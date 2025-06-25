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
from rich.spinner import Spinner
from rich.text import Text

from docker.errors import DockerException

from .docker_monitor import get_docker_client, get_grouped_containers, FormattedContainer

app = typer.Typer(
    name="dockedup",
    help="htop for your Docker Compose stack. A live, beautiful Docker Compose monitor.",
    add_completion=False,
)
console = Console()

def generate_layout() -> Layout:
    """Define the main layout for the application."""
    layout = Layout(name="root")
    layout.split(
        Layout(name="header", size=3),
        Layout(ratio=1, name="main"),
        Layout(size=1, name="footer")
    )
    layout["header"].update(
        Align.center(
            Text("🚀 DockedUp - Your Docker Compose Monitor", justify="center", style="bold magenta"),
            vertical="middle"
        )
    )
    return layout

def generate_tables_from_groups(groups: Dict[str, List[FormattedContainer]]) -> Layout:
    """Create a Rich Table for each Compose project group."""
    layout = Layout()

    if not groups:
        layout.update(Align.center(Text("No containers found.", style="yellow"), vertical="middle"))
        return layout

    tables = []
    for project_name, containers in groups.items():
        table = Table(
            title=f"Project: [bold cyan]{project_name}[/bold cyan]",
            title_style="",
            border_style="blue",
            expand=True,
        )
        table.add_column("Container", style="cyan", no_wrap=True)
        table.add_column("Status", justify="left")
        table.add_column("Health", justify="left")
        table.add_column("Ports", justify="left")
        table.add_column("CPU %", justify="right")
        table.add_column("MEM USAGE / LIMIT", justify="right")

        for container in containers:
            table.add_row(
                container["name"],
                container["status"],
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
    refresh_rate: Annotated[int, typer.Option(
        "--refresh", "-r", help="Refresh rate in seconds."
    )] = 2,
):
    """
    Monitor Docker containers in a live, beautiful table.
    """
    try:
        client = get_docker_client()
    except DockerException as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    layout = generate_layout()

    with Live(layout, screen=True, transient=True, redirect_stderr=False) as live:
        try:
            while True:
                layout["footer"].update(
                    Align.right(f"🔁 Refreshing every {refresh_rate}s... Press Ctrl+C to exit.")
                )

                spinner = Spinner("dots", text=Text("Fetching container data...", style="green"))
                layout["main"].update(Align.center(spinner, vertical="middle"))
                live.update(layout)

                groups = get_grouped_containers(client)
                table_layout = generate_tables_from_groups(groups)
                layout["main"].update(table_layout)
                live.update(layout)

                time.sleep(refresh_rate)
        except KeyboardInterrupt:
            console.print("\n[bold yellow]👋 Exiting DockedUp. Goodbye![/bold yellow]")
        except DockerException as e:
            console.print(f"\n[bold red]Error:[/bold red] Lost connection to Docker daemon: {e}")
            raise typer.Exit(code=1)

if __name__ == "__main__":
    app()