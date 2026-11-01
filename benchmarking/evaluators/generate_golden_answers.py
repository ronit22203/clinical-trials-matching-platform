"""
generate_golden_answers.py — One-time reference answers from the source PDF.

Extracts text from the sepsis paper and asks gpt-6.1-sol to write a
document-grounded answer for each golden query. Re-running skips ids that
already have an answer unless --force is set. Progress is saved after each query.

Usage:
    python evaluators/generate_golden_answers.py \\
        --pdf ../data/pdfs/raw/medrxiv/2026/04/22/10.64898/2026.03.17.26348414/paper.pdf \\
        --queries golden/queries.json \\
        --output golden/golden_answers.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai_client import complete_text, load_env, parse_json_object, resolve_api_key, resolve_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_BENCHMARKING_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BENCHMARKING_DIR.parent
_DEFAULT_PDF = (
    _REPO_ROOT
    / "data/pdfs/raw/medrxiv/2026/04/22/10.64898/2026.03.17.26348414/paper.pdf"
)

_INSTRUCTIONS = """You write the reference answer for a clinical-paper benchmark.
Use only the paper text in the user message. Do not add outside knowledge.
If the paper does not support a claim, say that explicitly.
Return a JSON object with exactly these keys:
  "answer": a definitive prose answer to the question
  "entities_and_facts": an array of the concrete entities and facts you used
"""


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract embedded text from every page. Does not use chunk artifacts."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(pdf_path))
    pages: list[str] = []
    try:
        for index in range(len(document)):
            page = document[index]
            text_page = page.get_textpage()
            try:
                pages.append(text_page.get_text_bounded() or "")
            finally:
                text_page.close()
                page.close()
    finally:
        document.close()
    return "\n\n".join(page.strip() for page in pages if page.strip()).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_answers(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with open(path) as handle:
        data = json.load(handle)
    answers = data.get("answers", [])
    return {item["id"]: item for item in answers if isinstance(item, dict) and item.get("id")}


def _write_output(
    path: Path,
    *,
    queries_data: dict[str, Any],
    pdf_path: Path,
    pdf_sha256: str,
    model: str,
    answers_by_id: dict[str, dict[str, Any]],
    query_order: list[str],
) -> None:
    payload = {
        "document_doi": queries_data.get("document_doi"),
        "document_title": queries_data.get("document_title"),
        "pdf_path": str(pdf_path),
        "pdf_sha256": pdf_sha256,
        "generator_model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "answers": [answers_by_id[qid] for qid in query_order if qid in answers_by_id],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    temporary.replace(path)


def _answer_one(api_key: str, model: str, paper_text: str, query_text: str) -> dict[str, Any]:
    raw = complete_text(
        api_key=api_key,
        model=model,
        instructions=_INSTRUCTIONS,
        user_text=f"PAPER:\n{paper_text}\n\nQUESTION:\n{query_text}",
        json_mode=True,
    )
    try:
        parsed = parse_json_object(raw)
    except (json.JSONDecodeError, ValueError):
        return {"answer": raw, "entities_and_facts": []}
    facts = parsed.get("entities_and_facts") or []
    if not isinstance(facts, list):
        facts = [str(facts)]
    answer = parsed.get("answer")
    return {
        "answer": answer.strip() if isinstance(answer, str) and answer.strip() else raw,
        "entities_and_facts": [str(item) for item in facts if str(item).strip()],
    }


def generate(
    pdf_path: Path,
    queries_path: Path,
    output_path: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    if not pdf_path.is_file():
        log.error("PDF not found: %s", pdf_path)
        sys.exit(1)

    env = load_env()
    api_key = resolve_api_key(env)
    if not api_key:
        log.error("OPENAI_API_KEY is missing. Add it to .env.local and rerun.")
        sys.exit(1)
    model = resolve_model(env)

    with open(queries_path) as handle:
        queries_data = json.load(handle)
    queries = queries_data.get("queries", [])
    if not queries:
        log.error("No queries in %s", queries_path)
        sys.exit(1)

    paper_text = extract_pdf_text(pdf_path)
    if not paper_text:
        log.error("Extracted no text from %s. The PDF may be image-only.", pdf_path)
        sys.exit(1)
    log.info("Extracted %d characters from %s", len(paper_text), pdf_path.name)

    pdf_sha256 = _sha256(pdf_path)
    answers_by_id = {} if force else _load_answers(output_path)
    query_order = [q.get("id", f"q{i+1:02d}") for i, q in enumerate(queries)]

    for query in queries:
        query_id = query.get("id")
        query_text = query.get("text", "")
        if not query_id or not query_text:
            log.error("Query missing id or text: %s", query)
            sys.exit(1)
        if query_id in answers_by_id:
            log.info("[%s] already answered — skipping", query_id)
            continue
        log.info("[%s] requesting reference answer", query_id)
        produced = _answer_one(api_key, model, paper_text, query_text)
        answers_by_id[query_id] = {
            "id": query_id,
            "query": query_text,
            "answer": produced["answer"],
            "entities_and_facts": produced["entities_and_facts"],
        }
        _write_output(
            output_path,
            queries_data=queries_data,
            pdf_path=pdf_path,
            pdf_sha256=pdf_sha256,
            model=model,
            answers_by_id=answers_by_id,
            query_order=query_order,
        )
        log.info("[%s] saved (%d chars)", query_id, len(produced["answer"]))

    log.info("Golden answers written → %s (%d answers)", output_path, len(answers_by_id))
    return {"answers": len(answers_by_id), "model": model, "output": str(output_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate document-grounded golden answers.")
    parser.add_argument("--pdf", type=Path, default=_DEFAULT_PDF)
    parser.add_argument("--queries", type=Path, default=_BENCHMARKING_DIR / "golden" / "queries.json")
    parser.add_argument("--output", type=Path, default=_BENCHMARKING_DIR / "golden" / "golden_answers.json")
    parser.add_argument("--force", action="store_true", help="Regenerate answers that already exist")
    args = parser.parse_args()
    generate(args.pdf, args.queries, args.output, force=args.force)


if __name__ == "__main__":
    main()
