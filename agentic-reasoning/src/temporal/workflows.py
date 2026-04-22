"""
Temporal workflow definition.

Workflows must be deterministic — no I/O, no randomness, no time calls.
All side effects live in activities, which are orchestrated here.
"""
import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import TimeoutError as TemporalTimeoutError

with workflow.unsafe.imports_passed_through():
    from src.temporal.activities import execute_tool_activity, synthesize_results_activity, distill_query_activity


RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
)

TOOL_TIMEOUT = timedelta(seconds=30)
SYNTHESIS_TIMEOUT = timedelta(seconds=120)
APPROVAL_TIMEOUT = timedelta(minutes=10)


@workflow.defn
class ClinicalResearchWorkflow:
    """
    Orchestrate parallel tool calls then synthesise with the LLM.

    When require_approval=True the workflow pauses after collecting tool
    results and waits for an external approve() signal before synthesis.
    This implements a human-in-the-loop review gate.
    """

    def __init__(self) -> None:
        self._approved: bool = False
        self._tool_results: dict[str, str] = {}

    @workflow.signal
    async def approve(self) -> None:
        """Signal sent by an operator to approve synthesis after reviewing tool results."""
        self._approved = True

    @workflow.query
    def get_tool_results(self) -> dict[str, str]:
        """Query tool results collected so far (available before synthesis completes)."""
        return self._tool_results

    @workflow.run
    async def run(
        self,
        query: str,
        tools: list[str],
        model: str,
        system_prompt: str,
        require_approval: bool = False,
    ) -> dict[str, Any]:
        # Distill the user query into a focused clinical search term.
        tool_query = await workflow.execute_activity(
            distill_query_activity,
            args=[query, model],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RETRY_POLICY,
        )

        # Execute all tools in parallel using the distilled query.
        tool_tasks = [
            workflow.execute_activity(
                execute_tool_activity,
                args=[tool_name, tool_query],
                start_to_close_timeout=TOOL_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )
            for tool_name in tools
        ]

        raw_results = await asyncio.gather(*tool_tasks, return_exceptions=True)

        for tool_name, result in zip(tools, raw_results):
            if isinstance(result, Exception):
                self._tool_results[tool_name] = f"Error: {result}"
            else:
                self._tool_results[tool_name] = result

        # Human-in-the-loop gate: wait for approve() signal before synthesis
        if require_approval:
            try:
                await workflow.wait_condition(
                    lambda: self._approved,
                    timeout=APPROVAL_TIMEOUT,
                )
            except TemporalTimeoutError:
                return {
                    "query": query,
                    "tool_results": self._tool_results,
                    "synthesis": "Workflow timed out waiting for human approval.",
                    "approved": False,
                    "workflow_id": workflow.info().workflow_id,
                    "run_id": workflow.info().run_id,
                }

        synthesis = await workflow.execute_activity(
            synthesize_results_activity,
            args=[query, self._tool_results, model, system_prompt],
            start_to_close_timeout=SYNTHESIS_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )

        return {
            "query": query,
            "tool_results": self._tool_results,
            "synthesis": synthesis,
            "approved": self._approved if require_approval else None,
            "workflow_id": workflow.info().workflow_id,
            "run_id": workflow.info().run_id,
        }
