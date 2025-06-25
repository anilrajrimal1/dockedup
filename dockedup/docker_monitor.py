from collections import defaultdict
from typing import Dict, List, TypedDict

import docker
from docker.models.containers import Container
from docker.errors import DockerException

from .utils import format_status, format_ports, get_compose_project_name

class FormattedContainer(TypedDict):
    """A dictionary representing a container with formatted data for display."""
    name: str
    status: str
    health: str
    ports: str
    project: str

def get_docker_client() -> docker.DockerClient:
    """
    Initializes and returns a Docker client.
    Raises DockerException if the client cannot be initialized.
    """
    try:
        client = docker.from_env()
        client.ping() # Verify the daemon is responsive
        return client
    except DockerException as e:
        raise DockerException(
            "Failed to connect to Docker daemon. Is it running?"
        ) from e


def get_grouped_containers(client: docker.DockerClient) -> Dict[str, List[FormattedContainer]]:
    """
    Fetches all containers and groups them by their Docker Compose project name.
    """
    containers = client.containers.list(all=True)
    
    grouped_containers = defaultdict(list)

    for container in containers:
        container_attrs = container.attrs
        state = container_attrs.get("State", {})
        health = state.get("Health", {})
        
        status_display, health_display = format_status(
            container_status=container.status,
            health_status=health.get("Status")
        )
        
        formatted = FormattedContainer(
            name=container.name,
            status=status_display,
            health=health_display,
            ports=format_ports(container.ports),
            project=get_compose_project_name(container.labels)
        )
        
        grouped_containers[formatted['project']].append(formatted)

    # Sort containers within each project by name
    for project in grouped_containers:
        grouped_containers[project].sort(key=lambda c: c['name'])
        
    return dict(sorted(grouped_containers.items()))