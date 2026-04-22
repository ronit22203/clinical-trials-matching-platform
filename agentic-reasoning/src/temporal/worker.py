"""
Temporal worker process.

Run this in a separate terminal before using --use-temporal in the CLI:

    python -m src.temporal.worker
"""
import asyncio
import logging

from dotenv import load_dotenv

load_dotenv()  # Load .env before any activity imports so API keys are available.

from temporalio.client import Client
from temporalio.worker import Worker

from src.temporal.activities import execute_tool_activity, synthesize_results_activity, distill_query_activity
from src.temporal.workflows import ClinicalResearchWorkflow

TASK_QUEUE = "clinical-research-queue"
TEMPORAL_HOST = "localhost:7233"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


async def run_worker() -> None:
    client = await Client.connect(TEMPORAL_HOST)
    log.info("Connected to Temporal at %s", TEMPORAL_HOST)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[ClinicalResearchWorkflow],
        activities=[execute_tool_activity, synthesize_results_activity, distill_query_activity],
    )

    log.info("Worker listening on task queue: %s", TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
