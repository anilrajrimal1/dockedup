"""
DockedUp CLI - Interactive Docker Compose stack monitor.
"""

import time
import subprocess
import threading
import os
import logging
from typing import Dict, List, Optional
from typing_extensions import Annotated
import typer
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.align import Align
from rich.text import Text
from rich.logging import RichHandler
import docker
from docker.errors import DockerException
import readchar

from .docker_monitor import ContainerMonitor
from .utils import format_uptime
from . import __version__, __description__

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("dockedup")

# Create main Typer app
app = typer.Typer(
    name="dockedup",
    help=f"{__description__}\n\nDockedUp provides an interactive, real-time view of your Docker containers with htop-like navigation and controls.",
    epilog="For more information and examples, visit: https://github.com/anilrajrimal1/dockedup",
    add_completion=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=False,
)

console = Console()


class AppState:
    """Manages the application's shared interactive state with thread-safety."""

    def __init__(self):
        self.all_containers: List[Dict] = []
        self.selected_index: int = 0
        self.container_id_to_index: Dict[str, int] = {}
        self.lock = threading.Lock()
        self.ui_updated_event = threading.Event()
        self.debug_mode: bool = False
        self.current_page: int = 0
        self.total_pages: int = 1
        self.page_change_requested: bool = False

    def update_containers(self, containers: List[Dict]):
        """Update the containers list while preserving selection."""
        with self.lock:
            current_id = self._get_selected_container_id_unsafe()
            self.all_containers = containers
            self.container_id_to_index = {c.get("id"): i for i, c in enumerate(self.all_containers)}

            if current_id and current_id in self.container_id_to_index:
                self.selected_index = self.container_id_to_index[current_id]
            elif self.all_containers:
                self.selected_index = 0
            else:
                self.selected_index = 0

    def get_selected_container(self) -> Optional[Dict]:
        """Get the currently selected container."""
        with self.lock:
            if self.all_containers and 0 <= self.selected_index < len(self.all_containers):
                return self.all_containers[self.selected_index]
        return None

    def _get_selected_container_id_unsafe(self) -> Optional[str]:
        """Get selected container ID without acquiring lock (internal use)."""
        if self.all_containers and 0 <= self.selected_index < len(self.all_containers):
            return self.all_containers[self.selected_index].get("id")
        return None

    def move_selection(self, delta: int):
        """Move selection up/down by delta, clamping at the ends."""
        with self.lock:
            if not self.all_containers:
                return
            new_index = self.selected_index + delta
            self.selected_index = max(0, min(new_index, len(self.all_containers) - 1))
            self.page_change_requested = False
        self.ui_updated_event.set()

    def change_page(self, delta: int):
        """Request a page change by delta, cycling through available pages."""
        with self.lock:
            if self.total_pages <= 1:
                return
            self.current_page = (self.current_page + delta + self.total_pages) % self.total_pages
            self.page_change_requested = True
        self.ui_updated_event.set()


def setup_logging(debug: bool = False):
    """Configure logging based on user preferences."""
    if debug:
        logging.getLogger("dockedup").setLevel(logging.DEBUG)
        logger.debug("Debug mode enabled")
    else:
        logging.getLogger("dockedup").setLevel(logging.WARNING)


def version_callback(value: bool):
    """Handle version flag callback."""
    if value:
        console.print(f"DockedUp v{__version__}")
        raise typer.Exit()


def run_docker_command(
    live_display: Live, command: List[str], container_name: str, confirm: bool = False
):
    """Pauses the live display to run a Docker command."""
    live_display.stop()
    console.clear(home=True)
    try:  # stopped container ko logs
        is_streaming_interactive = (command[1] == "exec" and "-it" in command) or (
            command[1] == "logs" and "-f" in command
        )

        if confirm:
            action = command[1].capitalize()
            console.print(
                f"\n[bold yellow]Are you sure you want to {action} container '{container_name}'? (y/n)[/bold yellow]"
            )
            key = readchar.readkey().lower()
            if key != "y":
                console.print("[green]Aborted.[/green]")
                time.sleep(1)
                return

        if is_streaming_interactive:
            command_str = " ".join(command)
            if "logs -f" in command_str:
                console.print(
                    f"[bold cyan]Showing live logs for '{container_name}'. Press Ctrl+C to return.[/bold cyan]"
                )
            os.system(command_str)
        else:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                console.print(
                    f"[bold red]Command failed (exit code {result.returncode}):[/bold red]"
                )
                output = result.stderr.strip() or result.stdout.strip()
                if output:
                    console.print(output)
            else:
                output = result.stdout.strip()
                if output:
                    console.print(output)
                else:
                    console.print(
                        f"[green]✅ Command '{' '.join(command[1:3])}...' executed successfully on '{container_name}'.[/green]"
                    )
            console.input("\n[bold]Press Enter to return...[/bold]")

    except Exception as e:
        logger.error(f"Failed to execute command: {e}")
        console.print(f"[bold red]Failed to execute command:[/bold red]\n{e}")
        console.input("\n[bold]Press Enter to return...[/bold]")
    finally:
        live_display.start(refresh=True)


