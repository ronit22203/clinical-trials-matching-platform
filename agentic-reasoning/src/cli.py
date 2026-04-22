# src/cli.py
import logging
import os
import sys

# Suppress verbose output from ML/embedding libraries before any other imports.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
for _lib in ("sentence_transformers", "transformers", "huggingface_hub", "torch", "tqdm"):
    logging.getLogger(_lib).setLevel(logging.ERROR)

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from .config_loader import load_agent_config
from .agent import SimpleAgent
from .tools.registry import ToolRegistry
from .logging_handler import ExecutionLogger

load_dotenv()
console = Console()

def _flush_stdin() -> None:
    """Discard buffered stdin (e.g. leftover lines from a multi-line paste)."""
    try:
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass


def _print_agent_info(config) -> None:
    """Display a startup panel with agent details."""
    grid = Table.grid(padding=(0, 1))
    grid.add_column(style="dim")
    grid.add_column()
    grid.add_row("Model:", config.model)
    if config.tools:
        grid.add_row("Tools:", ", ".join(t.name for t in config.tools))
    console.print(Panel(grid, title=f"[bold green]{config.name}[/bold green]", expand=False))


@click.command()
@click.option('--agent', '-a', default=None, help='Agent name from config/app.yaml (default: configured default agent)')
@click.option('--tools-dir', default=None, help='Deprecated; tools are loaded from config/app.yaml')
@click.option('--log-dir', default='log', help='Path to logging directory')
@click.option('--use-temporal', is_flag=True, default=False, help='Run query via Temporal workflow (requires worker)')
@click.option('--human-in-loop', is_flag=True, default=False, help='Pause after tool results for human review before synthesis (requires --use-temporal)')
@click.option('--parallel', is_flag=True, default=False, help='Fan out all tool calls concurrently before LLM synthesis (non-Temporal)')
@click.argument('query', required=False)
def main(agent, tools_dir, log_dir, use_temporal, human_in_loop, parallel, query):
    """Run a clinical agent. Use --use-temporal to run via Temporal workflow."""
    try:
        config = load_agent_config(agent)
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    _print_agent_info(config)

    logger = ExecutionLogger(log_dir=log_dir)

    if use_temporal:
        if not query:
            mode_label = "temporal + human-in-loop" if human_in_loop else "temporal"
            console.print(f"[yellow]Interactive mode ({mode_label}) — type 'exit' to quit, 'clear' to clear screen.[/yellow]\n")
            try:
                while True:
                    query = console.input("[bold cyan]You:[/bold cyan] ").strip()
                    if not query:
                        continue
                    if query.lower() in ('exit', 'quit'):
                        break
                    if query.lower() in ('clear', '/clear'):
                        console.clear()
                        continue
                    _run_temporal(query, config, logger, human_in_loop=human_in_loop)
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Bye![/dim]")
        else:
            _run_temporal(query, config, logger, human_in_loop=human_in_loop)
        return

    tool_registry = None
    if config.tools:
        tool_registry = ToolRegistry.from_agent_config(config)

    agent_instance = SimpleAgent(config, tool_registry)

    if not query:
        console.print("[yellow]Interactive mode — type 'exit' to quit, 'clear' to clear screen.[/yellow]\n")
        try:
            while True:
                query = console.input("[bold cyan]You:[/bold cyan] ").strip()
                if not query:
                    continue
                if query.lower() in ('exit', 'quit'):
                    break
                if query.lower() in ('clear', '/clear'):
                    console.clear()
                    continue
                if parallel:
                    with console.status("[dim]Fetching tools in parallel…[/dim]", spinner="dots"):
                        response = agent_instance.run_parallel(query)
                    console.print(Markdown(f"**Agent:** {response}"))
                    metrics = agent_instance.metrics
                    if metrics.latency_ms:
                        console.print(f"[dim]({metrics.latency_ms:.0f} ms)[/dim]\n")
                    _log_execution(agent_instance, query, response, logger)
                else:
                    _stream_response(agent_instance, query, logger)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Bye![/dim]")
    else:
        if parallel:
            with console.status("[dim]Fetching tools in parallel…[/dim]", spinner="dots"):
                response = agent_instance.run_parallel(query)
            console.print(Markdown(response))
            _log_execution(agent_instance, query, response, logger)
        else:
            _stream_response(agent_instance, query, logger)


