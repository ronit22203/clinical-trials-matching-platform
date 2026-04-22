"""
Temporal activities: each function runs in an activity worker,
isolated from workflow logic, and is retried independently on failure.
"""
import asyncio
from typing import Any

from temporalio import activity

@activity.defn
async def distill_query_activity(query: str, model: str) -> str:
    """
    Use the LLM to extract the core clinical concept from a user query.

    Returns a concise search term suitable for passing to clinical APIs
    (PubMed, ClinicalTrials.gov, openFDA) that do not perform their own
    natural-language query refinement. Called once per workflow run before
    the parallel tool fan-out so all tools share the same focused term.
    """
    from src.llm_factory import build_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = build_llm(model, temperature=0.0)

    system = (
        "You are a clinical query distillation assistant. "
        "Given a user question, extract the single most specific clinical concept "
        "(drug name, condition, intervention, or biomarker) that should be searched "
        "in medical databases. Reply with ONLY the search term — no punctuation, "
        "no explanation, no surrounding text."
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=query),
    ]

    response = await asyncio.to_thread(llm.invoke, messages)
    distilled = response.content.strip().strip('"').strip("'")
    # Fallback: if the model returned something too long or empty, use the raw query
    if not distilled or len(distilled) > 120:
        return query
    return distilled


@activity.defn
async def execute_tool_activity(tool_name: str, query: str) -> str:
    """
    Load a tool from the registry and execute it.

    Runs synchronous tool.execute() in a thread so the event loop is
    not blocked. Returns a JSON-serialisable string so Temporal can
    serialise the result across process boundaries.
    """
    from src.tools.registry import ToolRegistry

    registry = ToolRegistry.from_app_config()
    tool = registry.get_tool(tool_name)
    if tool is None:
        raise ValueError(f"Tool '{tool_name}' not found in registry.")

    result = await asyncio.to_thread(tool.execute, query)
    return str(result)


@activity.defn
async def synthesize_results_activity(
    query: str, tool_results: dict[str, str], model: str, system_prompt: str
) -> str:
    """
    Call the LLM to synthesise all tool results into a final answer.

    Runs the blocking LLM call in a thread to keep the event loop free.
    GraphRAG results (internal knowledge base) are listed first and the
    LLM is instructed to treat them as primary evidence, not a fallback.
    """
    from src.llm_factory import build_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = build_llm(model)

    # Separate graphrag results from external API results so we can
    # instruct the LLM to weight them appropriately.
    graphrag_results = {k: v for k, v in tool_results.items() if "graphrag" in k.lower()}
    api_results = {k: v for k, v in tool_results.items() if "graphrag" not in k.lower()}

    sections: list[str] = []

    if graphrag_results:
        sections.append("=== INTERNAL KNOWLEDGE BASE (treat as primary evidence) ===")
        for name, result in graphrag_results.items():
            sections.append(f"[{name}]\n{result}")

    if api_results:
        sections.append("=== EXTERNAL CLINICAL DATABASES ===")
        for name, result in api_results.items():
            sections.append(f"[{name}]\n{result}")

    formatted_results = "\n\n".join(sections)

    prompt = (
        f"Query: {query}\n\n"
        f"{formatted_results}\n\n"
        "Instructions:\n"
        "- Internal knowledge base results are primary evidence — cite them directly and specifically.\n"
        "- Do NOT dismiss or downplay internal knowledge base results as 'no direct data'; "
        "they represent curated domain knowledge.\n"
        "- Supplement with external database findings where they add detail.\n"
        "- Synthesise a comprehensive, evidence-based answer."
    )

    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=prompt))

    response = await asyncio.to_thread(llm.invoke, messages)
    return response.content