def generate_ui(groups: Dict[str, List[Dict]], state: AppState) -> Layout:
    """Generate the main UI layout with dynamically paginated project tables."""
    layout = Layout(name="root")
    layout.split(
        Layout(name="header", size=3), Layout(ratio=1, name="main"), Layout(size=1, name="footer")
    )

    header_text = Text(
        " DockedUp - Interactive Docker Compose Monitor", justify="center", style="bold magenta"
    )
    if state.debug_mode:
        header_text.append(" [DEBUG MODE]", style="bold red")
    layout["header"].update(Align.center(header_text))

    all_project_names = sorted(groups.keys())
    flat_list = [
        c
        for name in all_project_names
        for c in sorted(groups[name], key=lambda x: x.get("name", ""))
    ]
    state.update_containers(flat_list)

    if not state.all_containers:
        layout["main"].update(
            Align.center(Text("No containers found.", style="yellow"), vertical="middle")
        )
        state.total_pages = 1
        state.current_page = 0
    else:
        with state.lock:
            # Calculate available space for content
            chrome_height = 3 + 1 + 4
            available_height = max(10, console.height - chrome_height)

            # Build pages ensuring compose (project)
            pages: List[List[str]] = []
            current_page_projects: List[str] = []
            current_page_height = 0

            for proj_name in all_project_names:
                containers_in_project = groups[proj_name]

                # Calculate exact height
                # Every Project ko lagi: title(1) + header_row(1) + container_rows + panel_borders(2) + spacing(1)
                project_height = len(containers_in_project) + 5

                # If adding this project would exceed available height AND current page is not empty
                if current_page_projects and (
                    current_page_height + project_height > available_height
                ):
                    # Finalize current page and start new one
                    pages.append(current_page_projects[:])  # Copy the list
                    current_page_projects = [proj_name]
                    current_page_height = project_height
                else:
                    # Add project to current page
                    current_page_projects.append(proj_name)
                    current_page_height += project_height

            # last page (include)
            if current_page_projects:
                pages.append(current_page_projects)

            # euta page (compulsory)
            if not pages:
                pages = [[]]
            state.total_pages = len(pages)

            # Handle selection and page management
            if state.all_containers:
                selected_container = state.all_containers[state.selected_index]
                selected_project = selected_container["project"]

                # Find which page contains the selected container's project
                page_with_selection = 0
                for i, page_projects in enumerate(pages):
                    if selected_project in page_projects:
                        page_with_selection = i
                        break

                if state.page_change_requested:
                    # if explicitly changed page - valid range mai basam
                    state.current_page = max(0, min(state.current_page, state.total_pages - 1))

                    # select every page ko first container
                    if pages[state.current_page]:
                        target_project = pages[state.current_page][0]
                        for i, container in enumerate(state.all_containers):
                            if container["project"] == target_project:
                                state.selected_index = i
                                break

                    state.page_change_requested = False
                else:
                    state.current_page = page_with_selection
            else:
                state.current_page = 0

            renderables_on_page = []
            if state.current_page < len(pages):
                displayed_projects = pages[state.current_page]

                for proj_name in displayed_projects:
                    # Create table
                    table = Table(
                        title=f"Project: [bold cyan]{proj_name}[/bold cyan]",
                        border_style="blue",
                        expand=True,
                        show_lines=False,
                    )
                    table.add_column("Container", style="cyan", no_wrap=True)
                    table.add_column("Status", justify="left")
                    table.add_column("Uptime", justify="right")
                    table.add_column("Health", justify="left")
                    table.add_column("CPU %", justify="right")
                    table.add_column("MEM USAGE / LIMIT", justify="right")

                    # Add containers
                    project_containers = sorted(groups[proj_name], key=lambda c: c.get("name", ""))
                    for container in project_containers:
                        idx = state.container_id_to_index.get(container["id"])
                        style = "on blue" if idx == state.selected_index else ""

                        uptime = (
                            format_uptime(container.get("started_at"))
                            if "Up" in container["status"]
                            else "[grey50]—[/grey50]"
                        )

                        table.add_row(
                            container["name"],
                            container["status"],
                            uptime,
                            container["health"],
                            container["cpu"],
                            container["memory"],
                            style=style,
                        )

                    renderables_on_page.append(Panel(table, border_style="dim blue"))

            page_info = f"Page {state.current_page + 1} of {state.total_pages}"
            if state.debug_mode:
                page_info += f" | Available Height: {available_height}"

            if renderables_on_page:
                layout["main"].update(
                    Panel(Group(*renderables_on_page), title=page_info, border_style="dim blue")
                )
            else:
                layout["main"].update(
                    Panel(
                        Text("No projects on this page", justify="center"),
                        title=page_info,
                        border_style="dim blue",
                    )
                )

    # Footer
    footer_text = "[b]Q[/b]uit | [b]↑/↓[/b] Navigate | [b]PgUp/PgDn[/b] Change Page"
    if state.get_selected_container():
        footer_text += " | [b]L[/b]ogs | [b]R[/b]estart | [b]S[/b]hell | [b]X[/b] Stop"
    footer_text += " | [b]?[/b] Help"
    layout["footer"].update(Align.center(footer_text))

    return layout


