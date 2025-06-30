"""
Utility functions for Docker container monitoring and formatting.
"""

import logging
from datetime import datetime, timezone
from typing import Tuple, Dict, Any, Optional

logger = logging.getLogger("dockedup")

def format_status(container_status: str, health_status: Optional[str]) -> Tuple[str, str]:
    """
    Format container status and health status with appropriate colors and icons.
    
    Args:
        container_status: Container status from Docker API
        health_status: Health check status from Docker API
        
    Returns:
        Tuple of (formatted_status, formatted_health)
    """
    # Normalize status to lowercase for comparison
    status_lower = container_status.lower()
    
    if "running" in status_lower or "up" in status_lower:
        status_display = "[green]✅ Up[/green]"
    elif "restarting" in status_lower:
        status_display = "[yellow]🔁 Restarting[/yellow]"
    elif "paused" in status_lower:
        status_display = "[blue]⏸️  Paused[/blue]"
    elif "exited" in status_lower:
        status_display = "[red]❌ Exited[/red]"
    elif "dead" in status_lower:
        status_display = "[red]💀 Dead[/red]"
    elif "created" in status_lower:
        status_display = "[grey50]📦 Created[/grey50]"
    elif "removing" in status_lower:
        status_display = "[orange1]🗑️  Removing[/orange1]"
    else:
        status_display = f"[grey50]❓ {container_status.capitalize()}[/grey50]"

    # Format health status
    if not health_status:
        health_display = "[grey50]—[/grey50]"
    elif health_status == "healthy":
        health_display = "[green]🟢 Healthy[/green]"
    elif health_status == "unhealthy":
        health_display = "[red]🔴 Unhealthy[/red]"
    elif health_status == "starting":
        health_display = "[yellow]🟡 Starting[/yellow]"
    elif health_status == "none":
        health_display = "[grey50]—[/grey50]"
    else:
        health_display = f"[grey50]❓ {health_status}[/grey50]"

    return status_display, health_display

def format_ports(port_data: Dict[str, Any]) -> str:
    """
    Format port mappings for display.
    
    Args:
        port_data: Port mapping data from Docker API
        
    Returns:
        Formatted port string
    """
    if not port_data:
        return "[grey50]—[/grey50]"
    
    parts = []
    
    try:
        for container_port, host_bindings in port_data.items():
            if host_bindings:
                for binding in host_bindings:
                    host_port = binding.get("HostPort", "?")
                    host_ip = binding.get("HostIp", "0.0.0.0")
                    
                    # Simplify display for common cases
                    if host_ip in ["0.0.0.0", "::", ""]:
                        parts.append(f"[cyan]{host_port}[/cyan] → {container_port}")
                    else:
                        parts.append(f"[cyan]{host_ip}:{host_port}[/cyan] → {container_port}")
            else:
                parts.append(f"[dim]{container_port}[/dim]")
                
    except Exception as e:
        logger.debug(f"Error formatting ports: {e}")
        return "[red]Error[/red]"
    
    # Limit display to avoid overwhelming the UI
    if len(parts) > 3:
        displayed = parts[:3]
        displayed.append(f"[dim]... +{len(parts) - 3} more[/dim]")
        parts = displayed
    
    return "\n".join(parts)

def get_compose_project_name(labels: Dict[str, str]) -> str:
    """
    Extract Docker Compose project name from container labels.
    
    Args:
        labels: Container labels from Docker API
        
    Returns:
        Project name or default value
    """
    # Try various label keys that might contain the project name
    project_keys = [
        "com.docker.compose.project",
        "com.docker.compose.project.working_dir",
        "org.label-schema.docker.compose.project",
    ]
    
    for key in project_keys:
        if key in labels:
            project_name = labels[key].strip()
            if project_name:
                return project_name
    
    # Fallback: try to extract from container name patterns
    # This is a best-effort attempt for containers not managed by compose
    return "(No Project)"

def parse_docker_time(time_str: Optional[str]) -> Optional[datetime]:
    """
    Parse Docker timestamp string into datetime object.
    
    Docker timestamps are in RFC3339 format with varying precision.
    
    Args:
        time_str: Timestamp string from Docker API
        
    Returns:
        Parsed datetime object or None if parsing fails
    """
    if not time_str or time_str.startswith("0001-01-01"):
        return None
    
    try:
        # Handle different timestamp formats from Docker
        time_str = time_str.strip()
        
        # Remove 'Z' suffix and handle fractional seconds
        if time_str.endswith('Z'):
            time_str = time_str[:-1]
        
        # Truncate microseconds to 6 digits (Python datetime limitation)
        if '.' in time_str:
            main_part, fractional_part = time_str.split('.', 1)
            fractional_part = fractional_part[:6].ljust(6, '0')
            time_str = f"{main_part}.{fractional_part}"
        
        # Parse the timestamp
        dt = datetime.fromisoformat(time_str)
        
        # Ensure timezone is UTC if not specified
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        return dt
        
    except (ValueError, TypeError) as e:
        logger.debug(f"Failed to parse Docker timestamp '{time_str}': {e}")
        return None

