from datetime import datetime, timedelta, timezone

import pytest

from dockedup.utils import (
    _format_bytes,
    calculate_cpu_percent,
    format_memory_stats,
    format_ports,
    format_status,
    format_uptime,
    get_compose_project_name,
    parse_docker_time,
    safe_get_nested,
    truncate_string,
    validate_refresh_rate,
)

# --- format_status ---


@pytest.mark.parametrize(
    "container_status,expected_fragment",
    [
        ("running", "✅ Up"),
        ("Up 2 hours", "✅ Up"),
        ("restarting", "🔁 Restarting"),
        ("paused", "⏸️"),
        ("exited", "❌ Exited"),
        ("dead", "💀 Dead"),
        ("created", "📦 Created"),
        ("removing", "🗑️"),
        ("something-weird", "❓ Something-weird"),
    ],
)
def test_format_status_container_status(container_status, expected_fragment):
    status_display, _ = format_status(container_status, None)
    assert expected_fragment in status_display


@pytest.mark.parametrize(
    "health_status,expected_fragment",
    [
        (None, "—"),
        ("none", "—"),
        ("healthy", "🟢 Healthy"),
        ("unhealthy", "🔴 Unhealthy"),
        ("starting", "🟡 Starting"),
        ("mystery", "❓ mystery"),
    ],
)
def test_format_status_health_status(health_status, expected_fragment):
    _, health_display = format_status("running", health_status)
    assert expected_fragment in health_display


# --- format_ports ---


def test_format_ports_empty():
    assert format_ports({}) == "[grey50]—[/grey50]"


def test_format_ports_single_binding():
    result = format_ports({"80/tcp": [{"HostPort": "8080", "HostIp": "0.0.0.0"}]})
    assert "8080" in result
    assert "80/tcp" in result


def test_format_ports_custom_host_ip():
    result = format_ports({"80/tcp": [{"HostPort": "8080", "HostIp": "127.0.0.1"}]})
    assert "127.0.0.1:8080" in result


def test_format_ports_unbound_port():
    result = format_ports({"80/tcp": None})
    assert "80/tcp" in result


def test_format_ports_truncates_after_three():
    port_data = {f"{i}/tcp": [{"HostPort": str(8000 + i), "HostIp": "0.0.0.0"}] for i in range(5)}
    result = format_ports(port_data)
    assert "+2 more" in result


# --- get_compose_project_name ---


@pytest.mark.parametrize(
    "label_key",
    [
        "com.docker.compose.project",
        "com.docker.compose.project.working_dir",
        "org.label-schema.docker.compose.project",
    ],
)
def test_get_compose_project_name_from_labels(label_key):
    assert get_compose_project_name({label_key: "my-project"}) == "my-project"


def test_get_compose_project_name_fallback():
    assert get_compose_project_name({}) == "(No Project)"


def test_get_compose_project_name_blank_value_falls_through():
    assert get_compose_project_name({"com.docker.compose.project": "  "}) == "(No Project)"


# --- parse_docker_time ---


def test_parse_docker_time_none():
    assert parse_docker_time(None) is None


def test_parse_docker_time_zero_date():
    assert parse_docker_time("0001-01-01T00:00:00Z") is None


def test_parse_docker_time_valid():
    dt = parse_docker_time("2023-01-01T12:00:00.000000Z")
    assert dt == datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_docker_time_truncates_long_fractional_seconds():
    dt = parse_docker_time("2023-01-01T12:00:00.123456789Z")
    assert dt is not None
    assert dt.microsecond == 123456


def test_parse_docker_time_invalid_string():
    assert parse_docker_time("not-a-timestamp") is None


# --- format_uptime ---


def test_format_uptime_none():
    assert format_uptime(None) == "[grey50]—[/grey50]"


def test_format_uptime_seconds():
    start = datetime.now(timezone.utc) - timedelta(seconds=5)
    assert "s[/cyan]" in format_uptime(start)


