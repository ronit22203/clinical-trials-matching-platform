"""
CLI for the two-phase clinical research agent.

Usage:
    clinical-agents query "What are the safety profiles of GLP-1 agonists?"
    clinical-agents query "..." --no-stream
    clinical-agents interactive
"""
from __future__ import annotations

import json
import logging
import sys

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .agent import Agent
from .logging_handler import ExecutionLogger

console = Console()
logger = logging.getLogger(__name__)


def _build_agent() -> Agent:
    try:
        return Agent.from_config()
    except Exception as exc:
        console.print(f"[red]Failed to load agent config:[/red] {exc}")
        sys.exit(1)


@click.group()
@click.option("--log-level", default="WARNING", help="Python logging level.")
def main(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


@main.command()
@click.argument("query")
@click.option("--stream/--no-stream", default=True, show_default=True, help="Stream response tokens.")
@click.option("--json-output", is_flag=True, default=False, help="Output raw JSON instead of formatted text.")
def query(query: str, stream: bool, json_output: bool) -> None:
    """Run a single clinical research query."""
    agent = _build_agent()
    exec_logger = ExecutionLogger()

    if json_output:
        result = agent.run_json(query)
        click.echo(json.dumps(result, indent=2))
        return

    console.print(Panel(f"[bold]{query}[/bold]", title="Query", border_style="blue"))

    if stream:
        console.print("\n[dim]Retrieving evidence from knowledge base…[/dim]")
        parts: list[str] = []
        for token in agent.stream(query):
            console.print(token, end="", markup=False)
            parts.append(token)
        console.print()
        synthesis = "".join(parts)
        evidence = getattr(agent, "last_evidence", {})
        latency_ms = 0.0
    else:
        console.print("\n[dim]Retrieving evidence and synthesizing…[/dim]")
        result = agent.run(query)
        synthesis = result.synthesis
        evidence = result.evidence
        latency_ms = result.latency_ms
        console.print(Markdown(synthesis))

    _log_execution(exec_logger, agent, query, synthesis, evidence, latency_ms)
    _print_evidence_summary(evidence)


@main.command()
def interactive() -> None:
    """Start an interactive REPL session."""
    agent = _build_agent()
    console.print(Panel(
        "[bold green]Clinical Research Agent[/bold green] — two-phase pipeline\n"
        "[dim]Type your query and press Enter. Type 'exit' or Ctrl-C to quit.[/dim]",
        border_style="green",
    ))

    while True:
        try:
            user_input = console.input("\n[bold blue]Query>[/bold blue] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Bye.[/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "q"}:
            console.print("[dim]Bye.[/dim]")
            break

        console.print("[dim]Retrieving evidence…[/dim]")
        parts: list[str] = []
        try:
            for token in agent.stream(user_input):
                console.print(token, end="", markup=False)
                parts.append(token)
            console.print()
        except Exception as exc:
            console.print(f"\n[red]Error:[/red] {exc}")

        evidence = getattr(agent, "last_evidence", {})
        _print_evidence_summary(evidence)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_evidence_summary(evidence: dict) -> None:
    hits = len(evidence.get("vector_results", []))
    facts = len(evidence.get("graph_facts", []))
    if hits or facts:
        console.print(
            f"\n[dim]Evidence: {hits} vector hit(s), {facts} graph fact(s)[/dim]"
        )


def _log_execution(
    exec_logger: ExecutionLogger,
    agent: Agent,
    query: str,
    synthesis: str,
    evidence: dict,
    latency_ms: float,
) -> None:
    try:
        exec_logger.log_execution(
            model=agent.config.model,
            system_instruction=agent.config.system_prompt,
            user_query=query,
            response=synthesis,
            latency_ms=latency_ms,
            tools_called=["graphrag"],
            tool_responses={"graphrag": json.dumps(evidence)},
        )
    except Exception as exc:
        logger.warning("Execution logging failed: %s", exc)
