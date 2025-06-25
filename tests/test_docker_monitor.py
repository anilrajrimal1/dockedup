from unittest.mock import MagicMock
from collections import defaultdict
import pytest
from docker.errors import DockerException

from dockedup.docker_monitor import get_grouped_containers, get_docker_client

@pytest.fixture
def mock_docker_client(mocker):
    """Fixture to mock the Docker client and its container list."""
    mock_client = MagicMock()

    # Mock Container 1: Healthy, in a project
    container1 = MagicMock()
    container1.name = "backend-service"
    container1.status = "running"
    container1.labels = {"com.docker.compose.project": "my-app"}
    container1.ports = {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8000"}]}
    container1.attrs = {
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
        "Config": {"Labels": container1.labels}
    }
    
    # Mock Container 2: Restarting, in the same project
    container2 = MagicMock()
    container2.name = "redis-cache"
    container2.status = "restarting"
    container2.labels = {"com.docker.compose.project": "my-app"}
    container2.ports = {"6379/tcp": [{"HostIp": "0.0.0.0", "HostPort": "6379"}]}
    container2.attrs = {
        "State": {"Status": "restarting"},
        "Config": {"Labels": container2.labels}
    }

    # Mock Container 3: Exited, no project label
    container3 = MagicMock()
    container3.name = "old-container"
    container3.status = "exited"
    container3.labels = {}
    container3.ports = {}
    container3.attrs = {
        "State": {"Status": "exited"},
        "Config": {"Labels": container3.labels}
    }

    mock_client.containers.list.return_value = [container1, container2, container3]
    return mock_client

def test_get_grouped_containers(mock_docker_client):
    """Test if containers are fetched, formatted, and grouped correctly."""
    grouped_data = get_grouped_containers(mock_docker_client)

    # Check that we have two groups: 'my-app' and '(No Project)'
    assert len(grouped_data) == 2
    assert "my-app" in grouped_data
    assert "(No Project)" in grouped_data

    # Check the 'my-app' project
    my_app_containers = grouped_data["my-app"]
    assert len(my_app_containers) == 2
    
    # Note: The list is sorted by name, so 'backend-service' should be first
    assert my_app_containers[0]["name"] == "backend-service"
    assert "✅ Up" in my_app_containers[0]["status"]
    assert "🟢 Healthy" in my_app_containers[0]["health"]
    assert "8000 -> 8000/tcp" in my_app_containers[0]["ports"]

    assert my_app_containers[1]["name"] == "redis-cache"
    assert "🔁 Restarting" in my_app_containers[1]["status"]
    assert "—" in my_app_containers[1]["health"] # No health check defined

    # Check the '(No Project)' group
    no_project_containers = grouped_data["(No Project)"]
    assert len(no_project_containers) == 1
    assert no_project_containers[0]["name"] == "old-container"
    assert "❌ Down" in no_project_containers[0]["status"]

def test_get_docker_client_failure(mocker):
    """Test that get_docker_client raises an exception on failure."""
    mocker.patch('docker.from_env', side_effect=DockerException("Test error"))
    
    with pytest.raises(DockerException, match="Failed to connect to Docker daemon"):
        get_docker_client()