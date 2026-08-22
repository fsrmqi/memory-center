'''共享的 typer.Option 单例。

从 cli/main.py 按独立职责拆出(ADR-0002):被多个命令族复用的选项对象。'''
from __future__ import annotations

import typer

RELEASE_GATE_QUERY_OPTION = typer.Option(
    None,
    "--query",
    help="Portable query smoke check; repeatable and never persisted.",
)
OPTIONAL_PROJECT_FILTER = typer.Option(None, help="Only rebuild indexes for these projects.")
OPTIONAL_PATH_FILTER = typer.Option(None, help="Only rebuild indexes for these logical or absolute paths.")
OPTIONAL_PROJECTS = typer.Option(None)
OPTIONAL_FILES = typer.Option(None)
REQUIRED_REF_IDS = typer.Option(...)
REQUIRED_PROJECTS = typer.Option(...)
REQUIRED_FILES = typer.Option(...)
OPTIONAL_RISK_POINTS = typer.Option(None)
OPTIONAL_VERIFIED_BY = typer.Option(None)
OPTIONAL_TAGS = typer.Option(None)
OPTIONAL_SESSION_IDS = typer.Option(None, help="Session ids to consolidate. Defaults to the most recent finished sessions.")
