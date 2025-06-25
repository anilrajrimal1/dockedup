import time
import subprocess
import threading
from typing_extensions import Annotated
from typing import Dict, List

import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.align import Align
from rich.text import Text
import docker
from docker.errors import DockerException
import readchar

from .docker_monitor import ContainerMonitor
from .utils import format_uptime

app = typer.Typer(
    name="dockedup",
    help="htop for your Docker Compose stack. An interactive, real-time monitor.",
    add_completion=False,
)
console = Console()

class AppState:
    """Manages the application's shared interactive state with thread-safety."""
    def __init__(self):
        self.all_containers: List[Dict] = []
        self.selected_index: int = 0
        self.lock = threading.Lock()
        self.ui_updated_event = threading.Event()

    def update_containers(self, containers: List[Dict]):
        with self.lock:
            current_id = self._get_selected_container_id_unsafe()
            self.all_containers = containers
            if current_id:
                for i, c in enumerate(self.all_containers):
                    if c.get('id') == current_id:
                        self.selected_index = i
                        return
            self._move_selection_unsafe(0)

    def get_selected_container(self) -> Dict | None:
        with self.lock:
            if self.all_containers and 0 <= self.selected_index < len(self.all_containers):
                return self.all_containers[self.selected_index]
        return None

    def _get_selected_container_id_unsafe(self) -> str | None:
        if self.all_containers and 0 <= self.selected_index < len(self.all_containers):
            return self.all_containers[self.selected_index].get('id')
        return None

    def move_selection(self, delta: int):
        with self.lock:
            self._move_selection_unsafe(delta)
        self.ui_updated_event.set()

    def _move_selection_unsafe(self, delta: int):
        if not self.all_containers:
            self.selected_index = 0
            return
        self.selected_index = (self.selected_index + delta) % len(self.all_containers)

def run_docker_command(live_display: Live, command: List[str], container_name: str, confirm: bool = False):
    """Pauses the live display to run a Docker command in the foreground."""
    live_display.stop()
    try:
        if confirm:
            action = command[1].capitalize()
            console.print(f"\n[bold yellow]Are you sure you want to {action} container '{container_name}'? (y/n)[/bold yellow]")
            key = readchar.readkey().lower()
            if key != 'y':
                console.print("[green]Aborted.[/green]")
                time.sleep(1)
                return

        subprocess.run(command)
        if "-f" not in command and "exec" not in command:
            console.input("\n[bold]Press Enter to return to DockedUp...[/bold]")
    except Exception as e:
        console.print(f"[bold red]Failed to execute command:[/bold red]\n{e}")
        console.input("\n[bold]Press Enter to return to DockedUp...[/bold]")
    finally:
        console.clear()
        live_display.start()

def generate_layout() -> Layout:
    layout = Layout(name="root")
    layout.split(Layout(name="header", size=3), Layout(ratio=1, name="main"), Layout(size=1, name="footer"))
    layout["header"].update(Align.center(Text(" DockedUp - Interactive Docker Compose Monitor", justify="center", style="bold magenta")))
    return layout

def generate_ui(groups: Dict[str, List[Dict]], state: AppState) -> Layout:
    """Builds the entire UI renderable from the current state."""
    layout = generate_layout()
    flat_list = [c for project_containers in groups.values() for c in project_containers]
    state.update_containers(flat_list)

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
            row_style = "on blue" if is_selected else ""
            table.add_row(
                container["name"], container["status"], format_uptime(container.get('started_at')),
                container["health"], container["cpu"], container["memory"], style=row_style
            )
            current_flat_index += 1
        tables.append(Panel(table, border_style="dim blue", expand=True))
    
    if not groups:
        layout["main"].update(Align.center(Text("No containers found.", style="yellow"), vertical="middle"))
    else:
        layout["main"].split_column(*tables)

    footer_text = "[b]Q[/b]uit | [b]↑/↓[/b] Navigate"
    if state.get_selected_container():
        footer_text += " | [b]L[/b]ogs | [b]R[/b]estart | [b]S[/b]hell | [b]X[/b] Stop"
    layout["footer"].update(Align.center(footer_text))
    
    return layout

@app.callback(invoke_without_command=True)
def main(
    refresh_rate: Annotated[float, typer.Option("--refresh", "-r", help="UI refresh rate in seconds.")] = 1.0,
):
    try:
        client = docker.from_env(timeout=5); client.ping()
    except DockerException as e:
        console.print(f"[bold red]Error:[/bold red] Failed to connect to Docker. Is it running?\n{e}"); raise typer.Exit(code=1)

    monitor = ContainerMonitor(client)
    app_state = AppState()
    should_quit = threading.Event()

    def input_worker(live: Live):
        while not should_quit.is_set():
            try:
                key = readchar.readkey()
                if key == readchar.key.UP: app_state.move_selection(-1)
                elif key == readchar.key.DOWN: app_state.move_selection(1)
                elif key.lower() == 'q': should_quit.set(); app_state.ui_updated_event.set()
                else:
                    container = app_state.get_selected_container()
                    if container:
                        container_id = container['id']; container_name = container['name']
                        if key.lower() == 'l': run_docker_command(live, ["docker", "logs", "-f", "--tail", "100", container_id], container_name)
                        elif key.lower() == 'r': run_docker_command(live, ["docker", "restart", container_id], container_name, confirm=True)
                        elif key.lower() == 'x': run_docker_command(live, ["docker", "stop", container_id], container_name, confirm=True)
                        elif key.lower() == 's': run_docker_command(live, ["docker", "exec", "-it", container_id, "/bin/sh"], container_name)
                        app_state.ui_updated_event.set() # Force refresh after returning from command
            except (KeyboardInterrupt):
                should_quit.set()

    try:
        with Live(console=console, screen=True, transient=True, redirect_stderr=False, auto_refresh=False) as live:
            monitor.run()
            input_thread = threading.Thread(target=input_worker, args=(live,), daemon=True)
            input_thread.start()

            while not should_quit.is_set():
                grouped_data = monitor.get_grouped_containers()
                ui_layout = generate_ui(grouped_data, app_state)
                live.update(ui_layout, refresh=True)
                
                # Wait for a UI update event OR a timeout
                app_state.ui_updated_event.wait(timeout=refresh_rate)
                app_state.ui_updated_event.clear()

    except Exception as e:
        console.print_exception()
    finally:
        should_quit.set()
        monitor.stop()
        console.print("\n[bold yellow]See you soon![/bold yellow]")

if __name__ == "__main__":
    app()