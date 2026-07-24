"""Focused mock-based tests for graph extraction provenance and resumability."""

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_knowledge_graph import KnowledgeGraphBuilder
from src.processors.graph_creator import GraphCreator


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def run(self, query: str, **params: object) -> MagicMock:
        self.calls.append((query, params))
        result = MagicMock()
        result.single.return_value = {"deleted": 2}
        return result


class _FakeDriver:
    def __init__(self) -> None:
        self.session_instance = _FakeSession()

    def verify_connectivity(self) -> None:
        return None

    def session(self) -> _FakeSession:
        return self.session_instance

    def close(self) -> None:
        return None


@pytest.fixture
def artifact_dir() -> Path:
    path = Path(__file__).parent / ".graph_creator_test_artifacts"
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir()
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def config() -> dict:
    return {
        "neo4j": {"uri": "bolt://unused", "user": "neo4j", "password": "unused"},
        "knowledge_graph": {
            "model": "primary-model",
            "chat_url": "http://primary:30000/v1/chat/completions",
            "fallback_model": "fallback-model",
            "fallback_chat_url": "http://fallback:1234/v1/chat/completions",
            "health_timeout_seconds": 1,
            "max_retries": 1,
            "min_chunk_chars": 1,
        },
    }


@pytest.fixture
def creator(config: dict) -> GraphCreator:
    driver = _FakeDriver()
    with patch(
        "src.processors.graph_creator.GraphDatabase.driver", return_value=driver
    ):
        instance = GraphCreator(config)
    return instance


def _write_chunks(path: Path, content: str = "Metformin treats diabetes.") -> Path:
    chunks_file = path / "sample_chunks.json"
    chunks_file.write_text(
        json.dumps({"chunks": [{"content": content, "char_start": 3, "char_end": 31}]}),
        encoding="utf-8",
    )
    return chunks_file


def _response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        ok=True,
        status_code=200,
        text="",
        json=lambda: {"choices": [{"message": {"content": content}}]},
    )


def test_fallback_is_selected_before_posting_text(creator: GraphCreator) -> None:
    with (
        patch(
            "src.processors.graph_creator.requests.get",
            side_effect=[
                requests.exceptions.ConnectionError(),
                SimpleNamespace(ok=True, status_code=200),
            ],
        ) as get,
        patch(
            "src.processors.graph_creator.requests.post",
            return_value=_response('{"triplets":[]}'),
        ) as post,
    ):
        assert creator.extract_triplets("A" * 60) == []

    assert get.call_args_list[0].args[0] == "http://primary:30000/health"
    assert get.call_args_list[1].args[0] == "http://fallback:1234/health"
    assert post.call_args.args[0] == "http://fallback:1234/v1/chat/completions"
    assert post.call_args.kwargs["json"]["model"] == "fallback-model"


def test_unavailable_extractor_does_not_mark_progress(
    creator: GraphCreator, artifact_dir: Path
) -> None:
    chunks_file = _write_chunks(artifact_dir)
    with patch(
        "src.processors.graph_creator.requests.get",
        side_effect=requests.exceptions.ConnectionError(),
    ), patch("src.processors.graph_creator.requests.post") as post:
        assert creator.process_chunks_file(chunks_file) == 0

    manifest = json.loads((artifact_dir / ".kg_progress.json").read_text())
    document = manifest["documents"]["sample_chunks"]
    assert document["processed_chunks"] == []
    assert document["complete"] is False
    post.assert_not_called()


def test_legacy_and_fingerprint_changes_purge_before_rebuild(
    creator: GraphCreator, artifact_dir: Path
) -> None:
    chunks_file = _write_chunks(artifact_dir)
    (artifact_dir / ".kg_progress.json").write_text(
        json.dumps({"sample_chunks": [0]}), encoding="utf-8"
    )
    creator.extract_triplets = MagicMock(return_value=[])
    creator.write_triplets = MagicMock(return_value=0)
    creator.purge_source = MagicMock(return_value=0)

    assert creator.process_chunks_file(chunks_file) == 0
    manifest = json.loads((artifact_dir / ".kg_progress.json").read_text())
    document = manifest["documents"]["sample_chunks"]
    assert manifest["version"] == 2
    assert document["processed_chunks"] == [0]
    assert document["zero_triplet_chunks"] == [0]
    creator.purge_source.assert_called_once_with("sample_chunks", "literature")

    _write_chunks(artifact_dir, "Changed clinical relation content.")
    assert creator.process_chunks_file(chunks_file) == 0
    assert creator.purge_source.call_count == 2
    assert creator.extract_triplets.call_count == 2


def test_relationships_are_source_scoped_and_purge_preserves_entities(
    creator: GraphCreator,
) -> None:
    assert creator.write_triplets(
        [
            {
                "head": "Metformin",
                "relation": "TREATS",
                "tail": "Diabetes",
                "tier": 1,
            }
        ],
        "paper_a_chunks",
        4,
        byte_start=10,
        byte_end=20,
        scope="patient_context",
    ) == 1
    write_query, write_params = creator._driver.session_instance.calls[-1]
    assert "source: $source, chunk_id: $chunk_id, scope: $scope" in write_query
    assert write_params["source"] == "paper_a_chunks"
    assert write_params["scope"] == "patient_context"
    assert write_params["byte_start"] == 10
    assert write_params["tier"] == 1

    assert creator.purge_source("paper_a_chunks", "patient_context") == 2
    purge_query, purge_params = creator._driver.session_instance.calls[-1]
    assert "DELETE r" in purge_query
    assert "DELETE n" not in purge_query
    assert purge_params == {"source": "paper_a_chunks", "scope": "patient_context"}


def test_counts_are_returned_by_file_directory_and_builder(
    creator: GraphCreator, artifact_dir: Path, config: dict
) -> None:
    chunks_file = _write_chunks(artifact_dir)
    creator.extract_triplets = MagicMock(
        return_value=[
            {"head": "A", "relation": "TREATS", "tail": "B", "tier": 2},
            {"head": "A", "relation": "REDUCES", "tail": "C", "tier": 1},
        ]
    )
    creator.write_triplets = MagicMock(return_value=2)
    creator.purge_source = MagicMock(return_value=0)
    assert creator.process_chunks_file(chunks_file, force=True) == 2

    with patch(
        "scripts.build_knowledge_graph.GraphCreator"
    ) as creator_class:
        wrapped_creator = creator_class.return_value
        wrapped_creator.process_chunks_dir.return_value = 7
        builder = KnowledgeGraphBuilder(config)
        assert builder.run(artifact_dir, scope="patient_context", force=True) == 7
        wrapped_creator.process_chunks_dir.assert_called_once_with(
            artifact_dir, scope="patient_context", force=True
        )