def show_help_screen():
    """Display help screen with all available commands."""
    help_content = """
[bold cyan]DockedUp - Interactive Docker Monitor[/bold cyan]

[bold yellow]Navigation:[/bold yellow]
  ↑/↓ or k/j    Navigate up/down (auto-scrolls pages)
  PgUp/PgDn     Change page
  q or Ctrl+C   Quit DockedUp

[bold yellow]Container Actions:[/bold yellow]
  l             View logs (live for running, static for stopped)
  r             Restart container (with confirmation)
  s             Open shell session (in running containers)
  x             Stop container (with confirmation)

[bold yellow]Other:[/bold yellow]
  ?             Show this help screen

[bold green]Tip:[/bold green] UI is responsive! Resize your terminal and see the pages adjust.
"""
    console.print(Panel(help_content, title="Help", border_style="cyan"))
    console.input("\n[bold]Press Enter to return to DockedUp...[/bold]")


@app.command()
def main(
    refresh_rate: Annotated[
        float, typer.Option("--refresh", "-r", help="UI refresh rate in seconds", min=0.1)
    ] = 1.0,
    debug: Annotated[bool, typer.Option("--debug", "-d", help="Enable debug mode")] = False,
    version: Annotated[
        Optional[bool], typer.Option("--version", "-v", callback=version_callback, is_eager=True)
    ] = None,
):
    """🐳 Interactive Docker Compose stack monitor."""
    setup_logging(debug=debug)

    try:
        client = docker.from_env(timeout=5)
        client.ping()
    except DockerException as e:
        console.print(f"[bold red]Error: Failed to connect to Docker.[/bold red]\nDetails: {e}")
        raise typer.Exit(code=1)

    monitor = ContainerMonitor(client)
    app_state = AppState()
    app_state.debug_mode = debug
    should_quit = threading.Event()

    def input_worker(live: Live):
        """Handle keyboard input in a separate thread."""
        while not should_quit.is_set():
            try:
                key = readchar.readkey()
                if key == readchar.key.CTRL_C or key.lower() == "q":
                    should_quit.set()
                elif key in (readchar.key.UP, "k"):
                    app_state.move_selection(-1)
                elif key in (readchar.key.DOWN, "j"):
                    app_state.move_selection(1)
                elif key == readchar.key.PAGE_UP:
                    app_state.change_page(-1)
                elif key == readchar.key.PAGE_DOWN:
                    app_state.change_page(1)
                elif key == "?":
                    live.stop()
                    console.clear(home=True)
                    show_help_screen()
                    live.start(refresh=True)
                else:
                    container = app_state.get_selected_container()
                    if container:
                        if key.lower() == "l":
                            cmd = ["docker", "logs", "--tail", "100"]
                            if "Up" in container["status"]:
                                cmd.insert(2, "-f")
                            cmd.append(container["id"])
                            run_docker_command(live, cmd, container["name"])
                        elif key.lower() == "r":
                            run_docker_command(
                                live,
                                ["docker", "restart", container["id"]],
                                container["name"],
                                confirm=True,
                            )
                        elif key.lower() == "x":
                            run_docker_command(
                                live,
                                ["docker", "stop", container["id"]],
                                container["name"],
                                confirm=True,
                            )
                        elif key.lower() == "s":
                            run_docker_command(
                                live,
                                ["docker", "exec", "-it", container["id"], "/bin/sh"],
                                container["name"],
                            )
            except KeyboardInterrupt:
                should_quit.set()
            except Exception as e:
                logger.error(f"Input handler error: {e}")
                should_quit.set()
        app_state.ui_updated_event.set()

    try:
        with Live(
            console=console, screen=True, transient=True, redirect_stderr=False, auto_refresh=False
        ) as live:
            monitor.run()
            input_thread = threading.Thread(target=input_worker, args=(live,), daemon=True)
            input_thread.start()
            while not should_quit.is_set():
                grouped_data = monitor.get_grouped_containers()
                ui_layout = generate_ui(grouped_data, app_state)
                live.update(ui_layout, refresh=True)
                app_state.ui_updated_event.wait(timeout=refresh_rate)
                app_state.ui_updated_event.clear()
    finally:
        should_quit.set()
        monitor.stop()
        console.print("\n[bold yellow]👋 See you soon![/bold yellow]")


if __name__ == "__main__":
    app()