def test_format_uptime_minutes():
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert "m " in format_uptime(start) and "[yellow]" in format_uptime(start)


def test_format_uptime_hours():
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    assert "h " in format_uptime(start) and "[green]" in format_uptime(start)


def test_format_uptime_days():
    start = datetime.now(timezone.utc) - timedelta(days=3, hours=1)
    result = format_uptime(start)
    assert "3d" in result


def test_format_uptime_future_start_time():
    start = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert format_uptime(start) == "[grey50]—[/grey50]"


def test_format_uptime_naive_datetime_treated_as_utc():
    start = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(tzinfo=None)
    result = format_uptime(start)
    assert "[grey50]—[/grey50]" != result


# --- _format_bytes ---


@pytest.mark.parametrize(
    "size,expected",
    [
        (0, "0B"),
        (512, "512B"),
        (1024, "1.0KiB"),
        (1024 * 1024, "1.0MiB"),
        (1024 * 1024 * 1024, "1.0GiB"),
    ],
)
def test_format_bytes(size, expected):
    assert _format_bytes(size) == expected


def test_format_bytes_negative():
    assert _format_bytes(-5) == "0B"


# --- format_memory_stats ---


def test_format_memory_stats_missing_fields():
    assert format_memory_stats({}) == "[grey50]—[/grey50]"


def test_format_memory_stats_zero_limit():
    assert format_memory_stats({"usage": 100, "limit": 0}) == "[grey50]—[/grey50]"


@pytest.mark.parametrize(
    "usage,limit,expected_color",
    [
        (10, 100, "green"),
        (60, 100, "blue"),
        (80, 100, "yellow"),
        (95, 100, "red"),
    ],
)
def test_format_memory_stats_color_thresholds(usage, limit, expected_color):
    result = format_memory_stats({"usage": usage, "limit": limit})
    assert f"[{expected_color}]" in result


# --- calculate_cpu_percent ---


def test_calculate_cpu_percent_normal():
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 2000},
            "system_cpu_usage": 10000,
            "online_cpus": 2,
        },
        "precpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 5000},
    }
    assert "40.0%" in calculate_cpu_percent(stats)


def test_calculate_cpu_percent_zero_system_delta():
    stats = {
        "cpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 5000},
        "precpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 5000},
    }
    assert "0.0%" in calculate_cpu_percent(stats)


def test_calculate_cpu_percent_missing_online_cpus_falls_back_to_percpu_len():
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 2000, "percpu_usage": [1, 2, 3, 4]},
            "system_cpu_usage": 10000,
        },
        "precpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 5000},
    }
    result = calculate_cpu_percent(stats)
    assert "%" in result


def test_calculate_cpu_percent_missing_fields():
    assert calculate_cpu_percent({}) == "[green]0.0%[/green]"


# --- validate_refresh_rate ---


@pytest.mark.parametrize(
    "rate,expected",
    [
        (0.1, True),
        (1.0, True),
        (60.0, True),
        (0.05, False),
        (60.1, False),
    ],
)
def test_validate_refresh_rate(rate, expected):
    assert validate_refresh_rate(rate) is expected


# --- truncate_string ---


def test_truncate_string_no_truncation_needed():
    assert truncate_string("short", 10) == "short"


def test_truncate_string_truncates_with_suffix():
    assert truncate_string("a very long string", 10) == "a very ..."


def test_truncate_string_max_length_smaller_than_suffix():
    assert truncate_string("hello", 2, suffix="...") == ".."


# --- safe_get_nested ---


def test_safe_get_nested_found():
    data = {"a": {"b": {"c": 42}}}
    assert safe_get_nested(data, ["a", "b", "c"]) == 42


def test_safe_get_nested_missing_key_returns_default():
    data = {"a": {"b": {}}}
    assert safe_get_nested(data, ["a", "b", "c"], default="fallback") == "fallback"


def test_safe_get_nested_wrong_type_returns_default():
    data = {"a": 1}
    assert safe_get_nested(data, ["a", "b"], default=None) is None
