"""
DockedUp CLI - Interactive Docker Compose stack monitor.
"""

import time
import subprocess
import threading
import sys
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
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("dockedup")

# Create main Typer app with comprehensive configuration
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
        self.projects_per_page: int = 5

    def update_containers(self, containers: List[Dict]):
        """Update the containers list while preserving selection and using an ID map for efficiency."""
        with self.lock:
            current_id = self._get_selected_container_id_unsafe()
            self.all_containers = containers
            self.container_id_to_index = {c.get('id'): i for i, c in enumerate(self.all_containers)}
            
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
            return self.all_containers[self.selected_index].get('id')
        return None

    def move_selection(self, delta: int):
        """Move selection up/down, clamping at ends, and auto-scrolling pages."""
        with self.lock:
            if not self.all_containers:
                self.selected_index = 0
                return
            
            # Calculate new index and clamp it between 0 and the last index
            new_index = self.selected_index + delta
            new_index = max(0, min(new_index, len(self.all_containers) - 1))

            if new_index == self.selected_index:
                return # No change, do nothing

            self.selected_index = new_index

            # Adjust page to ensure selected container is visible
            selected_project = self.all_containers[self.selected_index]['project']
            projects = sorted(set(c['project'] for c in self.all_containers))
            try:
                project_index = projects.index(selected_project)
                self.current_page = project_index // self.projects_per_page
            except ValueError:
                self.current_page = 0
        self.ui_updated_event.set()

    def change_page(self, delta: int):
        """Change the current page by delta and adjust selection."""
        with self.lock:
            projects = sorted(set(c['project'] for c in self.all_containers))
            total_pages = (len(projects) + self.projects_per_page - 1) // self.projects_per_page
            if total_pages == 0:
                return

            self.current_page = (self.current_page + delta) % total_pages
            if self.current_page < 0:
                self.current_page += total_pages

            start_project_index = self.current_page * self.projects_per_page
            if projects and start_project_index < len(projects):
                target_project = projects[start_project_index]
                for i, c in enumerate(self.all_containers):
                    if c['project'] == target_project:
                        self.selected_index = i
                        break
            else:
                self.selected_index = 0
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

def run_docker_command(live_display: Live, command: List[str], container_name: str, confirm: bool = False):
    """
    Pauses the live display to run a Docker command, handling interactive and non-interactive cases.
    """
    live_display.stop()
    console.clear(home=True)
    try:
        is_streaming_interactive = (command[1] == "exec" and "-it" in command) or \
                                   (command[1] == "logs" and "-f" in command)

        if confirm:
            action = command[1].capitalize()
            console.print(f"\n[bold yellow]Are you sure you want to {action} container '{container_name}'? (y/n)[/bold yellow]")
            key = readchar.readkey().lower()
            if key != 'y':
                console.print("[green]Aborted.[/green]")
                time.sleep(1)
                return

        if is_streaming_interactive:
            command_str = " ".join(command)
            if "logs -f" in command_str:
                console.print(f"[bold cyan]Showing live logs for '{container_name}'. Press Ctrl+C to return.[/bold cyan]")
            os.system(command_str)
        else:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                console.print(f"[bold red]Command failed (exit code {result.returncode}):[/bold red]")
                output = result.stderr.strip() or result.stdout.strip()
                if output:
                    console.print(output)
            else:
                output = result.stdout.strip()
                if output:
                    console.print(output)
                else:
                    console.print(f"[green]✅ Command '{' '.join(command[1:3])}...' executed successfully on '{container_name}'.[/green]")
            
            console.input("\n[bold]Press Enter to return...[/bold]")

    except Exception as e:
        logger.error(f"Failed to execute command: {e}")
        console.print(f"[bold red]Failed to execute command:[/bold red]\n{e}")
        console.input("\n[bold]Press Enter to return...[/bold]")
    finally:
        live_display.start(refresh=True)

def generate_ui(groups: Dict[str, List[Dict]], state: AppState) -> Layout:
    """Generate the main UI layout with paginated project tables."""
    layout = Layout(name="root")
    layout.split(
        Layout(name="header", size=3),
        Layout(ratio=1, name="main"),
        Layout(size=1, name="footer")
    )
    
    header_text = Text(" DockedUp - Interactive Docker Compose Monitor", justify="center", style="bold magenta")
    if state.debug_mode:
        header_text.append(" [DEBUG MODE]", style="bold red")
    layout["header"].update(Align.center(header_text))
    
    all_project_names = sorted(groups.keys())
    flat_list = []
    for proj_name in all_project_names:
        flat_list.extend(sorted(groups[proj_name], key=lambda c: c.get('name', '')))
    state.update_containers(flat_list)

    if not state.all_containers:
        layout["main"].update(
            Align.center(
                Text("No containers found.\nMake sure Docker is running and you have containers.", style="yellow"),
                vertical="middle"
            )
        )
    else:
        projects = sorted(set(c['project'] for c in state.all_containers))
        total_pages = (len(projects) + state.projects_per_page - 1) // state.projects_per_page
        if total_pages > 0:
            state.current_page = max(0, min(state.current_page, total_pages - 1))
        else:
            state.current_page = 0
        
        start_idx = state.current_page * state.projects_per_page
        end_idx = start_idx + state.projects_per_page
        displayed_projects = projects[start_idx:end_idx]

        tables_on_page = []
        for project_name in displayed_projects:
            containers_in_project = groups.get(project_name, [])

            table = Table(title=f"Project: [bold cyan]{project_name}[/bold cyan]", border_style="blue", expand=True)
            table.add_column("Container", style="cyan", no_wrap=True)
            table.add_column("Status", justify="left")
            table.add_column("Uptime", justify="right")
            table.add_column("Health", justify="left")
            table.add_column("CPU %", justify="right")
            table.add_column("MEM USAGE / LIMIT", justify="right")

            for container in containers_in_project:
                global_index = state.container_id_to_index.get(container['id'], -1)
                row_style = "on blue" if global_index == state.selected_index else ""
                
                is_running = '✅ Up' in container['status']
                uptime_str = format_uptime(container.get('started_at')) if is_running else "[grey50]—[/grey50]"
                
                table.add_row(
                    container["name"], container["status"], uptime_str, container["health"],
                    container["cpu"], container["memory"], style=row_style
                )
            
            tables_on_page.append(Panel(table, border_style="dim blue"))

        page_info = f"Page {state.current_page + 1} of {total_pages}" if total_pages > 0 else "Page 1 of 1"
        main_content = Group(*tables_on_page)
        layout["main"].update(Panel(main_content, title=page_info, border_style="dim blue"))

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
  ↑/↓ or k/j    Navigate up/down (stops at ends)
  PgUp/PgDn     Change page
  q or Ctrl+C   Quit DockedUp

