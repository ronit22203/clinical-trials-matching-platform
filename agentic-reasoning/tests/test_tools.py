"""Tests for tool implementations (API calls are mocked)."""
from unittest.mock import MagicMock, patch
import pytest

from src.tools.implementations.openfda import OpenFDATool
from src.tools.implementations.clinicaltrials import ClinicalTrialsTool
from src.tools.implementations.pubmed import PubMedTool
from src.tools.implementations.graphrag_tools import GraphRAGTool, _extract_keywords

# ---------------------------------------------------------------------------
# Shared tool configs (mirrors config/app.yaml → agentic_reasoning.tools)
# ---------------------------------------------------------------------------

FDA_CONFIG = {
    "base_url": "https://api.fda.gov",
    "endpoint": "/drug/event.json",
    "search_param": "patient.drug.medicinalproduct",
    "limit": 2,
    "timeout": 10,
    "response": {
        "results_key": "results",
        "total_path": ["meta", "results", "total"],
        "fields": {
            "safety_report_id": "safetyreportid",
            "serious": "serious",
            "country": "occurcountry",
            "reactions": ["patient", "reaction", "reactionmeddrapt"],
            "drugs": ["patient", "drug", "medicinalproduct"],
        },
    },
}

CT_CONFIG = {
    "base_url": "https://clinicaltrials.gov",
    "endpoint": "/api/v2/studies",
    "search_param": "query.cond",
    "page_size_param": "pageSize",
    "status_filter_param": "filter.overallStatus",
    "limit": 2,
    "timeout": 10,
    "response": {
        "results_key": "studies",
        "fields": {
            "nct_id": ["protocolSection", "identificationModule", "nctId"],
            "title": ["protocolSection", "identificationModule", "briefTitle"],
            "status": ["protocolSection", "statusModule", "overallStatus"],
            "sponsor": ["protocolSection", "sponsorCollaboratorsModule", "leadSponsor", "leadSponsorName"],
            "summary": ["protocolSection", "descriptionModule", "briefSummary"],
        },
        "summary_max_length": 100,
    },
}

