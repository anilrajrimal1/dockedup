from collections import defaultdict
from typing import Dict, List, TypedDict

import docker
from docker.errors import DockerException, NotFound

from .utils import (
    format_status, 
    format_ports, 
    get_compose_project_name,
    format_memory_stats,
    calculate_cpu_percent,
    format_uptime
)

class FormattedContainer(TypedDict):
    """A dictionary representing a container with formatted data for display."""
    name: str
    status: str
    health: str
    ports: str
    project: str
    cpu: str
    memory: str
    uptime: str

def get_docker_client() -> docker.DockerClient:
    """Initializes and returns a Docker client."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except DockerException as e:
        raise DockerException("Failed to connect to Docker daemon. Is it running?") from e

def get_grouped_containers(client: docker.DockerClient) -> Dict[str, List[FormattedContainer]]:
    """Fetches all containers, their stats, and groups them by Docker Compose project."""
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

        uptime_display = format_uptime(state.get("StartedAt"))

        cpu_display = "[grey50]—[/grey50]"
        mem_display = "[grey50]—[/grey50]"
        if container.status == 'running':
            try:
                stats = container.stats(stream=False)
                cpu_display = calculate_cpu_percent(stats)
                mem_display = format_memory_stats(stats.get('memory_stats', {}))
            except (NotFound, DockerException):
                pass

        formatted = FormattedContainer(
            name=container.name,
            status=status_display,
            health=health_display,
            ports=format_ports(container.ports),
            project=get_compose_project_name(container.labels),
            cpu=cpu_display,
            memory=mem_display,
            uptime=uptime_display
        )
        grouped_containers[formatted['project']].append(formatted)

    for project in grouped_containers:
        grouped_containers[project].sort(key=lambda c: c['name'])
        
    return dict(sorted(grouped_containers.items()))