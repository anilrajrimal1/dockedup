# 🚀 DockedUp

**htop for your Docker Compose stack.**

DockedUp is a command-line tool that provides a live, beautiful, and human-friendly monitor for your Docker and Docker Compose containers. It's designed for developers and DevOps engineers who want a quick, real-time overview of their containerized environments without the noise of `docker ps`.

  <!-- Replace with a real GIF! -->

### Problem It Solves

`docker ps` is functional, but it falls short when you need to:
- Monitor container status and health in **real-time**.
- Quickly detect if a service is **restarting** or **unhealthy**.
- Understand **port mappings** in a clean, readable way.
- Group containers logically by their **Compose project**.

DockedUp solves these problems by presenting your container information in a continuously updating, color-coded, and organized table right in your terminal.

### Core Features

-   **Live Monitoring**: Auto-refreshing container table every few seconds.
-   **Emoji + Colors**: Clearly shows container status (`Up`, `Down`, `Restarting`) and health checks (`Healthy`, `Unhealthy`) with visual cues.
-   **Readable Port Mapping**: Lists exposed and mapped ports in a simple `host->container` format.
-   **Compose Project Grouping**: Automatically groups containers by their `com.docker.compose.project` label.
-    graceful **Graceful Exit**: `Ctrl+C` to cleanly stop the monitor.
-   **One Command**: `dockedup monitor` to start instantly.
-   **PyPI Package**: Simple one-liner installation.

### Installation

DockedUp is available on PyPI and can be installed with `pip`.

```bash
pip install dockedup
```
It is highly recommended to install CLI tools in an isolated environment using `pipx`:
```bash
pipx install dockedup
```

### usage

Simply run the `monitor` command:
```bash
dockedup monitor
```

You can customize the refresh rate (default is 2 seconds):
```bash
dockedup monitor --refresh 5  # Refresh every 5 seconds
```

### Tech Stack

-   **Python 3.10+**
-   **Typer** for the CLI interface.
-   **Docker SDK** for interfacing with the Docker daemon.
-   **Rich** for beautiful terminal rendering, tables, and colors.
-   **Poetry** for packaging and dependency management.
-   **pytest** for unit testing.

### License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.