PUBMED_CONFIG = {
    "base_url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
    "search_endpoint": "/esearch.fcgi",
    "summary_endpoint": "/esummary.fcgi",
    "database": "pubmed",
    "limit": 2,
    "timeout": 10,
    "response": {
        "id_path": ["esearchresult", "idlist"],
        "summary_results_key": "result",
        "fields": {
            "title": "title",
            "journal": "source",
            "pub_date": "pubdate",
            "authors_field": "authors",
            "author_name_field": "name",
            "max_authors": 3,
        },
        "url_template": "https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    },
}


# ---------------------------------------------------------------------------
# OpenFDA Tool
# ---------------------------------------------------------------------------

class TestOpenFDATool:
    def setup_method(self):
        self.tool = OpenFDATool(FDA_CONFIG)

    def test_missing_drug_input(self):
        assert "Error" in self.tool.execute("")

    @patch("requests.Session.get")
    def test_successful_response(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "meta": {"results": {"total": 1}},
                "results": [{
                    "safetyreportid": "123",
                    "serious": 1,
                    "occurcountry": "US",
                    "patient": {
                        "patientsex": "1",
                        "reaction": [{"reactionmeddrapt": "Nausea"}],
                        "drug": [{"medicinalproduct": "Ibuprofen"}],
                    },
                }],
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        result = self.tool.execute("ibuprofen")
        assert result["total_reports"] == 1
        assert result["results"][0]["country"] == "US"
        assert "Nausea" in result["results"][0]["reactions"]

    @patch("requests.Session.get")
    def test_request_error_returns_message(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.RequestException("timeout")
        result = self.tool.execute("aspirin")
        assert "Error" in result


# ---------------------------------------------------------------------------
# ClinicalTrials Tool
# ---------------------------------------------------------------------------

class TestClinicalTrialsTool:
    def setup_method(self):
        self.tool = ClinicalTrialsTool(CT_CONFIG)

    def test_missing_condition_input(self):
        assert "Error" in self.tool.execute("")

    @patch("requests.Session.get")
    def test_successful_response(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "studies": [{
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT001", "briefTitle": "Diabetes Study"},
                        "statusModule": {"overallStatus": "RECRUITING"},
                        "sponsorCollaboratorsModule": {"leadSponsor": {"leadSponsorName": "NIH"}},
                        "descriptionModule": {"briefSummary": "A study on diabetes."},
                    }
                }]
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        result = self.tool.execute("diabetes")
        assert len(result) == 1
        assert result[0]["nct_id"] == "NCT001"
        assert result[0]["status"] == "RECRUITING"

    @patch("requests.Session.get")
    def test_request_error_returns_message(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.RequestException("timeout")
        result = self.tool.execute("cancer")
        assert "Error" in result


# ---------------------------------------------------------------------------
# PubMed Tool
# ---------------------------------------------------------------------------

class TestPubMedTool:
    def setup_method(self):
        self.tool = PubMedTool(PUBMED_CONFIG)

    def test_missing_query_input(self):
        assert "Error" in self.tool.execute("")

    @patch("requests.Session.get")
    def test_successful_response(self, mock_get):
        search_response = MagicMock(
            status_code=200,
            json=lambda: {"esearchresult": {"idlist": ["12345"]}},
        )
        search_response.raise_for_status = lambda: None

        summary_response = MagicMock(
            status_code=200,
            json=lambda: {
                "result": {
                    "12345": {
                        "title": "Metformin in diabetes",
                        "source": "NEJM",
                        "pubdate": "2023",
                        "authors": [{"name": "Smith J"}],
                    }
                }
            },
        )
        summary_response.raise_for_status = lambda: None

        mock_get.side_effect = [search_response, summary_response]
        result = self.tool.execute("metformin diabetes")
        assert len(result) == 1
        assert result[0]["pmid"] == "12345"
        assert result[0]["journal"] == "NEJM"
        assert result[0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/12345/"

    @patch("requests.Session.get")
    def test_no_results(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"esearchresult": {"idlist": []}},
        )
        mock_get.return_value.raise_for_status = lambda: None
        result = self.tool.execute("xyznonexistentdrug")
        assert result == "No results found."


# ---------------------------------------------------------------------------
# GraphRAG Tool
# ---------------------------------------------------------------------------

GRAPHRAG_CONFIG = {
    "qdrant_url": "http://localhost:6333",
    "collection": "medical_papers",
    "embedding_model": "BAAI/bge-small-en-v1.5",
    "model_cache_dir": "data/models",
    "neo4j_uri": "bolt://localhost:7687",
    "neo4j_username": "neo4j",
    "neo4j_password": "testpassword",
    "limit": 2,
    "neo4j_limit": 5,
}


class TestExtractKeywords:
    def test_filters_stop_words(self):
        keywords = _extract_keywords("what are the side effects of metformin")
        assert "what" not in keywords
        assert "the" not in keywords
        assert "metformin" in keywords

    def test_respects_max_keywords(self):
        query = "alpha beta gamma delta epsilon zeta eta"
        assert len(_extract_keywords(query, max_keywords=3)) <= 3

    def test_empty_query(self):
        assert _extract_keywords("") == []


class TestGraphRAGTool:
    def setup_method(self):
        self.tool = GraphRAGTool(GRAPHRAG_CONFIG)

    def test_empty_string_returns_error(self):
        result = self.tool.execute("")
        assert "Error" in result

    def test_empty_dict_query_returns_error(self):
        result = self.tool.execute({"query": "   "})
        assert "Error" in result

    def test_successful_hybrid_retrieval(self):
        result = self.tool.execute("aspirin headache treatment")
        assert isinstance(result, dict)
        assert result["query"] == "aspirin headache treatment"
        assert "vector_results" in result
        assert "graph_facts" in result
        assert "keywords" in result
        assert isinstance(result["vector_results"], list)
        assert isinstance(result["graph_facts"], list)

    def test_dict_input(self):
        result = self.tool.execute({"query": "insulin resistance"})
        assert isinstance(result, dict)
        assert result["query"] == "insulin resistance"
        assert "vector_results" in result

    # Error-path tests still use mocks to simulate infrastructure failures.
    @patch("src.tools.implementations.graphrag_tools.GraphRAGTool._qdrant_client")
    def test_vector_search_failure_returns_error(self, mock_qdrant):
        mock_qdrant.return_value.query_points.side_effect = RuntimeError("Qdrant unavailable")
        result = self.tool.execute("metformin")
        assert "Error" in result
        assert "Vector search failed" in result

    @patch("src.tools.implementations.graphrag_tools.GraphRAGTool._neo4j_driver")
    def test_neo4j_failure_returns_empty_graph_facts(self, mock_neo4j):
        mock_neo4j.return_value.session.side_effect = Exception("Neo4j down")
        result = self.tool.execute("diabetes")
        assert result["graph_facts"] == []
        assert isinstance(result["vector_results"], list)