def _stream_response(agent: SimpleAgent, query: str, logger: ExecutionLogger) -> None:
    """Stream agent response tokens to the console, then log metrics."""
    for token in agent.stream(query):
        console.print(token, end="", markup=False)
    console.print()  # newline after stream ends
    metrics = agent.metrics
    if metrics.latency_ms:
        console.print(f"[dim]({metrics.latency_ms:.0f} ms)[/dim]\n")
    _log_execution(agent, query, metrics.response, logger)


def _run_temporal(query: str, config, logger: ExecutionLogger, human_in_loop: bool = False) -> None:
    """Execute query as a Temporal workflow and display the result."""
    from .temporal.client import run_research_sync, run_hitl_sync

    tool_names = [t.name for t in config.tools]

    try:
        if human_in_loop:
            console.print(f"[blue]Starting Temporal workflow (human-in-loop) with tools: {tool_names}[/blue]")

            def display_tool_results(workflow_id: str, tool_results: dict) -> None:
                console.print(f"\n[bold yellow]Tool results ready — Workflow ID: {workflow_id}[/bold yellow]")
                for tool_name, data in tool_results.items():
                    console.rule(f"[cyan]{tool_name}[/cyan]")
                    console.print(data[:800] + "..." if len(str(data)) > 800 else data)
                console.rule()

            def prompt_approval() -> bool:
                _flush_stdin()  # discard buffered lines from multi-line paste
                console.print("\n[bold]Approve synthesis? (y/n):[/bold] ", end="")
                try:
                    answer = input("").strip().lower()
                except EOFError:
                    answer = ""
                approved = answer in ("y", "yes")
                if approved:
                    console.print("[dim]Synthesising — this may take a moment…[/dim]")
                else:
                    console.print("[dim]Rejected.[/dim]")
                return approved

            result = run_hitl_sync(
                query=query,
                tools=tool_names,
                model=config.model,
                system_prompt=config.system_prompt or "",
                display_fn=display_tool_results,
                prompt_fn=prompt_approval,
            )
        else:
            console.print(f"[blue]Starting Temporal workflow with tools: {tool_names}[/blue]")
            result = run_research_sync(
                query=query,
                tools=tool_names,
                model=config.model,
                system_prompt=config.system_prompt or "",
            )
    except Exception as e:
        console.print(f"[red]Temporal workflow failed: {e}[/red]")
        console.print("[yellow]Is the Temporal worker running? Run: make temporal-worker[/yellow]")
        return

    console.print(Markdown(result["synthesis"]))
    console.print(f"\n[dim]Workflow ID: {result['workflow_id']}[/dim]")

    logger.log_execution(
        model=config.model,
        system_instruction=config.system_prompt or "",
        user_query=query,
        response=result["synthesis"],
        latency_ms=0.0,
        tools_called=list(result["tool_results"].keys()),
        tool_responses=result["tool_results"],
        tool_success_rate=1.0,
        router_intent="temporal-hitl" if human_in_loop else "temporal",
    )


def _log_execution(agent: SimpleAgent, query: str, response: str, logger: ExecutionLogger) -> None:
    """Log the execution with all metrics."""
    metrics = agent.metrics
    logger.log_execution(
        model=metrics.model,
        system_instruction=metrics.system_instruction,
        user_query=query,
        response=response,
        latency_ms=metrics.latency_ms,
        tokens_input=metrics.tokens_input,
        tokens_output=metrics.tokens_output,
        temperature=metrics.temperature,
        top_p=metrics.top_p,
        tools_called=metrics.tools_called,
        tool_responses=metrics.tool_responses,
        tool_success_rate=1.0 if metrics.tools_called else 1.0,
    )


if __name__ == '__main__':
    main()
