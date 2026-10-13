"""Command-line interface. Subcommands (run, replay, serve, doctor, export) arrive in C01."""

from typing import Annotated

import typer

from repro import __version__

app = typer.Typer(
    name="repro",
    help="Reproduce agent-written changes base-vs-head and verify their claims.",
    no_args_is_help=True,
    add_completion=False,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"repro {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_print_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Reproduce agent-written changes base-vs-head and verify their claims."""
