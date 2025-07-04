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
        self.scroll_offset: int = 0  # NEW: tracks which project/container to start displaying from

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
        self.ui_updated_event.set()

    def scroll_view(self, delta: int):
        """Scroll the view up/down by delta positions."""
        with self.lock:
            if not self.all_containers:
                return

            # Calculate max scroll position
            max_scroll = max(0, len(self.all_containers) - 1)

            # Update scroll offset
            new_offset = self.scroll_offset + delta
            self.scroll_offset = max(0, min(new_offset, max_scroll))

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
    try:
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
    """Generate the main UI layout with scrollable project tables (KEEPING YOUR ORIGINAL STRUCTURE)."""
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
    else:
        with state.lock:
            # Calculate available space for content
            chrome_height = 3 + 1 + 2  # header + footer + some padding
            available_height = max(8, console.height - chrome_height)

            # Create a list of all renderable items (projects + containers)
            all_renderables = []
            container_index = 0

            for proj_name in all_project_names:
                containers_in_project = sorted(groups[proj_name], key=lambda c: c.get("name", ""))

                # Create table for this project
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

                # Add containers to this project's table
                for container in containers_in_project:
                    style = "on blue" if container_index == state.selected_index else ""

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
                    container_index += 1

                all_renderables.append(Panel(table, border_style="dim blue"))

            # Apply scrolling - show only the renderables that fit in available space
            if len(all_renderables) > 0:
                # Calculate how many projects we can show
                projects_per_screen = max(1, available_height // 8)  # Rough estimate

                # Apply scroll offset
                start_idx = min(state.scroll_offset, max(0, len(all_renderables) - 1))
                end_idx = min(start_idx + projects_per_screen, len(all_renderables))

                visible_renderables = all_renderables[start_idx:end_idx]

                # Create scroll indicator
                if len(all_renderables) > projects_per_screen:
                    scroll_info = f"Showing projects {start_idx + 1}-{end_idx} of {len(all_renderables)} | Scroll: {state.scroll_offset}"
                else:
                    scroll_info = f"Showing all {len(all_renderables)} projects"

                if state.debug_mode:
                    scroll_info += f" | Selected: {state.selected_index} | Available Height: {available_height}"

                layout["main"].update(
                    Panel(Group(*visible_renderables), title=scroll_info, border_style="dim blue")
                )
            else:
                layout["main"].update(
                    Panel(
                        Text("No projects to display", justify="center"),
                        title="No Data",
                        border_style="dim blue",
                    )
                )

    # Footer
    footer_text = "[b]Q[/b]uit | [b]↑/↓[/b] Navigate | [b]PgUp/PgDn[/b] Scroll View"
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
  ↑/↓ or k/j    Navigate up/down through containers
  PgUp/PgDn     Scroll view up/down
  q or Ctrl+C   Quit DockedUp

[bold yellow]Container Actions:[/bold yellow]
  l             View logs (live for running, static for stopped)
  r             Restart container (with confirmation)
  s             Open shell session (in running containers)
  x             Stop container (with confirmation)

[bold yellow]Other:[/bold yellow]
  ?             Show this help screen

[bold green]Tip:[/bold green] Use PgUp/PgDn to scroll through projects when you have many containers!
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
                    app_state.scroll_view(-1)
                elif key == readchar.key.PAGE_DOWN:
                    app_state.scroll_view(1)
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
