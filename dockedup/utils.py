from datetime import datetime, timezone
from typing import Tuple, Dict, Any, List

def format_status(container_status: str, health_status: str | None) -> Tuple[str, str]:
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
    return labels.get("com.docker.compose.project", "(No Project)")

def parse_docker_time(time_str: str | None) -> datetime | None:
    if not time_str or time_str.startswith("0001-01-01"):
        return None
    try:
        # Truncate to microseconds and handle Z suffix
        if '.' in time_str:
            main_part, fractional_part = time_str.split('.', 1)
            fractional_part = fractional_part.rstrip('Z')
            fractional_part = fractional_part[:6]
            time_str = f"{main_part}.{fractional_part}"
        else:
            time_str = time_str.rstrip('Z')
        
        dt = datetime.fromisoformat(time_str)
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None

def format_uptime(start_time: datetime | None) -> str:
    if not start_time:
        return "[grey50]—[/grey50]"
    
    now = datetime.now(timezone.utc)
    delta = now - start_time
    
    seconds = int(delta.total_seconds())
    if seconds < 0: return "[grey50]—[/grey50]"
    
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0: return f"{days}d {hours}h"
    if hours > 0: return f"{hours}h {minutes}m"
    if minutes > 0: return f"{minutes}m {seconds}s"
    return f"{seconds}s"

def _format_bytes(size: int) -> str:
    power = 1024; n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size >= power and n < len(power_labels):
        size /= power; n += 1
    return f"{size:.1f}{power_labels[n]}iB"

def format_memory_stats(mem_stats: Dict[str, Any]) -> str:
    usage = mem_stats.get('usage'); limit = mem_stats.get('limit')
    if usage is None or limit is None: return "[grey50]—[/grey50]"
    mem_percent = (usage / limit) * 100.0
    color = "cyan"
    if mem_percent > 85.0: color = "red"
    elif mem_percent > 60.0: color = "yellow"
    return f"[{color}]{_format_bytes(usage)} / {_format_bytes(limit)} ({mem_percent:.1f}%)[/{color}]"

def calculate_cpu_percent(stats: Dict[str, Any]) -> str:
    try:
        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage']['total_usage']
        system_cpu_delta = stats['cpu_stats']['system_cpu_usage'] - stats['precpu_stats']['system_cpu_usage']
        online_cpus = stats['cpu_stats'].get('online_cpus', len(stats['cpu_stats']['cpu_usage'].get('percpu_usage', [1])))

        if system_cpu_delta > 0.0 and cpu_delta > 0.0:
            percent = (cpu_delta / system_cpu_delta) * online_cpus * 100.0
            color = "cyan"
            if percent > 80.0: color = "red"
            elif percent > 50.0: color = "yellow"
            return f"[{color}]{percent:.2f}%[/{color}]"
    except (KeyError, ZeroDivisionError, TypeError): return "[grey50]—[/grey50]"
    return "[grey50]0.00%[/grey50]"