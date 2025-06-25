import threading
from collections import defaultdict
from typing import Dict, List, Any
from datetime import datetime

import docker
from docker.client import DockerClient
from docker.errors import DockerException, NotFound

from .utils import (
    format_status, format_ports, get_compose_project_name,
    format_memory_stats, calculate_cpu_percent, parse_docker_time
)

class ContainerMonitor:
    def __init__(self, client: DockerClient):
        self.client = client
        self.containers: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.stats_threads: Dict[str, threading.Thread] = {}

    def _stats_worker(self, container_id: str):
        try:
            stats_stream = self.client.api.stats(container=container_id, stream=True, decode=True)
            for stats in stats_stream:
                if self.stop_event.is_set(): break
                with self.lock:
                    if container_id in self.containers:
                        self.containers[container_id]['cpu'] = calculate_cpu_percent(stats)
                        self.containers[container_id]['memory'] = format_memory_stats(stats.get('memory_stats', {}))
        except (NotFound, DockerException, StopIteration):
            self._remove_container(container_id)

    def _event_worker(self):
        try:
            for event in self.client.events(decode=True):
                if self.stop_event.is_set(): break
                if event.get('Type') == 'container':
                    self._handle_container_event(event)
        except (DockerException, StopIteration):
            pass

    def _handle_container_event(self, event: Dict[str, Any]):
        status = event.get('status')
        container_id = event.get('id')
        if not container_id: return

        if status in ['start', 'unpause'] or 'health_status' in status:
            self._add_or_update_container(container_id)
        elif status in ['die', 'destroy', 'stop', 'pause', 'kill', 'oom']:
            self._remove_container(container_id)

    def _add_or_update_container(self, container_id: str):
        try:
            container_info = self.client.api.inspect_container(container_id)
            state = container_info.get("State", {})
            health = state.get("Health", {})
            
            status_display, health_display = format_status(state.get("Status", "unknown"), health.get("Status"))
            
            with self.lock:
                self.containers[container_id] = {
                    'id': container_info.get("Id"),
                    'name': container_info.get("Name", "").lstrip('/'),
                    'status': status_display,
                    'health': health_display,
                    'started_at': parse_docker_time(state.get("StartedAt")),
                    'ports': format_ports(container_info.get("NetworkSettings", {}).get("Ports", {})),
                    'project': get_compose_project_name(container_info.get("Config", {}).get("Labels", {})),
                    'cpu': "[grey50]—[/grey50]",
                    'memory': "[grey50]—[/grey50]",
                }

            if state.get("Status") == 'running' and container_id not in self.stats_threads:
                thread = threading.Thread(target=self._stats_worker, args=(container_id,), daemon=True)
                self.stats_threads[container_id] = thread
                thread.start()
        except (NotFound, DockerException):
            self._remove_container(container_id)

    def _remove_container(self, container_id: str):
        with self.lock:
            if container_id in self.containers:
                del self.containers[container_id]
        if container_id in self.stats_threads:
            del self.stats_threads[container_id]

    def initial_populate(self):
        try:
            for container in self.client.containers.list(all=True):
                self._add_or_update_container(container.id)
        except DockerException:
            pass
    
    def run(self):
        self.initial_populate()
        event_thread = threading.Thread(target=self._event_worker, daemon=True)
        event_thread.start()

    def stop(self):
        self.stop_event.set()

    def get_grouped_containers(self) -> Dict[str, List[Dict[str, Any]]]:
        with self.lock:
            containers_copy = list(self.containers.values())
        
        grouped = defaultdict(list)
        for container in containers_copy:
            grouped[container['project']].append(container)
        
        for project in grouped:
            grouped[project].sort(key=lambda c: c['name'])
            
        return dict(sorted(grouped.items()))