from typing import Tuple, Dict, Any, List

def format_status(container_status: str, health_status: str | None) -> Tuple[str, str]:
    """
    Formats the container status and health into a colorized, emoji-led string.
    """
    # Status Formatting
    if "running" in container_status or "up" in container_status:
        status_display = f"[green]✅ Up[/green]"
    elif "restarting" in container_status:
        status_display = f"[yellow]🔁 Restarting[/yellow]"
    elif "exited" in container_status or "dead" in container_status:
        status_display = f"[red]❌ Down[/red]"
    else:
        status_display = f"[grey50]❓ {container_status.capitalize()}[/grey50]"

    # Health Formatting
    if not health_status:
        health_display = "[grey50]—[/grey50]"
    elif health_status == "healthy":
        health_display = "[green]🟢 Healthy[/green]"
    elif health_status == "unhealthy":
        health_display = "[red]🔴 Unhealthy[/red]"
    elif health_status == "starting":
        health_display = "[yellow]🟡 Starting[/yellow]"
    else:
        health_display = f"[grey50]{health_status}[/grey50]"

    return status_display, health_display

def format_ports(port_data: Dict[str, Any]) -> str:
    """
    Formats the port mappings into a readable string like '8000->8000/tcp'.
    """
    if not port_data:
        return "[grey50]—[/grey50]"

    parts = []
    for container_port, host_bindings in port_data.items():
        if host_bindings:
            # Typically, we only care about the first host binding for a clean display
            host_port = host_bindings[0].get("HostPort", "?")
            host_ip = host_bindings[0].get("HostIp", "0.0.0.0")
            
            # Don't show the default 0.0.0.0 IP unless it's something else
            ip_prefix = "" if host_ip in ["0.0.0.0", "::"] else f"{host_ip}:"
            
            parts.append(f"{ip_prefix}{host_port} -> {container_port}")
        else:
            # Port is exposed but not mapped
            parts.append(f"{container_port} (exposed)")
    
    return "\n".join(parts)

def get_compose_project_name(labels: Dict[str, str]) -> str:
    """
    Extracts the Docker Compose project name from container labels.
    """
    return labels.get("com.docker.compose.project", "(No Project)")
