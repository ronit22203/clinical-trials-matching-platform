import re
import requests
from typing import Any
from ..base import BaseTool
from .openfda import _extract_drug_name


def _get_nested(obj: dict, path: list, default=None):
    """Walk a nested dict using a list of keys."""
    for key in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key, default)
    return obj


class ClinicalTrialsTool(BaseTool):
    def execute(self, input: Any) -> Any:
        raw = input if isinstance(input, str) else input.get("condition", "")
        if not raw:
            return "Error: No condition provided."
        condition = _extract_drug_name(raw)  # shared sanitizer strips question prefixes
        if not condition:
            condition = raw  # fallback to raw if extraction produces empty string

        cfg = self.config
        resp_cfg = cfg.get("response", {})
        fields = resp_cfg.get("fields", {})

        url = cfg["base_url"].rstrip("/") + cfg["endpoint"]
        params = {
            cfg.get("search_param", "query.cond"): condition,
            cfg.get("page_size_param", "pageSize"): cfg.get("limit", 5),
        }
        if cfg.get("status"):
            params[cfg.get("status_filter_param", "filter.overallStatus")] = cfg["status"]

        try:
            response = self.session.get(url, params=params, timeout=cfg.get("timeout", 10))
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            return f"Error fetching ClinicalTrials data: {e}"

        data = response.json()
        summary_max = resp_cfg.get("summary_max_length", 300)
        studies = []
        for study in data.get(resp_cfg.get("results_key", "studies"), []):
            summary_raw = _get_nested(study, fields.get("summary", ["protocolSection", "descriptionModule", "briefSummary"]), "") or ""
            studies.append({
                "nct_id": _get_nested(study, fields.get("nct_id", ["protocolSection", "identificationModule", "nctId"])),
                "title": _get_nested(study, fields.get("title", ["protocolSection", "identificationModule", "briefTitle"])),
                "status": _get_nested(study, fields.get("status", ["protocolSection", "statusModule", "overallStatus"])),
                "sponsor": _get_nested(study, fields.get("sponsor", ["protocolSection", "sponsorCollaboratorsModule", "leadSponsor", "leadSponsorName"])),
                "summary": summary_raw[:summary_max],
            })
        return studies
