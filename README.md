# DockedUp

**htop for your Docker Compose stack.**

<div align="center">
  <img src="https://github.com/user-attachments/assets/e0abd228-2a89-4f17-8530-1483d1aa97f3" alt="DockedUp Demo">
</div>

---
[![PyPI version](https://img.shields.io/pypi/v/dockedup.svg)](https://pypi.org/project/dockedup/)
[![Python versions](https://img.shields.io/pypi/pyversions/dockedup.svg)](https://pypi.org/project/dockedup/)
[![License](https://img.shields.io/pypi/l/dockedup.svg)](https://github.com/anilrajrimal1/dockedup/blob/master/LICENSE)

**DockedUp** is an interactive command-line tool that provides a live, beautiful, and human-friendly monitor for your Docker containers. It's designed for developers and DevOps engineers who want a quick, real-time overview of their containerized environments without the noise of `docker ps` and the hassle of switching terminals.

### Problem It Solves

`docker stats` and `docker ps` are functional, but fall short when you need to:
- **Monitor** container status, health, and resource usage in one unified view.
- **Act** on a container (view logs, restart, shell in) without breaking your workflow.
- **Understand** a complex `docker-compose` stack at a glance.

DockedUp solves these problems by presenting your container information in a continuously updating, color-coded, and interactive dashboard right in your terminal.

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

### Installation

DockedUp is available on PyPI. It is highly recommended to install CLI tools in an isolated environment using `pipx`.

```bash
pipx install dockedup
```

Alternatively, you can use `pip`:
```bash
pip install dockedup
```

###  usage

Simply run the command to start the interactive monitor:
```bash
dockedup
```
Once running, use the following keys:
-  **↑/↓**: Navigate between containers.
-  **l**: Show live logs for the selected container.
-  **r**: Restart the selected container.
-  **x**: Stop the selected container.
-  **s**: Open a shell in the selected container.
-  **q**: Quit the application.

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

### Contributing

Contributions are welcome! Whether it's a bug report, a feature request, or a pull request, we'd love to hear from you.

Please read our [**Contributing Guide**](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

### License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.