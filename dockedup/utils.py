from typing import Tuple, Dict, Any, List

def format_status(container_status: str, health_status: str | None) -> Tuple[str, str]:
    """
    Formats the container status and health into a colorized, emoji-led string.
    """
    if "running" in container_status or "up" in container_status:
        status_display = f"[green]✅ Up[/green]"
    elif "restarting" in container_status:
        status_display = f"[yellow]🔁 Restarting[/yellow]"
    elif "exited" in container_status or "dead" in container_status:
        status_display = f"[red]❌ Down[/red]"
    else:
        status_display = f"[grey50]❓ {container_status.capitalize()}[/grey50]"

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
            host_port = host_bindings[0].get("HostPort", "?")
            host_ip = host_bindings[0].get("HostIp", "0.0.0.0")
            
            ip_prefix = "" if host_ip in ["0.0.0.0", "::"] else f"{host_ip}:"
            
            parts.append(f"{ip_prefix}{host_port} -> {container_port}")
        else:
            parts.append(f"[dim]{container_port}[/dim]")
    
    return "\n".join(parts)

def get_compose_project_name(labels: Dict[str, str]) -> str:
    """
    Extracts the Docker Compose project name from container labels.
    """
    return labels.get("com.docker.compose.project", "(No Project)")

def _format_bytes(size: int) -> str:
    """Helper to format bytes into KiB, MiB, GiB etc."""
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size >= power and n < len(power_labels):
        size /= power
        n += 1
    return f"{size:.1f}{power_labels[n]}iB"

def format_memory_stats(mem_stats: Dict[str, Any]) -> str:
    """Formats memory stats into a 'Usage / Limit (Percent)' string."""
    usage = mem_stats.get('usage')
    limit = mem_stats.get('limit')

    if usage is None or limit is None:
        return "[grey50]—[/grey50]"
    
    mem_percent = (usage / limit) * 100.0
    
    color = "cyan"
    if mem_percent > 85.0:
        color = "red"
    elif mem_percent > 60.0:
        color = "yellow"

    return f"[{color}]{_format_bytes(usage)} / {_format_bytes(limit)} ({mem_percent:.1f}%)[/{color}]"

def calculate_cpu_percent(stats: Dict[str, Any]) -> str:
    """Calculates CPU percentage from a Docker stats object."""
    try:
        cpu_stats = stats.get('cpu_stats', {})
        precpu_stats = stats.get('precpu_stats', {})

        cpu_usage = cpu_stats.get('cpu_usage', {})
        precpu_usage = precpu_stats.get('cpu_usage', {})

        cpu_delta = cpu_usage.get('total_usage', 0) - precpu_usage.get('total_usage', 0)
        system_cpu_delta = cpu_stats.get('system_cpu_usage', 0) - precpu_stats.get('system_cpu_usage', 0)
        
        online_cpus = cpu_stats.get('online_cpus', 0)
        if online_cpus == 0:
            online_cpus = len(cpu_usage.get('percpu_usage', [1]))

        if system_cpu_delta > 0.0 and cpu_delta > 0.0:
            percent = (cpu_delta / system_cpu_delta) * online_cpus * 100.0
            
            color = "cyan"
            if percent > 80.0:
                color = "red"
            elif percent > 50.0:
                color = "yellow"
            
            return f"[{color}]{percent:.2f}%[/{color}]"
    except (KeyError, TypeError, ZeroDivisionError):
        return "[grey50]—[/grey50]"
    
    return "[grey50]0.00%[/grey50]"