[bold yellow]Container Actions:[/bold yellow]
  l             View logs (live for running, static for stopped)
  r             Restart container (with confirmation)
  s             Open shell session (in running containers)
  x             Stop container (with confirmation)

[bold yellow]Other:[/bold yellow]
  ?             Show this help screen

[bold green]Tip:[/bold green] Use the arrow keys to select a container, then press the action key.
"""
    console.print(Panel(help_content, title="Help", border_style="cyan"))
    console.input("\n[bold]Press Enter to return to DockedUp...[/bold]")

@app.command()
def main(
    refresh_rate: Annotated[
        float, typer.Option("--refresh", "-r", help="UI refresh rate in seconds (default: 1.0)", min=0.1, max=60.0)
    ] = 1.0,
    debug: Annotated[
        bool, typer.Option("--debug", "-d", help="Enable debug mode with verbose logging")
    ] = False,
    version: Annotated[
        Optional[bool], typer.Option("--version", "-v", callback=version_callback, is_eager=True, help="Show version and exit")
    ] = None,
):
    """🐳 Interactive Docker Compose stack monitor."""
    setup_logging(debug=debug)
    
    try:
        client = docker.from_env(timeout=5)
        client.ping()
        logger.debug("Successfully connected to Docker daemon")
    except DockerException as e:
        console.print(f"[bold red]Error: Failed to connect to Docker.[/bold red]")
        if isinstance(getattr(e, 'original_error', None), FileNotFoundError):
            console.print("\n[bold yellow]Could not find the Docker socket.[/bold yellow]")
        else:
            console.print(f"Details: {e}")
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
                
                if key == readchar.key.CTRL_C or key.lower() == 'q':
                    should_quit.set()
                    break
                elif key in (readchar.key.UP, 'k'):
                    app_state.move_selection(-1)
                elif key in (readchar.key.DOWN, 'j'):
                    app_state.move_selection(1)
                elif key == readchar.key.PAGE_UP:
                    app_state.change_page(-1)
                elif key == readchar.key.PAGE_DOWN:
                    app_state.change_page(1)
                elif key == '?':
                    live.stop()
                    console.clear(home=True)
                    show_help_screen()
                    live.start(refresh=True)
                else:
                    container = app_state.get_selected_container()
                    if container:
                        if key.lower() == 'l':
                            is_running = 'Up' in container['status']
                            cmd = ["docker", "logs", "--tail", "100", container['id']]
                            if is_running:
                                cmd.insert(2, "-f")
                            run_docker_command(live, cmd, container['name'])
                        elif key.lower() == 'r':
                            run_docker_command(live, ["docker", "restart", container['id']], container['name'], confirm=True)
                        elif key.lower() == 'x':
                            run_docker_command(live, ["docker", "stop", container['id']], container['name'], confirm=True)
                        elif key.lower() == 's':
                            run_docker_command(live, ["docker", "exec", "-it", container['id'], "/bin/sh"], container['name'])
                
                app_state.ui_updated_event.set()
            
            except KeyboardInterrupt:
                should_quit.set()
                break
            except Exception as e:
                logger.error(f"Input handler error: {e}")
                should_quit.set()
                break
        
        app_state.ui_updated_event.set()

    try:
        with Live(console=console, screen=True, transient=True, redirect_stderr=False, auto_refresh=False) as live:
            logger.debug("Starting container monitor")
            monitor.run()
            
            input_thread = threading.Thread(target=input_worker, args=(live,), daemon=True, name="input-worker")
            input_thread.start()
            
            while not should_quit.is_set():
                grouped_data = monitor.get_grouped_containers()
                ui_layout = generate_ui(grouped_data, app_state)
                live.update(ui_layout, refresh=True)
                
                app_state.ui_updated_event.wait(timeout=refresh_rate)
                app_state.ui_updated_event.clear()

    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
        if debug: console.print_exception()
    finally:
        if not should_quit.is_set():
            should_quit.set()
        
        monitor.stop()
        console.print("\n[bold yellow]👋 See you soon![/bold yellow]")

if __name__ == "__main__":
    app()