import time
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

from .docker_monitor import ContainerMonitor
from .utils import format_uptime

app = typer.Typer(
    name="dockedup",
    help="htop for your Docker Compose stack. A live, beautiful Docker Compose monitor.",
    add_completion=False,
)
console = Console()

def generate_layout() -> Layout:
    layout = Layout(name="root")
    layout.split(
        Layout(name="header", size=3),
        Layout(ratio=1, name="main"),
        Layout(size=1, name="footer")
    )
    layout["header"].update(
        Align.center(
            Text("🚀 DockedUp - Real-time Docker Compose Monitor", justify="center", style="bold magenta"),
            vertical="middle"
        )
    )
    return layout

def generate_tables_from_groups(groups: Dict[str, List[Dict]]) -> Layout:
    layout = Layout()
    if not groups:
        layout.update(Align.center(Text("No containers found.", style="yellow"), vertical="middle"))
        return layout

    tables = []
    for project_name, containers in groups.items():
        table = Table(
            title=f"Project: [bold cyan]{project_name}[/bold cyan]",
            title_style="", border_style="blue", expand=True
        )
        table.add_column("Container", style="cyan", no_wrap=True)
        table.add_column("Status", justify="left")
        table.add_column("Uptime", justify="right")
        table.add_column("Health", justify="left")
        table.add_column("Ports", justify="left")
        table.add_column("CPU %", justify="right")
        table.add_column("MEM USAGE / LIMIT", justify="right")

        for container in containers:
            table.add_row(
                container["name"],
                container["status"],
                format_uptime(container.get('started_at')),
                container["health"],
                container["ports"],
                container["cpu"],
                container["memory"],
            )
        tables.append(Panel(table, border_style="dim blue", expand=True))

    layout.split_column(*tables)
    return layout

@app.callback(invoke_without_command=True)
def main(
    refresh_rate: Annotated[float, typer.Option(
        "--refresh", "-r", help="UI refresh rate in seconds (data is real-time)."
    )] = 0.5,
):
    try:
        client = docker.from_env(timeout=5)
        client.ping()
    except DockerException as e:
        console.print(f"[bold red]Error:[/bold red] Failed to connect to Docker. Is it running?\n{e}")
        raise typer.Exit(code=1)

    monitor = ContainerMonitor(client)
    layout = generate_layout()

    try:
        with Live(layout, screen=True, transient=True, redirect_stderr=False, refresh_per_second=1/refresh_rate) as live:
            monitor.run()
            
            while not monitor.stop_event.is_set():
                grouped_data = monitor.get_grouped_containers()
                table_layout = generate_tables_from_groups(grouped_data)
                layout["main"].update(table_layout)
                layout["footer"].update(
                    Align.right(f"⚡️ Real-time data | UI Refresh: {refresh_rate}s | Press Ctrl+C to exit")
                )
                time.sleep(refresh_rate)

    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()
        console.print("\n[bold yellow] Exiting DockedUp. 👋 ![/bold yellow]")

if __name__ == "__main__":
    app()