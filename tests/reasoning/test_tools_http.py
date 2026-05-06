"""
HTTP tool tests — OpenFDATool, ClinicalTrialsTool, PubMedTool — with fully
mocked requests.Session.get.  No real network calls are made.
"""

import pytest
import requests
from unittest.mock import MagicMock, patch, call

from src.tools.implementations.openfda import OpenFDATool
from src.tools.implementations.clinicaltrials import ClinicalTrialsTool
from src.tools.implementations.pubmed import PubMedTool


# ---------------------------------------------------------------------------
# Minimal config mirrors (match config/app.yaml structure)
# ---------------------------------------------------------------------------

FDA_CONFIG = {
    "base_url": "https://api.fda.gov",
    "endpoint": "/drug/event.json",
    "search_param": "patient.drug.medicinalproduct",
    "limit": 2,
    "timeout": 5,
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
    "limit": 2,
    "timeout": 5,
    "response": {
        "results_key": "studies",
        "summary_max_length": 100,
        "fields": {
            "nct_id": ["protocolSection", "identificationModule", "nctId"],
            "title": ["protocolSection", "identificationModule", "briefTitle"],
            "status": ["protocolSection", "statusModule", "overallStatus"],
            "sponsor": [
                "protocolSection",
                "sponsorCollaboratorsModule",
                "leadSponsor",
                "leadSponsorName",
            ],
            "summary": ["protocolSection", "descriptionModule", "briefSummary"],
        },
    },
}

PUBMED_CONFIG = {
    "base_url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
    "search_endpoint": "/esearch.fcgi",
    "summary_endpoint": "/esummary.fcgi",
    "database": "pubmed",
    "limit": 2,
    "timeout": 5,
    "response": {
        "id_path": ["esearchresult", "idlist"],
        "summary_results_key": "result",
        "url_template": "https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "fields": {
            "title": "title",
            "journal": "source",
            "pub_date": "pubdate",
            "authors_field": "authors",
            "author_name_field": "name",
            "max_authors": 2,
        },
    },
}


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    r.raise_for_status.return_value = None
    return r


def _error_response() -> MagicMock:
    r = MagicMock()
    r.raise_for_status.side_effect = requests.exceptions.HTTPError("404")
    return r


# ---------------------------------------------------------------------------
# OpenFDA Tool
# ---------------------------------------------------------------------------