def format_uptime(start_time: Optional[datetime]) -> str:
    """
    Format container uptime in human-readable format.
    
    Args:
        start_time: Container start time
        
    Returns:
        Formatted uptime string
    """
    if not start_time:
        return "[grey50]—[/grey50]"
    
    try:
        now = datetime.now(timezone.utc)
        
        # Ensure both timestamps have timezone info
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        
        delta = now - start_time
        total_seconds = int(delta.total_seconds())
        
        if total_seconds < 0:
            return "[grey50]—[/grey50]"
        
        # Format based on duration
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        if days > 0:
            return f"[green]{days}d {hours}h[/green]"
        elif hours > 0:
            return f"[green]{hours}h {minutes}m[/green]"
        elif minutes > 0:
            return f"[yellow]{minutes}m {seconds}s[/yellow]"
        else:
            return f"[cyan]{seconds}s[/cyan]"
            
    except Exception as e:
        logger.debug(f"Error formatting uptime: {e}")
        return "[red]Error[/red]"

def _format_bytes(size: int) -> str:
    """
    Format byte size in human-readable format.
    
    Args:
        size: Size in bytes
        
    Returns:
        Formatted size string
    """
    if size < 0:
        return "0B"
    
    power = 1024
    n = 0
    power_labels = {0: 'B', 1: 'K', 2: 'M', 3: 'G', 4: 'T', 5: 'P'}
    
    while size >= power and n < len(power_labels) - 1:
        size /= power
        n += 1
    
    if n == 0:
        return f"{int(size)}B"
    else:
        return f"{size:.1f}{power_labels[n]}iB"

def format_memory_stats(mem_stats: Dict[str, Any]) -> str:
    """
    Format memory statistics for display.
    
    Args:
        mem_stats: Memory statistics from Docker stats API
        
    Returns:
        Formatted memory usage string
    """
    try:
        usage = mem_stats.get('usage')
        limit = mem_stats.get('limit')
        
        if usage is None or limit is None or limit == 0:
            return "[grey50]—[/grey50]"
        
        # Calculate percentage
        mem_percent = (usage / limit) * 100.0
        
        # Choose color based on usage
        if mem_percent > 90.0:
            color = "red"
        elif mem_percent > 75.0:
            color = "yellow"
        elif mem_percent > 50.0:
            color = "blue"
        else:
            color = "green"
        
        usage_str = _format_bytes(usage)
        limit_str = _format_bytes(limit)
        
        return f"[{color}]{usage_str} / {limit_str} ({mem_percent:.1f}%)[/{color}]"
        
    except (KeyError, TypeError, ZeroDivisionError) as e:
        logger.debug(f"Error formatting memory stats: {e}")
        return "[grey50]—[/grey50]"

def calculate_cpu_percent(stats: Dict[str, Any]) -> str:
    """
    Calculate CPU usage percentage from Docker stats.
    
    Args:
        stats: Stats data from Docker stats API
        
    Returns:
        Formatted CPU percentage string
    """
    try:
        # Extract CPU stats
        cpu_stats = stats.get('cpu_stats', {})
        precpu_stats = stats.get('precpu_stats', {})
        
        cpu_usage = cpu_stats.get('cpu_usage', {})
        precpu_usage = precpu_stats.get('cpu_usage', {})
        
        total_usage = cpu_usage.get('total_usage', 0)
        prev_total_usage = precpu_usage.get('total_usage', 0)
        
        system_usage = cpu_stats.get('system_cpu_usage', 0)
        prev_system_usage = precpu_stats.get('system_cpu_usage', 0)
        
        # Calculate deltas
        cpu_delta = total_usage - prev_total_usage
        system_cpu_delta = system_usage - prev_system_usage
        
        # Get number of CPUs
        online_cpus = cpu_stats.get('online_cpus')
        if online_cpus is None:
            # Fallback to percpu_usage length
            percpu_usage = cpu_usage.get('percpu_usage', [])
            online_cpus = len(percpu_usage) if percpu_usage else 1
        
        # Calculate percentage
        if system_cpu_delta > 0.0 and cpu_delta >= 0.0:
            percent = (cpu_delta / system_cpu_delta) * online_cpus * 100.0
            
            # Clamp to reasonable range
            percent = max(0.0, min(percent, 100.0 * online_cpus))
            
            # Choose color based on usage
            if percent > 80.0:
                color = "red"
            elif percent > 60.0:
                color = "yellow"
            elif percent > 30.0:
                color = "blue"
            else:
                color = "green"
            
            return f"[{color}]{percent:.1f}%[/{color}]"
        else:
            return "[green]0.0%[/green]"
            
    except (KeyError, TypeError, ZeroDivisionError) as e:
        logger.debug(f"Error calculating CPU percentage: {e}")
        return "[grey50]—[/grey50]"

def validate_refresh_rate(rate: float) -> bool:
    """
    Validate refresh rate parameter.
    
    Args:
        rate: Refresh rate in seconds
        
    Returns:
        True if valid, False otherwise
    """
    return 0.1 <= rate <= 60.0

def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate string to maximum length with suffix.
    
    Args:
        text: String to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to add when truncating
        
    Returns:
        Truncated string
    """
    if len(text) <= max_length:
        return text
    
    if max_length <= len(suffix):
        return suffix[:max_length]
    
    return text[:max_length - len(suffix)] + suffix

def safe_get_nested(data: Dict[str, Any], keys: list, default: Any = None) -> Any:
    """
    Safely get nested dictionary value.
    
    Args:
        data: Dictionary to search
        keys: List of keys to traverse
        default: Default value if key path doesn't exist
        
    Returns:
        Value at key path or default
    """
    try:
        current = data
        for key in keys:
            current = current[key]
        return current
    except (KeyError, TypeError):
        return default