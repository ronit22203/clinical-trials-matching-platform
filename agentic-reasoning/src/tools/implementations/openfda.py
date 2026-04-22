import os
import re
import requests
from typing import Any
from ..base import BaseTool


def _get_nested(obj: dict, path: list, default=None):
    """Walk a nested dict using a list of keys."""
    for key in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key, default)
    return obj


def _extract_drug_name(text: str) -> str:
    """
    Extract a clean drug name from a natural-language query.

    Strips question marks, common clinical question prefixes, and
    trailing noise so the FDA API receives a bare compound name.
    """
    text = re.sub(r"[?!]", "", text).strip()
    prefixes = [
        r"^(?:what are the\s+)?(?:side effects?|adverse events?|safety profile|"
        r"contraindications?|drug interactions?)\s+(?:of|for|with|to)\s+",
        r"^(?:tell me about|what is|describe|list|summarise|summarize)\s+(?:the\s+)?",
        r"^(?:the\s+)?(?:latest|recent|new|known)\s+",
        r"^i['\u2019]?m (?:researching|looking at|studying)\s+",
        r"\s*\.\s*$",
    ]
    for pattern in prefixes:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    # Take only the first meaningful token group (before a comma or " and ")
    text = re.split(r",| and | or ", text, maxsplit=1)[0]
    return text.strip()


class OpenFDATool(BaseTool):
    def execute(self, input: Any) -> Any:
        raw = input if isinstance(input, str) else input.get("drug", "")
        if not raw:
            return "Error: No drug name provided."
        drug = _extract_drug_name(raw)
        if not drug:
            return "Error: Could not extract a drug name from the input."

        cfg = self.config
        resp_cfg = cfg.get("response", {})
        fields = resp_cfg.get("fields", {})

        url = cfg["base_url"].rstrip("/") + cfg["endpoint"]
        search_param = cfg.get("search_param", "patient.drug.medicinalproduct")
        params = {
            "search": f'{search_param}:"{drug}"',
            "limit": cfg.get("limit", 5),
        }
        if cfg.get("api_key"):
            params["api_key"] = cfg["api_key"]
        elif os.getenv("OPENFDA_API_KEY"):
            params["api_key"] = os.getenv("OPENFDA_API_KEY")

        try:
            response = self.session.get(url, params=params, timeout=cfg.get("timeout", 10))
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            return f"Error fetching FDA data: {e}"

        data = response.json()
        sex_map = {"1": "Male", "2": "Female", "0": "Unknown"}
        results = []
        for report in data.get(resp_cfg.get("results_key", "results"), []):
            patient = report.get("patient", {})
            results.append({
                "safety_report_id": report.get(fields.get("safety_report_id", "safetyreportid")),
                "serious": report.get(fields.get("serious", "serious")),
                "country": report.get(fields.get("country", "occurcountry")),
                "sex": sex_map.get(str(patient.get("patientsex", "0")), "Unknown"),
                "reactions": [r.get(fields.get("reactions", ["patient", "reaction", "reactionmeddrapt"])[-1])
                               for r in patient.get("reaction", [])],
                "drugs": [d.get(fields.get("drugs", ["patient", "drug", "medicinalproduct"])[-1])
                          for d in patient.get("drug", [])],
            })

        total_path = resp_cfg.get("total_path", ["meta", "results", "total"])
        total = _get_nested(data, total_path, 0)
        return {"total_reports": total, "results": results}
