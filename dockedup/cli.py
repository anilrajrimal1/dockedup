"""
DockedUp CLI - Interactive Docker Compose stack monitor.
"""
import time
import subprocess
import threading
import sys
import logging
from typing import Dict, List, Optional
from typing_extensions import Annotated
import typer
from rich.console import Console
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
        self.lock = threading.Lock()
        self.ui_updated_event = threading.Event()
        self.debug_mode: bool = False

    def update_containers(self, containers: List[Dict]):
        """Update the containers list while preserving selection."""
        with self.lock:
            current_id = self._get_selected_container_id_unsafe()
            self.all_containers = containers
            if current_id:
                for i, c in enumerate(self.all_containers):
                    if c.get('id') == current_id:
                        self.selected_index = i
                        return
            self._move_selection_unsafe(0)

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
        """Move selection up/down by delta positions."""
        with self.lock:
            self._move_selection_unsafe(delta)
        self.ui_updated_event.set()

    def _move_selection_unsafe(self, delta: int):
        """Move selection without acquiring lock (internal use)."""
        if not self.all_containers:
            self.selected_index = 0
            return
        self.selected_index = (self.selected_index + delta) % len(self.all_containers)

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
    """Pauses the live display to run a Docker command in the foreground."""
    live_display.stop()
    console.clear(home=True)
    try:
        if confirm:
            action = command[1].capitalize()
            console.print(f"\n[bold yellow]Are you sure you want to {action} container '{container_name}'? (y/n)[/bold yellow]")
            key = readchar.readkey().lower()
            if key != 'y':
                console.print("[green]Aborted.[/green]")
                time.sleep(1)
                return
        
        is_interactive = "-f" in command or "-it" in command
        
        if is_interactive:
            if "logs" in command:
                console.print(f"[bold cyan]Showing live logs for '{container_name}'. Press Ctrl+C to return to DockedUp.[/bold cyan]")
            
            try:
                subprocess.run(command)
            except KeyboardInterrupt:
                pass
        else:
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                console.print(f"[bold red]Command failed:[/bold red] {result.stderr or result.stdout}")
            else:
                console.print(f"[green]✅ Command executed successfully[/green]")
            console.input("\n[bold]Press Enter to return to DockedUp...[/bold]")

    except Exception as e:
        logger.error(f"Failed to execute command: {e}")
        console.print(f"[bold red]Failed to execute command:[/bold red]\n{e}")
        console.input("\n[bold]Press Enter to return to DockedUp...[/bold]")
    finally:
        live_display.start(refresh=True)

def generate_ui(groups: Dict[str, List[Dict]], state: AppState) -> Layout:
    """Generate the main UI layout."""
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
    
    flat_list = [c for project_containers in groups.values() for c in project_containers]
    state.update_containers(flat_list)

    if not groups:
        layout["main"].update(
            Align.center(
                Text("No containers found.\nMake sure Docker is running and you have containers.", style="yellow"),
                vertical="middle"
            )
        )
    else:
        tables = []
        current_flat_index = 0
        for project_name, containers in groups.items():
            table = Table(title=f"Project: [bold cyan]{project_name}[/bold cyan]", border_style="blue", expand=True)
            table.add_column("Container", style="cyan", no_wrap=True)
            table.add_column("Status", justify="left")
            table.add_column("Uptime", justify="right")
            table.add_column("Health", justify="left")
            table.add_column("CPU %", justify="right")
            table.add_column("MEM USAGE / LIMIT", justify="right")
            for container in containers:
                with state.lock:
                    is_selected = (current_flat_index == state.selected_index)
                is_running = '✅ Up' in container['status']
                uptime_str = format_uptime(container.get('started_at')) if is_running else "[grey50]—[/grey50]"
                row_style = "on blue" if is_selected else ""
                table.add_row(
                    container["name"], container["status"], uptime_str, container["health"],
                    container["cpu"], container["memory"], style=row_style
                )
                current_flat_index += 1
            tables.append(Panel(table, border_style="dim blue", expand=True))
        layout["main"].split_column(*tables)

    footer_text = "[b]Q[/b]uit | [b]↑/↓[/b] Navigate"
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
  ↑/↓ or k/j    Navigate up/down
  q or Ctrl+C   Quit DockedUp

[bold yellow]Container Actions:[/bold yellow]
  l             View live logs
  r             Restart container (with confirmation)
  s             Open shell session
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
                elif key == readchar.key.UP or key.lower() == 'k':
                    app_state.move_selection(-1)
                elif key == readchar.key.DOWN or key.lower() == 'j':
                    app_state.move_selection(1)
                elif key == '?':
                    live.stop()
                    console.clear(home=True)
                    show_help_screen()
                    live.start(refresh=True)
                else:
                    container = app_state.get_selected_container()
                    if container:
                        if key.lower() == 'l':
                            run_docker_command(live, ["docker", "logs", "-f", "--tail", "100", container['id']], container['name'])
                        elif key.lower() == 'r':
                            run_docker_command(live, ["docker", "restart", container['id']], container['name'], confirm=True)
                        elif key.lower() == 'x':
                            run_docker_command(live, ["docker", "stop", container['id']], container['name'], confirm=True)
                        elif key.lower() == 's':
                            run_docker_command(live, ["docker", "exec", "-it", container['id']], container['name'], "/bin/sh")
                
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