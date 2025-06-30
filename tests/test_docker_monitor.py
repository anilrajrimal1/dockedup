import time
import threading
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import NotFound

from dockedup.docker_monitor import ContainerMonitor


# --- MOCK DATA FIXTURES ---

@pytest.fixture
def mock_container_data_running():
    """Mock data for a running container."""
    return {
        'Id': 'container1_id', 'Name': '/test-container-1',
        'State': {'Status': 'running', 'Health': {'Status': 'healthy'}, 'StartedAt': '2023-01-01T12:00:00.000000Z'},
        'NetworkSettings': {'Ports': {'80/tcp': [{'HostPort': '8080'}]}},
        'Config': {'Labels': {'com.docker.compose.project': 'my-project'}}
    }

@pytest.fixture
def mock_container_data_exited():
    """Mock data for an exited container."""
    return {
        'Id': 'container2_id', 'Name': '/test-container-2',
        'State': {'Status': 'exited', 'StartedAt': '0001-01-01T00:00:00Z'},
        'NetworkSettings': {'Ports': {}},
        'Config': {'Labels': {'com.docker.compose.project': 'my-project'}}
    }

@pytest.fixture
def mock_docker_client(mocker, mock_container_data_running, mock_container_data_exited):
    """A comprehensive mock of the Docker client."""
    mock_client = MagicMock()
    
    mock_container_obj1 = MagicMock(); mock_container_obj1.id = 'container1_id'
    mock_container_obj2 = MagicMock(); mock_container_obj2.id = 'container2_id'
    mock_client.containers.list.return_value = [mock_container_obj1, mock_container_obj2]

    # This dictionary will hold the current state for each mock container
    mock_db = {
        'container1_id': mock_container_data_running,
        'container2_id': mock_container_data_exited
    }
    
    def inspect_side_effect(container_id):
        if container_id in mock_db:
            return mock_db[container_id]
        raise NotFound("Container not found")
        
    mock_client.api.inspect_container.side_effect = inspect_side_effect
    
    # Add a reference to the mock_db so tests can manipulate state
    mock_client.mock_db = mock_db

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
    assert '[green]✅ Up[/green]' in monitor.containers['container1_id']['status']
    assert '[red]❌ Exited[/red]' in monitor.containers['container2_id']['status']


def test_monitor_handles_start_event(mock_docker_client):
    """Test if the monitor adds/updates a container on a 'start' event."""
    start_event = {'Type': 'container', 'status': 'start', 'id': 'container1_id'}
    mock_docker_client.events.return_value = iter([start_event])
    
    monitor = ContainerMonitor(mock_docker_client)
    monitor.run()
    time.sleep(0.1)
    monitor.stop()

    assert 'container1_id' in monitor.containers


def test_monitor_handles_stop_event_updates_status(mock_docker_client, mock_container_data_running):
    """Test 'die' event updates container status to Down, not removes it."""
    monitor = ContainerMonitor(mock_docker_client)
    monitor.initial_populate()
    assert '[green]✅ Up[/green]' in monitor.containers['container1_id']['status']
    
    # Simulate the container state changing to 'exited' in mock database
    stopped_state = mock_container_data_running.copy()
    stopped_state['State']['Status'] = 'exited'
    mock_docker_client.mock_db['container1_id'] = stopped_state
    
    stop_event = {'Type': 'container', 'status': 'die', 'id': 'container1_id'}
    mock_docker_client.events.return_value = iter([stop_event])
    
    monitor.run()
    time.sleep(0.1)
    monitor.stop()
    
    assert 'container1_id' in monitor.containers
    assert '[red]❌ Exited[/red]' in monitor.containers['container1_id']['status']


def test_monitor_handles_destroy_event_removes_container(mock_docker_client):
    """Test a 'destroy' event correctly removes the container from the list."""
    monitor = ContainerMonitor(mock_docker_client)
    monitor.initial_populate()
    assert 'container1_id' in monitor.containers

    destroy_event = {'Type': 'container', 'status': 'destroy', 'id': 'container1_id'}
    mock_docker_client.events.return_value = iter([destroy_event])
    
    monitor.run()
    time.sleep(0.1)
    monitor.stop()

    assert 'container1_id' not in monitor.containers


def test_monitor_stats_worker_updates_container(mock_docker_client):
    """Test if the stats worker correctly updates a container's CPU and Memory."""
    monitor = ContainerMonitor(mock_docker_client)
    
    mock_stats_data = {
        'cpu_stats': {
            'cpu_usage': {'total_usage': 2000},
            'system_cpu_usage': 10000,
            'online_cpus': 2
        },
        'precpu_stats': {
            'cpu_usage': {'total_usage': 1000},
            'system_cpu_usage': 5000
        },
        'memory_stats': {
            'usage': 1024 * 1024 * 50,
            'limit': 1024 * 1024 * 100
        }
    }
    mock_docker_client.api.stats.return_value = iter([mock_stats_data])
    
    monitor._add_or_update_container('container1_id')
    time.sleep(0.1)
    
    updated_container = monitor.containers['container1_id']
    assert '[blue]40.0%[/blue]' in updated_container['cpu']
    assert '50.0MiB / 100.0MiB (50.0%)' in updated_container['memory']
