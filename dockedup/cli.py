"""
DockedUp CLI - Interactive Docker Compose stack monitor.
"""

import time
import subprocess
import threading
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
        # Data structures
        self.all_containers: List[Dict] = []
        self.project_names: List[str] = []
        self.project_to_container_indices: Dict[str, List[int]] = {}
        self.container_index_to_project_index: Dict[int, int] = {}

        # UI State
        self.selected_index: int = 0
        self.scroll_offset: int = 0  # Index of the project at the top of the viewport
        self.viewport_height_projects: int = 1  # How many projects fit on screen

        # Filter state
        self.filter_text: str = ""
        self.filter_typing: bool = False
        self.total_container_count: int = 0

        # Project-select mode state
        self.project_mode: bool = False
        self.selected_project_index: int = 0

        # Control
        self.lock = threading.Lock()
        self.ui_updated_event = threading.Event()
        self.debug_mode: bool = False

    def _apply_filter_unsafe(
        self, grouped_containers: Dict[str, List[Dict]]
    ) -> Dict[str, List[Dict]]:
        """Filter projects/containers by filter_text (internal use, lock must be held)."""
        if not self.filter_text:
            return grouped_containers

        needle = self.filter_text.lower()
        filtered: Dict[str, List[Dict]] = {}
        for project_name, containers in grouped_containers.items():
            if needle in project_name.lower():
                filtered[project_name] = containers
                continue
            matched = [c for c in containers if needle in c.get("name", "").lower()]
            if matched:
                filtered[project_name] = matched
        return filtered

    def update_containers(self, grouped_containers: Dict[str, List[Dict]]):
        """Rebuilds all data structures from the latest container data."""
        with self.lock:
            current_id = self._get_selected_container_id_unsafe()
            current_project = self._get_selected_project_name_unsafe()

            self.total_container_count = sum(len(v) for v in grouped_containers.values())
            visible_containers = self._apply_filter_unsafe(grouped_containers)

            # Rebuild all data structures
            self.project_names = sorted(visible_containers.keys())
            self.all_containers = []
            self.project_to_container_indices = {}
            self.container_index_to_project_index = {}

            flat_index = 0
            for proj_index, proj_name in enumerate(self.project_names):
                # Sort containers within each project for consistent order
                containers_in_project = sorted(
                    visible_containers[proj_name], key=lambda c: c.get("name", "")
                )
                self.project_to_container_indices[proj_name] = []
                for container in containers_in_project:
                    self.all_containers.append(container)
                    self.project_to_container_indices[proj_name].append(flat_index)
                    self.container_index_to_project_index[flat_index] = proj_index
                    flat_index += 1

            container_id_to_index = {c.get("id"): i for i, c in enumerate(self.all_containers)}

            # Restore selection if possible, otherwise reset
            if current_id and current_id in container_id_to_index:
                self.selected_index = container_id_to_index[current_id]
            elif self.all_containers:
                self.selected_index = 0
            else:
                self.selected_index = 0

            # Ensure selection and scroll are within new bounds
            self.selected_index = max(0, min(self.selected_index, len(self.all_containers) - 1))
            self.scroll_offset = max(0, min(self.scroll_offset, len(self.project_names) - 1))

            # Restore project selection if possible, otherwise reset
            if current_project and current_project in self.project_names:
                self.selected_project_index = self.project_names.index(current_project)
            else:
                self.selected_project_index = 0
            self.selected_project_index = max(
                0, min(self.selected_project_index, len(self.project_names) - 1)
            )

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

    def _get_selected_project_name_unsafe(self) -> Optional[str]:
        """Get selected project name without acquiring lock (internal use)."""
        if self.project_names and 0 <= self.selected_project_index < len(self.project_names):
            return self.project_names[self.selected_project_index]
        return None

    def get_selected_project_name(self) -> Optional[str]:
        """Get the currently selected project name (project-select mode)."""
        with self.lock:
            return self._get_selected_project_name_unsafe()

    def get_containers_in_project(self, project_name: str) -> List[Dict]:
        """Get all containers belonging to a project."""
        with self.lock:
            indices = self.project_to_container_indices.get(project_name, [])
            return [self.all_containers[i] for i in indices]

    def move_selection(self, delta: int):
        """Move selection up/down, automatically scrolling the viewport if needed."""
        with self.lock:
            if not self.all_containers:
                return

            # calculate and clamp new selection index
            new_index = self.selected_index + delta
            self.selected_index = max(0, min(new_index, len(self.all_containers) - 1))

            # Find the project corresponding to the new selection
            newly_selected_project_index = self.container_index_to_project_index.get(
                self.selected_index
            )
            if newly_selected_project_index is None:
                return  # Should not happen

            # Check if the project is outside the current viewport and adjust scroll
            is_above = newly_selected_project_index < self.scroll_offset
            is_below = newly_selected_project_index >= (
                self.scroll_offset + self.viewport_height_projects
            )

            if is_above:
                # If selection moved above the viewport, scroll up to make it the top project
                self.scroll_offset = newly_selected_project_index
            elif is_below:
                # If selection moved below, scroll down to make it the last visible project
                self.scroll_offset = (
                    newly_selected_project_index - self.viewport_height_projects + 1
                )

            # Ensure scroll offset is always valid
            self.scroll_offset = max(0, min(self.scroll_offset, len(self.project_names) - 1))

        self.ui_updated_event.set()

    def scroll_project_view(self, delta: int):
        """Scroll the project view and select the first container of the new top project."""
        with self.lock:
            if not self.project_names:
                return

            # Calculate and clamp new scroll offset
            new_offset = self.scroll_offset + delta
            self.scroll_offset = max(0, min(new_offset, len(self.project_names) - 1))

            # Update selection to the first container of the new top project
            scrolled_to_project_name = self.project_names[self.scroll_offset]
            container_indices = self.project_to_container_indices.get(scrolled_to_project_name, [])
            if container_indices:
                self.selected_index = container_indices[0]

        self.ui_updated_event.set()

    def toggle_project_mode(self):
        """Toggle project-select mode, syncing the selected project to the current container."""
        with self.lock:
            self.project_mode = not self.project_mode
            if self.project_mode:
                proj_index = self.container_index_to_project_index.get(self.selected_index)
                if proj_index is not None:
                    self.selected_project_index = proj_index
            self.selected_project_index = max(
                0, min(self.selected_project_index, len(self.project_names) - 1)
            )
        self.ui_updated_event.set()

    def move_project_selection(self, delta: int):
        """Move project selection up/down, scrolling the viewport if needed."""
        with self.lock:
            if not self.project_names:
                return

            new_index = self.selected_project_index + delta
            self.selected_project_index = max(0, min(new_index, len(self.project_names) - 1))

            is_above = self.selected_project_index < self.scroll_offset
            is_below = self.selected_project_index >= (
                self.scroll_offset + self.viewport_height_projects
            )

            if is_above:
                self.scroll_offset = self.selected_project_index
            elif is_below:
                self.scroll_offset = self.selected_project_index - self.viewport_height_projects + 1

            self.scroll_offset = max(0, min(self.scroll_offset, len(self.project_names) - 1))

        self.ui_updated_event.set()

    def start_filter_typing(self):
        """Enter filter-typing mode, keeping any existing filter text to refine."""
        with self.lock:
            self.filter_typing = True
        self.ui_updated_event.set()

    def append_filter_char(self, char: str):
        """Append a character to the filter text."""
        with self.lock:
            self.filter_text += char
        self.ui_updated_event.set()

    def backspace_filter(self):
        """Remove the last character of the filter text."""
        with self.lock:
            self.filter_text = self.filter_text[:-1]
        self.ui_updated_event.set()

    def confirm_filter(self):
        """Exit filter-typing mode, keeping the filter applied."""
        with self.lock:
            self.filter_typing = False
        self.ui_updated_event.set()

    def clear_filter(self):
        """Clear the filter text and exit filter-typing mode."""
        with self.lock:
            self.filter_text = ""
            self.filter_typing = False
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
            if command[1] == "logs" and "-f" in command:
                console.print(
                    f"[bold cyan]Showing live logs for '{container_name}'. Press Ctrl+C to return.[/bold cyan]"
                )
            subprocess.run(command, check=False)
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


