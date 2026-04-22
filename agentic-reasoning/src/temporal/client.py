"""
Client helpers for starting and querying Temporal workflows.
"""
import asyncio
import time
from typing import Any

from temporalio.client import Client

from src.temporal.workflows import ClinicalResearchWorkflow

TASK_QUEUE = "clinical-research-queue"
TEMPORAL_HOST = "localhost:7233"


async def _connect() -> Client:
    return await Client.connect(TEMPORAL_HOST)


async def run_research_workflow(
    query: str,
    tools: list[str],
    model: str,
    system_prompt: str,
    require_approval: bool = False,
) -> dict[str, Any]:
    """Start a ClinicalResearchWorkflow and wait for the result."""
    client = await _connect()
    workflow_id = f"research-{int(time.time())}"
    result = await client.execute_workflow(
        ClinicalResearchWorkflow.run,
        args=[query, tools, model, system_prompt, require_approval],
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    return result


async def start_research_workflow(
    query: str,
    tools: list[str],
    model: str,
    system_prompt: str,
    require_approval: bool = False,
) -> tuple[Any, str]:
    """
    Start a workflow without waiting for completion.

    Returns (handle, workflow_id). The caller can poll get_tool_results
    and later call send_approval() or wait for the handle.
    """
    client = await _connect()
    workflow_id = f"research-{int(time.time())}"
    handle = await client.start_workflow(
        ClinicalResearchWorkflow.run,
        args=[query, tools, model, system_prompt, require_approval],
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    return handle, workflow_id


async def poll_tool_results(workflow_id: str) -> dict[str, str] | None:
    """
    Query the workflow for tool results collected so far.
    Returns None if the workflow is not yet at the approval gate.
    """
    client = await _connect()
    handle = client.get_workflow_handle(workflow_id)
    try:
        return await handle.query(ClinicalResearchWorkflow.get_tool_results)
    except Exception:
        return None


async def send_approval(workflow_id: str) -> None:
    """Send the approve signal to a waiting workflow."""
    client = await _connect()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(ClinicalResearchWorkflow.approve)


def run_research_sync(
    query: str,
    tools: list[str],
    model: str,
    system_prompt: str,
    require_approval: bool = False,
) -> dict[str, Any]:
    """Synchronous wrapper for use from Click CLI (no HITL)."""
    return asyncio.run(
        run_research_workflow(query, tools, model, system_prompt, require_approval)
    )


def run_hitl_sync(
    query: str,
    tools: list[str],
    model: str,
    system_prompt: str,
    display_fn,
    prompt_fn,
) -> dict[str, Any]:
    """
    Human-in-the-loop synchronous flow.

    User input (display + prompt) happens OUTSIDE asyncio.run() to avoid
    stdin corruption when blocking I/O is called from inside an event loop.
    """
    async def _start_and_collect() -> tuple[str, dict]:
        handle, workflow_id = await start_research_workflow(
            query, tools, model, system_prompt, require_approval=True
        )
        tool_results: dict[str, str] = {}
        for _ in range(60):  # poll up to 60s
            await asyncio.sleep(1)
            results = await poll_tool_results(workflow_id)
            if results:
                tool_results = results
                break
        return workflow_id, tool_results

    async def _finish(workflow_id: str, approved: bool, tool_results: dict) -> dict:
        client = await _connect()
        handle = client.get_workflow_handle(workflow_id)
        if not approved:
            await handle.cancel()
            return {
                "query": query,
                "tool_results": tool_results,
                "synthesis": "Synthesis not approved — workflow cancelled.",
                "approved": False,
                "workflow_id": workflow_id,
                "run_id": "",
            }
        await handle.signal(ClinicalResearchWorkflow.approve)
        return await handle.result()

    # Phase 1 (async): start workflow and wait for tool results
    workflow_id, tool_results = asyncio.run(_start_and_collect())

    # Phase 2 (sync): display results and get human decision — outside event loop
    display_fn(workflow_id, tool_results)
    approved = prompt_fn()

    # Phase 3 (async): approve or cancel
    return asyncio.run(_finish(workflow_id, approved, tool_results))
