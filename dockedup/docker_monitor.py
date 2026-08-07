"""
Docker container monitoring with real-time stats collection.
"""

import threading
import logging
import time
from collections import defaultdict
from typing import Dict, List, Any, Optional
from http.client import IncompleteRead

from docker.client import DockerClient
from docker.errors import DockerException, NotFound

from .utils import (
    format_status,
    format_ports,
    get_compose_project_name,
    format_memory_stats,
    calculate_cpu_percent,
    parse_docker_time,
)

logger = logging.getLogger("dockedup")


class ContainerMonitor:
    """
    Monitors Docker containers and collects real-time statistics.

    This class maintains a real-time view of all containers, their states,
    and resource usage statistics through Docker's event stream and stats API.
    """

    def __init__(self, client: DockerClient, enable_stats: bool = True):
        self.client = client
        self.containers: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.stats_threads: Dict[str, threading.Thread] = {}
        self._event_thread: Optional[threading.Thread] = None
        self.enable_stats = enable_stats
        self._is_remote_connection = self._check_remote_connection()

    def _check_remote_connection(self) -> bool:
        """Check if this is a remote Docker connection (SSH, TCP)."""
        try:
            base_url = self.client.api.base_url
            return base_url.startswith(("ssh://", "tcp://", "http://")) if base_url else False
        except Exception:
            return False

    def _stats_worker(self, container_id: str):
        """
        Collect real-time stats for a specific container.

        Args:
            container_id: The container ID to monitor
        """
        retry_count = 0
        max_retries = 3 if self._is_remote_connection else 1
        backoff_delay = 2.0

        while retry_count <= max_retries and not self.stop_event.is_set():
            try:
                logger.debug(
                    f"Starting stats collection for container {container_id[:12]} (attempt {retry_count + 1})"
                )

                # For remote connections, use non-streaming stats with polling
                if self._is_remote_connection:
                    while not self.stop_event.is_set():
                        with self.lock:
                            if container_id not in self.containers:
                                logger.debug(
                                    f"Container {container_id[:12]} removed during stats collection"
                                )
                                return

                        try:
                            # Get single stats snapshot (stream=False)
                            stats = self.client.api.stats(
                                container=container_id, stream=False, decode=True
                            )

                            with self.lock:
                                if container_id in self.containers:
                                    self.containers[container_id]["cpu"] = calculate_cpu_percent(
                                        stats
                                    )
                                    self.containers[container_id]["memory"] = format_memory_stats(
                                        stats.get("memory_stats", {})
                                    )
                                else:
                                    logger.debug(
                                        f"Container {container_id[:12]} removed during stats collection"
                                    )
                                    return

                            # Poll interval for remote connections (reduce network overhead)
                            time.sleep(2.0)

                        except (IncompleteRead, ConnectionError, BrokenPipeError) as e:
                            logger.debug(
                                f"Network error getting stats for {container_id[:12]}: {e}"
                            )
                            # Don't remove container, just retry after delay
                            time.sleep(1.0)
                            continue

                else:
                    # Local connection: use streaming stats
                    stats_stream = self.client.api.stats(
                        container=container_id, stream=True, decode=True
                    )

                    for stats in stats_stream:
                        if self.stop_event.is_set():
                            logger.debug(
                                f"Stop event set, ending stats collection for {container_id[:12]}"
                            )
                            return

                        with self.lock:
                            if container_id in self.containers:
                                self.containers[container_id]["cpu"] = calculate_cpu_percent(stats)
                                self.containers[container_id]["memory"] = format_memory_stats(
                                    stats.get("memory_stats", {})
                                )
                            else:
                                logger.debug(
                                    f"Container {container_id[:12]} removed during stats collection"
                                )
                                return

                # If we got here without exception, stats collection completed successfully
                return

            except NotFound as e:
                logger.debug(f"Container {container_id[:12]} not found: {e}")
                # Container was removed, this is expected
                self._remove_container(container_id)
                return

            except (IncompleteRead, ConnectionError, BrokenPipeError, OSError) as e:
                retry_count += 1
                logger.warning(
                    f"Network error in stats worker for {container_id[:12]} (attempt {retry_count}/{max_retries + 1}): {e}"
                )

                if retry_count > max_retries:
                    logger.warning(
                        f"Max retries reached for {container_id[:12]}, disabling stats (container still visible)"
                    )
                    # Don't remove container, just stop collecting stats
                    with self.lock:
                        if container_id in self.containers:
                            self.containers[container_id]["cpu"] = "[grey50]—[/grey50]"
                            self.containers[container_id]["memory"] = "[grey50]—[/grey50]"
                    return

                # Exponential backoff before retry
                time.sleep(backoff_delay * retry_count)

            except DockerException as e:
                logger.debug(f"Docker error in stats worker for {container_id[:12]}: {e}")
                # Don't remove container on generic Docker errors
                with self.lock:
                    if container_id in self.containers:
                        self.containers[container_id]["cpu"] = "[grey50]—[/grey50]"
                        self.containers[container_id]["memory"] = "[grey50]—[/grey50]"
                return

            except Exception as e:
                logger.error(f"Unexpected error in stats worker for {container_id[:12]}: {e}")
                # Don't remove container on unexpected errors
                with self.lock:
                    if container_id in self.containers:
                        self.containers[container_id]["cpu"] = "[grey50]—[/grey50]"
                        self.containers[container_id]["memory"] = "[grey50]—[/grey50]"
                return

    def _event_worker(self):
        """
        Listen for Docker events and update container states accordingly.

        This method runs in a separate thread and processes Docker daemon events
        to keep the container list and states synchronized.
        """
        try:
            logger.debug("Starting Docker event listener")
            event_filter = {"type": "container"}

            for event in self.client.events(decode=True, filters=event_filter):
                if self.stop_event.is_set():
                    logger.debug("Stop event set, ending event listener")
                    break

                if event.get("Type") == "container":
                    self._handle_container_event(event)

        except (DockerException, StopIteration) as e:
            logger.debug(f"Event stream ended: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in event worker: {e}")

    def _handle_container_event(self, event: Dict[str, Any]):
        """
        Process a container event from Docker daemon.

        Args:
            event: Docker event dictionary
        """
        status = event.get("status")
        container_id = event.get("id")

        if not container_id:
            return

        logger.debug(f"Container event: {status} for {container_id[:12]}")

        if status == "destroy":
            self._remove_container(container_id)
        else:
            self._add_or_update_container(container_id)

    def _add_or_update_container(self, container_id: str):
        """
        Add or update a container in the monitoring list.

        Args:
            container_id: The container ID to add/update
        """
        try:
            container_info = self.client.api.inspect_container(container_id)
            state = container_info.get("State", {})
            health = state.get("Health", {})
            config = container_info.get("Config", {})
            host_config = container_info.get("HostConfig", {})
            network_settings = container_info.get("NetworkSettings", {})

            project_name = get_compose_project_name(config.get("Labels", {}))
            logger.debug(f"Container {container_id[:12]} assigned to project: {project_name}")

            status_display, health_display = format_status(
                state.get("Status", "unknown"), health.get("Status")
            )

            mounts = [
                f"{m.get('Source', '?')} -> {m.get('Destination', '?')} ({m.get('Mode', '')})"
                for m in container_info.get("Mounts", [])
            ]

            with self.lock:
                existing_stats = self.containers.get(container_id, {})

                self.containers[container_id] = {
                    "id": container_info.get("Id"),
                    "name": container_info.get("Name", "").lstrip("/"),
                    "status": status_display,
                    "health": health_display,
                    "started_at": parse_docker_time(state.get("StartedAt")),
                    "created": container_info.get("Created"),
                    "ports": format_ports(network_settings.get("Ports", {})),
                    "project": project_name,
                    "cpu": existing_stats.get("cpu", "[grey50]—[/grey50]"),
                    "memory": existing_stats.get("memory", "[grey50]—[/grey50]"),
                    "image": config.get("Image", ""),
                    "command": " ".join(config.get("Cmd") or []),
                    "entrypoint": " ".join(config.get("Entrypoint") or []),
                    "mounts": mounts,
                    "networks": list(network_settings.get("Networks", {}).keys()),
                    "restart_policy": host_config.get("RestartPolicy", {}).get("Name", "no"),
                }

            is_running = state.get("Status") == "running"
            has_stats_thread = container_id in self.stats_threads

            if is_running and not has_stats_thread and self.enable_stats:
                thread = threading.Thread(
                    target=self._stats_worker,
                    args=(container_id,),
                    daemon=True,
                    name=f"stats-{container_id[:12]}",
                )
                self.stats_threads[container_id] = thread
                thread.start()
                logger.debug(f"Started stats thread for {container_id[:12]}")

            elif not is_running and has_stats_thread:
                del self.stats_threads[container_id]
                logger.debug(f"Removed stats thread for {container_id[:12]}")

        except (NotFound, DockerException) as e:
            logger.debug(f"Failed to inspect container {container_id[:12]}: {e}")
            self._remove_container(container_id)
        except Exception as e:
            logger.error(f"Unexpected error updating container {container_id[:12]}: {e}")
            self._remove_container(container_id)

    def _remove_container(self, container_id: str):
        """
        Remove a container from monitoring.

        Args:
            container_id: The container ID to remove
        """
        logger.debug(f"Removing container {container_id[:12]}")

        with self.lock:
            if container_id in self.containers:
                del self.containers[container_id]

        if container_id in self.stats_threads:
            del self.stats_threads[container_id]

    def initial_populate(self):
        """
        Populate the initial list of containers.

        This method is called once at startup to discover all existing containers.
        """
        try:
            logger.debug("Performing initial container discovery")
            containers = self.client.containers.list(all=True)
            logger.debug(f"Found {len(containers)} containers")

            for container in containers:
                self._add_or_update_container(container.id)

        except DockerException as e:
            logger.error(f"Failed to list containers during initial populate: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during initial populate: {e}")

    def run(self):
        """
        Start the container monitoring system.

        This method starts the event listener thread and populates the initial
        container list.
        """
        logger.debug("Starting container monitor")

        self.initial_populate()

        self._event_thread = threading.Thread(
            target=self._event_worker, daemon=True, name="docker-events"
        )
        self._event_thread.start()

        logger.debug("Container monitor started successfully")

    def stop(self):
        """
        Stop the container monitoring system.

        This method signals all threads to stop and waits for them to finish.
        """
        logger.debug("Stopping container monitor")
        self.stop_event.set()

        try:
            self.client.close()
            logger.debug("Docker client closed, interrupting worker threads.")
        except Exception as e:
            logger.debug(f"Error closing docker client: {e}")

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=1.0)

        active_threads = list(self.stats_threads.values())
        for thread in active_threads:
            if thread.is_alive():
                thread.join(timeout=0.5)

        self.stats_threads.clear()

        logger.debug("Container monitor stopped")

    def get_grouped_containers(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get containers grouped by Docker Compose project.

        Returns:
            Dictionary mapping project names to lists of container dictionaries
        """
        with self.lock:
            containers_copy = list(self.containers.values())

        grouped = defaultdict(list)

        for container in containers_copy:
            project_name = container.get("project", "(No Project)")
            grouped[project_name].append(container)
            logger.debug(f"Grouped container {container['name']} under project {project_name}")

        for project in grouped:
            grouped[project].sort(key=lambda c: c.get("name", ""))

        return dict(sorted(grouped.items()))

    def get_container_count(self) -> int:
        """
        Get the total number of monitored containers.

        Returns:
            Number of containers currently being monitored
        """
        with self.lock:
            return len(self.containers)

    def get_running_container_count(self) -> int:
        """
        Get the number of running containers.

        Returns:
            Number of containers in running state
        """
        with self.lock:
            return sum(1 for c in self.containers.values() if "✅ Up" in c.get("status", ""))