ACTION_PAST_TENSE = {"restart": "Restarted", "stop": "Stopped"}


def run_bulk_docker_command(
    live_display: Live, action: str, containers: List[Dict], project_name: str
):
    """Pauses the live display to run a Docker command against every container in a project."""
    if not containers:
        return

    live_display.stop()
    console.clear(home=True)
    try:
        console.print(
            f"\n[bold yellow]Are you sure you want to {action} all {len(containers)} "
            f"container(s) in project '{project_name}'? (y/n)[/bold yellow]"
        )
        key = readchar.readkey().lower()
        if key != "y":
            console.print("[green]Aborted.[/green]")
            time.sleep(1)
            return

        container_ids = [c["id"] for c in containers]
        result = subprocess.run(
            ["docker", action, *container_ids], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            console.print(f"[bold red]Command failed (exit code {result.returncode}):[/bold red]")
            output = result.stderr.strip() or result.stdout.strip()
            if output:
                console.print(output)
        else:
            verb = ACTION_PAST_TENSE.get(action, action.capitalize())
            console.print(
                f"[green]✅ {verb} {len(containers)} container(s) in project "
                f"'{project_name}'.[/green]"
            )
        console.input("\n[bold]Press Enter to return...[/bold]")

    except Exception as e:
        logger.error(f"Failed to execute bulk command: {e}")
        console.print(f"[bold red]Failed to execute command:[/bold red]\n{e}")
        console.input("\n[bold]Press Enter to return...[/bold]")
    finally:
        live_display.start(refresh=True)


def show_detail_screen(container: Dict):
    """Display full inspect details for a single container."""
    name = container.get("name", "unknown")
    ports = container.get("ports", "[grey50]—[/grey50]")
    networks = ", ".join(container.get("networks") or []) or "—"
    mounts = container.get("mounts") or []

    lines = [
        f"[bold yellow]Status:[/bold yellow]      {container.get('status', '—')}",
        f"[bold yellow]Health:[/bold yellow]      {container.get('health', '—')}",
        f"[bold yellow]Project:[/bold yellow]     {container.get('project', '—')}",
        f"[bold yellow]Image:[/bold yellow]       {container.get('image') or '—'}",
        f"[bold yellow]Command:[/bold yellow]     {container.get('command') or '—'}",
        f"[bold yellow]Entrypoint:[/bold yellow]  {container.get('entrypoint') or '—'}",
        f"[bold yellow]Restart:[/bold yellow]     {container.get('restart_policy') or '—'}",
        f"[bold yellow]Networks:[/bold yellow]    {networks}",
        "",
        "[bold yellow]Ports:[/bold yellow]",
        f"  {ports}",
        "",
        "[bold yellow]Mounts:[/bold yellow]",
    ]
    if mounts:
        lines.extend(f"  {m}" for m in mounts)
    else:
        lines.append("  —")

    console.print(Panel("\n".join(lines), title=f"Container Details: {name}", border_style="cyan"))
    console.input("\n[bold]Press Enter to return...[/bold]")


def generate_ui(state: AppState) -> Layout:
    """Generate the main UI layout based on the current AppState."""
    layout = Layout(name="root")
    layout.split(
        Layout(name="header", size=3), Layout(ratio=1, name="main"), Layout(size=1, name="footer")
    )

    header_text = Text(
        " DockedUp - Interactive Docker Compose Monitor", justify="center", style="bold magenta"
    )
    if state.debug_mode:
        header_text.append(" [DEBUG MODE]", style="bold red")
    if state.project_mode:
        header_text.append(" [PROJECT MODE]", style="bold yellow")
    layout["header"].update(Align.center(header_text))

    with state.lock:
        if not state.all_containers:
            message = "No containers match filter." if state.filter_text else "No containers found."
            layout["main"].update(Align.center(Text(message, style="yellow"), vertical="middle"))
        else:
            # Viewport Calculation
            chrome_height = 3 + 1 + 2  # header + footer + panel padding
            available_height = max(8, console.height - chrome_height)
            # Estimate height per project (title + header + avg containers)
            avg_project_height = 7
            projects_per_screen = max(1, available_height // avg_project_height)
            state.viewport_height_projects = projects_per_screen

            # Determine which projects are visible based on scroll offset
            start_idx = state.scroll_offset
            end_idx = min(start_idx + projects_per_screen, len(state.project_names))
            visible_project_names = state.project_names[start_idx:end_idx]

            # Render Visible Projects
            visible_renderables = []
            for offset, proj_name in enumerate(visible_project_names):
                global_proj_index = start_idx + offset
                is_selected_project = (
                    state.project_mode and global_proj_index == state.selected_project_index
                )

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

                container_indices = state.project_to_container_indices[proj_name]
                for container_index in container_indices:
                    container = state.all_containers[container_index]
                    style = (
                        "on blue"
                        if (not state.project_mode and container_index == state.selected_index)
                        else ""
                    )
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

                panel_border_style = "bold yellow" if is_selected_project else "dim blue"
                visible_renderables.append(Panel(table, border_style=panel_border_style))

            # Scroll Indicator
            scroll_info = ""
            if len(state.project_names) > projects_per_screen:
                scroll_info = (
                    f"Showing projects {start_idx + 1}-{end_idx} of {len(state.project_names)}"
                )

            if state.filter_text:
                shown = len(state.all_containers)
                filter_info = (
                    f"{shown}/{state.total_container_count} containers match "
                    f"'{state.filter_text}'"
                )
                scroll_info = f"{scroll_info} | {filter_info}" if scroll_info else filter_info

            if state.debug_mode:
                debug_info = f" | Selected Index: {state.selected_index} | Scroll Offset: {state.scroll_offset}"
                scroll_info += debug_info

            layout["main"].update(
                Panel(Group(*visible_renderables), title=scroll_info, border_style="dim blue")
            )

    # Footer
    if state.filter_typing:
        footer_text = f"[b]/[/b] {state.filter_text}█  Enter=apply  Esc=clear"
    else:
        parts = ["[b]Q[/b]uit", "[b]↑/↓[/b] Navigate", "[b]PgUp/PgDn[/b] Scroll Projects"]
        if state.project_mode:
            parts += [
                "[b]R[/b]estart project",
                "[b]X[/b] Stop project",
                "[b]P[/b] Exit project mode",
            ]
        else:
            parts.append("[b]/[/b] Filter")
            parts.append("[b]P[/b] Project mode")
            if state.get_selected_container():
                parts += [
                    "[b]L[/b]ogs",
                    "[b]R[/b]estart",
                    "[b]S[/b]hell",
                    "[b]X[/b] Stop",
                    "[b]I[/b]nfo",
                ]
        parts.append("[b]?[/b] Help")
        footer_text = " | ".join(parts)
    layout["footer"].update(Align.center(footer_text))

    return layout


def show_help_screen():
    """Display help screen with all available commands."""
    help_content = """
[bold cyan]DockedUp - Interactive Docker Monitor[/bold cyan]

[bold yellow]Navigation:[/bold yellow]
  ↑/↓ or k/j    Navigate up/down through containers.
  PgUp/PgDn     Scroll through projects one-by-one.
  q or Ctrl+C   Quit DockedUp

[bold yellow]Container Actions:[/bold yellow]
  l             View logs (live for running, static for stopped)
  r             Restart container (with confirmation)
  s             Open shell session (in running containers)
  x             Stop container (with confirmation)
  i             Show full container details (image, mounts, networks...)

[bold yellow]Filter:[/bold yellow]
  /             Start typing a filter (matches container or project name)
  Enter         Apply filter and keep browsing
  Esc           Clear filter

[bold yellow]Project Mode:[/bold yellow]
  p             Toggle project mode
  ↑/↓ or k/j    Select a project (while in project mode)
  r             Restart every container in the selected project
  x             Stop every container in the selected project

[bold yellow]Other:[/bold yellow]
  ?             Show this help screen
"""
    console.print(Panel(help_content, title="Help", border_style="cyan"))
    console.input("\n[bold]Press Enter to return to DockedUp...[/bold]")


@app.command()
def main(
    refresh_rate: Annotated[
        float, typer.Option("--refresh", "-r", help="UI refresh rate in seconds", min=0.1)
    ] = 1.0,
    debug: Annotated[bool, typer.Option("--debug", "-d", help="Enable debug mode")] = False,
    no_stats: Annotated[
        bool,
        typer.Option(
            "--no-stats", help="Disable real-time stats collection (useful for remote connections)"
        ),
    ] = False,
    version: Annotated[
        Optional[bool], typer.Option("--version", "-v", callback=version_callback, is_eager=True)
    ] = None,
):
    """🐳 Interactive Docker Compose stack monitor."""
    setup_logging(debug=debug)

    try:
        client = docker.from_env(timeout=10)
        client.ping()
    except DockerException as e:
        console.print(f"[bold red]Error: Failed to connect to Docker.[/bold red]\nDetails: {e}")
        raise typer.Exit(code=1)

    # Auto-detect remote connection and warn user
    is_remote = False
    try:
        base_url = client.api.base_url
        is_remote = base_url.startswith(("ssh://", "tcp://", "http://")) if base_url else False
        if is_remote and debug:
            console.print(f"[yellow]Detected remote Docker connection: {base_url}[/yellow]")
            console.print("[yellow]Using optimized polling mode for stats collection...[/yellow]")
    except Exception:
        pass

    monitor = ContainerMonitor(client, enable_stats=not no_stats)
    app_state = AppState()
    app_state.debug_mode = debug
    should_quit = threading.Event()

    def input_worker(live: Live):
        """Handle keyboard input in a separate thread."""
        while not should_quit.is_set():
            try:
                key = readchar.readkey()

                if key == readchar.key.CTRL_C:
                    should_quit.set()
                    continue

                if app_state.filter_typing:
                    if key == readchar.key.ENTER:
                        app_state.confirm_filter()
                    elif key == readchar.key.ESC:
                        app_state.clear_filter()
                    elif key == readchar.key.BACKSPACE:
                        app_state.backspace_filter()
                    elif len(key) == 1 and key.isprintable():
                        app_state.append_filter_char(key)
                    continue

                if key.lower() == "q":
                    should_quit.set()
                elif key in (readchar.key.UP, "k"):
                    if app_state.project_mode:
                        app_state.move_project_selection(-1)
                    else:
                        app_state.move_selection(-1)
                elif key in (readchar.key.DOWN, "j"):
                    if app_state.project_mode:
                        app_state.move_project_selection(1)
                    else:
                        app_state.move_selection(1)
                elif key == readchar.key.PAGE_UP:
                    app_state.scroll_project_view(-1)
                elif key == readchar.key.PAGE_DOWN:
                    app_state.scroll_project_view(1)
                elif key == "/":
                    app_state.start_filter_typing()
                elif key.lower() == "p":
                    app_state.toggle_project_mode()
                elif key == "?":
                    live.stop()
                    console.clear(home=True)
                    show_help_screen()
                    live.start(refresh=True)
                elif app_state.project_mode:
                    project_name = app_state.get_selected_project_name()
                    if project_name:
                        containers = app_state.get_containers_in_project(project_name)
                        if key.lower() == "r":
                            run_bulk_docker_command(live, "restart", containers, project_name)
                        elif key.lower() == "x":
                            run_bulk_docker_command(live, "stop", containers, project_name)
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
                        elif key.lower() == "i":
                            live.stop()
                            console.clear(home=True)
                            show_detail_screen(container)
                            live.start(refresh=True)
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

            # Main render loop
            while not should_quit.is_set():
                grouped_data = monitor.get_grouped_containers()
                app_state.update_containers(grouped_data)
                ui_layout = generate_ui(app_state)
                live.update(ui_layout, refresh=True)
                app_state.ui_updated_event.wait(timeout=refresh_rate)
                app_state.ui_updated_event.clear()
    finally:
        should_quit.set()
        monitor.stop()
        console.print("\n[bold yellow]👋 See you soon![/bold yellow]")


if __name__ == "__main__":
    app()
