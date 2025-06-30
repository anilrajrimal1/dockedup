# DockedUp 🐳

**htop for your Docker Compose stack.**

[![PyPI version](https://badge.fury.io/py/dockedup.svg)](https://badge.fury.io/py/dockedup)
[![Python Support](https://img.shields.io/pypi/pyversions/dockedup.svg)](https://pypi.org/project/dockedup/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/anilrajrimal1/dockedup/blob/master/LICENSE)

**DockedUp** is an interactive command-line tool that provides a live, beautiful, and human-friendly monitor for your Docker containers. It's designed for developers and DevOps engineers who want a quick, real-time overview of their containerized environments without the noise of `docker ps` and the hassle of switching terminals.

<div align="center">
  <img src="https://github.com/user-attachments/assets/e0abd228-2a89-4f17-8530-1483d1aa97f3" alt="DockedUp Demo">
</div>

### Key Features

- **Real-Time Monitoring**: Live-updating data for status, uptime, CPU, and Memory.
- **Compose Project Grouping**: Automatically groups containers by their `docker-compose` project.
- **Emoji + Colors**: Clearly shows container status (`Up`, `Down`, `Restarting`) and health (`Healthy`, `Unhealthy`) with visual cues.
- **Interactive Controls**: Select containers with arrow keys and use hotkeys to:
    -  `l` → View live logs (`docker logs -f`).
    -  `r` → Restart a container (with confirmation).
    -  `x` → Stop a container (with confirmation).
    -  `s` → Open a shell (`/bin/sh`) inside a container.
- **PyPI Package**: Simple one-liner installation.

### Problem It Solves

`docker stats` and `docker ps` are functional, but fall short when you need to:
- **Monitor** container status, health, and resource usage in one unified view.
- **Act** on a container (view logs, restart, shell in) without breaking your workflow.
- **Understand** a complex `docker-compose` stack at a glance.

DockedUp solves these problems by presenting your container information in a continuously updating, color-coded, and interactive dashboard right in your terminal.

### Installation

DockedUp is available on PyPI. It is highly recommended to install CLI tools in an isolated environment using `pipx`.

```bash
pipx install dockedup
```

Alternatively, you can use `pip`:
```bash
pip install dockedup
```

### From Source

```bash
git clone https://github.com/anilrajrimal1/dockedup.git
cd dockedup
pip install -e .
```

## 📋 Requirements

- Python 3.10+
- Docker Engine (local or remote)
- Terminal with color support

## Usage

### Basic Usage

```bash
# Start DockedUp with default settings
dockedup

# Custom refresh rate (0.5 seconds)
dockedup --refresh 0.5

# Enable debug mode
dockedup --debug
```

### Command Line Options

```bash
dockedup [OPTIONS]

Options:
  -r, --refresh FLOAT    UI refresh rate in seconds (0.1-60.0) [default: 1.0]
  -d, --debug           Enable debug mode with verbose logging
  -v, --version         Show version and exit
  -h, --help            Show help message and exit
```

### Interactive Controls

Once DockedUp is running, use these keyboard shortcuts:

| Key | Action |
|-----|--------|
| `↑/↓` or `k/j` | Navigate up/down |
| `l` | View live logs |
| `r` | Restart container (with confirmation) |
| `s` | Open shell session |
| `x` | Stop container (with confirmation) |
| `?` | Show help screen |
| `q` or `Ctrl+C` | Quit DockedUp |

## 🖥️ Interface

DockedUp displays containers grouped by Docker Compose project:

```
┌─────────────────────────────────────────────────────────────────────┐
│                DockedUp - Interactive Docker Compose Monitor         │
└─────────────────────────────────────────────────────────────────────┘

┌─ Project: anil-demo ──────────────────────────────────────────────────┐
│ Container    │ Status      │ Uptime │ Health    │ CPU %  │ Memory   │
│ anil-demo-web   │ ✅ Up       │ 2h 15m │ 🟢 Healthy│ 15.2%  │ 245M/1G  │
│ anil-demo-db    │ ✅ Up       │ 2h 15m │ —         │ 5.1%   │ 180M/2G  │
│ anil-demo-redis │ ❌ Down     │ —      │ —         │ —      │ —        │
└────────────────────────────────────────────────────────────────────┘

Q)uit | ↑/↓ Navigate | L)ogs | R)estart | S)hell | X) Stop | ?) Help
```

### Status Icons

- ✅ **Up** - Container is running
- ❌ **Down** - Container is stopped/exited
- 🔁 **Restarting** - Container is restarting
- ⏸️ **Paused** - Container is paused
- 💀 **Dead** - Container is dead
- 📦 **Created** - Container created but not started

### Health Icons

- 🟢 **Healthy** - Health check passing
- 🔴 **Unhealthy** - Health check failing  
- 🟡 **Starting** - Health check starting
- — **No health check** defined

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DOCKER_HOST` | Docker daemon socket | `unix:///var/run/docker.sock` |
| `DOCKER_CERT_PATH` | Path to Docker certificates | — |
| `DOCKER_TLS_VERIFY` | Enable TLS verification | `0` |

### Docker Context

DockedUp respects your Docker context configuration:

```bash
# Use a specific Docker context
docker context use myremote
dockedup

# Or temporarily override
DOCKER_HOST=tcp://remote-docker:2376 dockedup
```

## Troubleshooting

### Docker Connection Issues

**Error: Failed to connect to Docker**

1. **Docker Desktop not running** (macOS/Windows):
   ```bash
   # Start Docker Desktop, then test:
   docker ps
   ```

2. **Permission denied** (Linux):
   ```bash
   # Add user to docker group:
   sudo usermod -aG docker $USER
   # Then logout and login again
   ```

3. **Docker daemon not running** (Linux):
   ```bash
   # Check status:
   sudo systemctl status docker
   
   # Start if needed:
   sudo systemctl start docker
   ```

### Performance Issues

If DockedUp feels slow:

```bash
# Reduce refresh rate
dockedup --refresh 2.0

# Check Docker daemon performance
docker system df
docker system prune  # Clean up unused resources
```

### Debug Mode

Enable debug logging to troubleshoot issues:

```bash
dockedup --debug
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Developer's Guide

Interested in contributing or running the project locally?

**Prerequisites:**
-  Git
-  Python 3.10+
-  [Poetry](https://python-poetry.org/)

**Setup:**
1.  Clone the repository:
    ```bash
    git clone https://github.com/anilrajrimal1/dockedup.git
    cd dockedup
    ```
2.  Install dependencies:
    ```bash
    poetry install
    ```
3.  Run the application locally:
    ```bash
    poetry run dockedup
    ```
4.  Run the tests:
    ```bash
    poetry run pytest
    ```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Inspired by [htop](https://htop.dev/) and [lazydocker](https://github.com/jesseduffield/lazydocker)
- Built with [Rich](https://github.com/Textualize/rich) and [Typer](https://github.com/tiangolo/typer)
---

**Made with ❤️ by [Anil](https://anilrajrimal.com.np) for the Docker community**