class TestOpenFDATool:
    def setup_method(self) -> None:
        self.tool = OpenFDATool(FDA_CONFIG)

    def test_empty_input_returns_error_string(self) -> None:
        result = self.tool.execute("")
        assert isinstance(result, str) and "Error" in result

    def test_dict_input_with_empty_drug_returns_error(self) -> None:
        result = self.tool.execute({"drug": ""})
        assert "Error" in result

    def test_question_framing_stripped_before_http_call(self) -> None:
        with patch.object(self.tool.session, "get") as mock_get:
            mock_get.return_value = _mock_response(
                {"meta": {"results": {"total": 0}}, "results": []}
            )
            self.tool.execute("What are the side effects of aspirin?")
            url, kwargs = mock_get.call_args[0][0], mock_get.call_args[1]
            params_str = str(mock_get.call_args)
            assert "aspirin" in params_str
            assert "What are the side effects" not in params_str

    @patch("requests.Session.get")
    def test_successful_response_parsed_correctly(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response({
            "meta": {"results": {"total": 3}},
            "results": [{
                "safetyreportid": "ABC123",
                "serious": 1,
                "occurcountry": "US",
                "patient": {
                    "patientsex": "1",
                    "reaction": [{"reactionmeddrapt": "Nausea"}],
                    "drug": [{"medicinalproduct": "ASPIRIN"}],
                },
            }],
        })
        result = self.tool.execute("aspirin")
        assert result["total_reports"] == 3
        assert len(result["results"]) == 1
        report = result["results"][0]
        assert report["country"] == "US"
        assert report["sex"] == "Male"
        assert "Nausea" in report["reactions"]
        assert "ASPIRIN" in report["drugs"]

    @pytest.mark.parametrize("sex_code, label", [
        ("1", "Male"), ("2", "Female"), ("0", "Unknown")
    ])
    @patch("requests.Session.get")
    def test_sex_codes_mapped_correctly(
        self, mock_get: MagicMock, sex_code: str, label: str
    ) -> None:
        mock_get.return_value = _mock_response({
            "meta": {"results": {"total": 1}},
            "results": [{
                "safetyreportid": "X",
                "serious": 1,
                "occurcountry": "DE",
                "patient": {"patientsex": sex_code, "reaction": [], "drug": []},
            }],
        })
        result = self.tool.execute("drug")
        assert result["results"][0]["sex"] == label

    @patch("requests.Session.get")
    def test_empty_results_returns_zero_total(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response(
            {"meta": {"results": {"total": 0}}, "results": []}
        )
        result = self.tool.execute("unknowndrugxyz")
        assert result["total_reports"] == 0
        assert result["results"] == []

    @patch("requests.Session.get")
    def test_connection_error_returns_error_string(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.exceptions.ConnectionError("timeout")
        result = self.tool.execute("aspirin")
        assert isinstance(result, str) and "Error" in result

    @patch("requests.Session.get")
    def test_timeout_returns_error_string(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.exceptions.Timeout("timed out")
        result = self.tool.execute("aspirin")
        assert "Error" in result


# ---------------------------------------------------------------------------
# ClinicalTrials Tool
# ---------------------------------------------------------------------------

class TestClinicalTrialsTool:
    def setup_method(self) -> None:
        self.tool = ClinicalTrialsTool(CT_CONFIG)

    def test_empty_input_returns_error(self) -> None:
        result = self.tool.execute("")
        assert "Error" in result

    @patch("requests.Session.get")
    def test_successful_response_parsed(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response({
            "studies": [{
                "protocolSection": {
                    "identificationModule": {
                        "nctId": "NCT12345678",
                        "briefTitle": "Semaglutide in Type 2 Diabetes",
                    },
                    "statusModule": {"overallStatus": "RECRUITING"},
                    "sponsorCollaboratorsModule": {
                        "leadSponsor": {"leadSponsorName": "Novo Nordisk"}
                    },
                    "descriptionModule": {
                        "briefSummary": "A " * 200  # > 100 chars — gets truncated
                    },
                }
            }]
        })
        result = self.tool.execute("diabetes")
        assert len(result) == 1
        study = result[0]
        assert study["nct_id"] == "NCT12345678"
        assert study["status"] == "RECRUITING"
        assert study["sponsor"] == "Novo Nordisk"
        assert len(study["summary"]) <= 100

    @patch("requests.Session.get")
    def test_empty_studies_returns_empty_list(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response({"studies": []})
        assert self.tool.execute("rare_condition_xyz") == []

    @patch("requests.Session.get")
    def test_network_error_returns_error_string(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.exceptions.ConnectionError("unreachable")
        result = self.tool.execute("diabetes")
        assert "Error" in result

    @patch("requests.Session.get")
    def test_multiple_studies_all_returned(self, mock_get: MagicMock) -> None:
        def _study(nct: str) -> dict:
            return {
                "protocolSection": {
                    "identificationModule": {"nctId": nct, "briefTitle": f"Trial {nct}"},
                    "statusModule": {"overallStatus": "COMPLETED"},
                    "sponsorCollaboratorsModule": {"leadSponsor": {"leadSponsorName": "Sponsor"}},
                    "descriptionModule": {"briefSummary": "Short."},
                }
            }

        mock_get.return_value = _mock_response({"studies": [_study("NCT001"), _study("NCT002")]})
        result = self.tool.execute("cancer")
        assert len(result) == 2
        assert {r["nct_id"] for r in result} == {"NCT001", "NCT002"}


# ---------------------------------------------------------------------------
# PubMed Tool
# ---------------------------------------------------------------------------

class TestPubMedTool:
    def setup_method(self) -> None:
        self.tool = PubMedTool(PUBMED_CONFIG)

    def test_empty_query_returns_error(self) -> None:
        result = self.tool.execute("")
        assert "Error" in result

    @patch("requests.Session.get")
    def test_no_ids_found_returns_no_results_message(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_response({"esearchresult": {"idlist": []}})
        result = self.tool.execute("very_obscure_query_xyz_123")
        assert result == "No results found."

    @patch("requests.Session.get")
    def test_two_step_request_parsed_correctly(self, mock_get: MagicMock) -> None:
        search_resp = _mock_response({"esearchresult": {"idlist": ["12345", "67890"]}})
        summary_resp = _mock_response({
            "result": {
                "12345": {
                    "title": "Aspirin in Cardiovascular Prevention",
                    "source": "NEJM",
                    "pubdate": "2024",
                    "authors": [{"name": "Smith J"}, {"name": "Jones A"}, {"name": "Brown K"}],
                },
                "67890": {
                    "title": "Aspirin Safety Profile",
                    "source": "Lancet",
                    "pubdate": "2023",
                    "authors": [{"name": "Wang X"}],
                },
            }
        })
        mock_get.side_effect = [search_resp, summary_resp]
        result = self.tool.execute("aspirin")
        assert len(result) == 2

        first = result[0]
        assert first["pmid"] == "12345"
        assert first["title"] == "Aspirin in Cardiovascular Prevention"
        assert first["journal"] == "NEJM"
        assert first["url"] == "https://pubmed.ncbi.nlm.nih.gov/12345/"
        assert len(first["authors"]) <= PUBMED_CONFIG["response"]["fields"]["max_authors"]

    @patch("requests.Session.get")
    def test_authors_truncated_to_max_authors(self, mock_get: MagicMock) -> None:
        max_authors = PUBMED_CONFIG["response"]["fields"]["max_authors"]  # 2
        search_resp = _mock_response({"esearchresult": {"idlist": ["111"]}})
        summary_resp = _mock_response({
            "result": {
                "111": {
                    "title": "Study",
                    "source": "BMJ",
                    "pubdate": "2024",
                    "authors": [{"name": f"Author{i}"} for i in range(10)],
                }
            }
        })
        mock_get.side_effect = [search_resp, summary_resp]
        result = self.tool.execute("study")
        assert len(result[0]["authors"]) <= max_authors

    @patch("requests.Session.get")
    def test_network_error_returns_error_string(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.exceptions.ConnectionError("unreachable")
        result = self.tool.execute("aspirin")
        assert "Error" in result

    @patch("requests.Session.get")
    def test_url_template_applied_per_pmid(self, mock_get: MagicMock) -> None:
        search_resp = _mock_response({"esearchresult": {"idlist": ["999"]}})
        summary_resp = _mock_response({
            "result": {
                "999": {
                    "title": "T", "source": "J", "pubdate": "2024", "authors": []
                }
            }
        })
        mock_get.side_effect = [search_resp, summary_resp]
        result = self.tool.execute("topic")
        assert result[0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/999/"
