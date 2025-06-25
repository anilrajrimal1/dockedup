import time
import threading
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import NotFound

from dockedup.docker_monitor import ContainerMonitor

# --- MOCK DATA FIXTURES ---

@pytest.fixture
def mock_container_data_running():
    """Mock data for a running container from client.api.inspect_container."""
    return {
        'Id': 'container1_id',
        'Name': '/test-container-1',
        'State': {
            'Status': 'running',
            'Health': {'Status': 'healthy'},
            'StartedAt': '2023-01-01T12:00:00.000000Z'
        },
        'NetworkSettings': {'Ports': {'80/tcp': [{'HostPort': '8080'}]}},
        'Config': {'Labels': {'com.docker.compose.project': 'my-project'}}
    }

@pytest.fixture
def mock_container_data_exited():
    """Mock data for an exited container."""
    return {
        'Id': 'container2_id',
        'Name': '/test-container-2',
        'State': {'Status': 'exited', 'StartedAt': '0001-01-01T00:00:00Z'},
        'NetworkSettings': {'Ports': {}},
        'Config': {'Labels': {'com.docker.compose.project': 'my-project'}}
    }

@pytest.fixture
def mock_docker_client(mocker, mock_container_data_running, mock_container_data_exited):
    """A comprehensive mock of the Docker client."""
    mock_client = MagicMock()
    
    mock_container_obj1 = MagicMock()
    mock_container_obj1.id = 'container1_id'
    mock_container_obj2 = MagicMock()
    mock_container_obj2.id = 'container2_id'
    mock_client.containers.list.return_value = [mock_container_obj1, mock_container_obj2]

    def inspect_side_effect(container_id):
        if container_id == 'container1_id':
            return mock_container_data_running
        if container_id == 'container2_id':
            return mock_container_data_exited
        raise NotFound("Container not found")
        
    mock_client.api.inspect_container.side_effect = inspect_side_effect
    
    mock_client.events.return_value = iter([])
    mock_client.api.stats.return_value = iter([])
    
    mocker.patch('docker.from_env', return_value=mock_client)
    return mock_client


# --- TESTS ---

def test_monitor_initial_populate(mock_docker_client):
    """Test if the monitor correctly populates with initial containers."""
    monitor = ContainerMonitor(mock_docker_client)
    monitor.initial_populate()

    assert len(monitor.containers) == 2
    assert 'container1_id' in monitor.containers
    assert 'container2_id' in monitor.containers
    
    running_container = monitor.containers['container1_id']
    assert running_container['name'] == 'test-container-1'
    assert '✅ Up' in running_container['status']
    
    exited_container = monitor.containers['container2_id']
    assert exited_container['name'] == 'test-container-2'
    assert '❌ Down' in exited_container['status']

def test_monitor_handles_start_event(mock_docker_client, mock_container_data_running):
    """Test if the monitor adds a container when a 'start' event is received."""
    start_event = {'Type': 'container', 'status': 'start', 'id': 'container1_id'}
    mock_docker_client.events.return_value = iter([start_event])
    
    monitor = ContainerMonitor(mock_docker_client)
    monitor.containers.clear()
    
    event_thread = threading.Thread(target=monitor._event_worker, daemon=True)
    event_thread.start()
    
    time.sleep(0.1)
    monitor.stop_event.set()
    event_thread.join()

    assert 'container1_id' in monitor.containers
    assert monitor.containers['container1_id']['name'] == 'test-container-1'

def test_monitor_handles_stop_event(mock_docker_client):
    """Test if the monitor removes a container when a 'die' event is received."""
    monitor = ContainerMonitor(mock_docker_client)
    monitor.initial_populate()
    assert 'container1_id' in monitor.containers
    
    stop_event = {'Type': 'container', 'status': 'die', 'id': 'container1_id'}
    mock_docker_client.events.return_value = iter([stop_event])
    
    event_thread = threading.Thread(target=monitor._event_worker, daemon=True)
    event_thread.start()

    time.sleep(0.1)
    monitor.stop_event.set()
    event_thread.join()
    
    assert 'container1_id' not in monitor.containers
    assert 'container2_id' in monitor.containers

def test_monitor_stats_worker_updates_container(mock_docker_client):
    """Test if the stats worker correctly updates a container's CPU and Memory."""
    # Arrange: Setup the monitor and configure the mock BEFORE the action
    monitor = ContainerMonitor(mock_docker_client)
    
    mock_stats_data = {
        'cpu_stats': {'cpu_usage': {'total_usage': 2000}, 'system_cpu_usage': 10000, 'online_cpus': 2},
        'precpu_stats': {'cpu_usage': {'total_usage': 1000}, 'system_cpu_usage': 5000},
        'memory_stats': {'usage': 1024 * 1024 * 50, 'limit': 1024 * 1024 * 100} # 50MiB / 100MiB
    }
    mock_docker_client.api.stats.return_value = iter([mock_stats_data])

    # Act: Trigger the method that starts the stats thread
    monitor._add_or_update_container('container1_id')
    
    # Assert: Wait for the thread to process the stats and then check the result
    time.sleep(0.1) # Give the background thread a moment to run
    
    updated_container = monitor.containers['container1_id']
    assert '40.00%' in updated_container['cpu']
    assert '50.0MiB / 100.0MiB (50.0%)' in updated_container['memory']