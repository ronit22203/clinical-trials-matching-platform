import requests
from typing import Any
from ..base import BaseTool


class PubMedTool(BaseTool):
    def execute(self, input: Any) -> Any:
        query = input if isinstance(input, str) else input.get("query", "")
        if not query:
            return "Error: No search query provided."

        cfg = self.config
        resp_cfg = cfg.get("response", {})
        fields = resp_cfg.get("fields", {})

        base_url = cfg["base_url"].rstrip("/")
        db = cfg.get("database", "pubmed")
        api_key = cfg.get("api_key", "")

        search_params = {
            "db": db,
            "term": query,
            "retmax": cfg.get("limit", 5),
            "retmode": "json",
        }
        if api_key:
            search_params["api_key"] = api_key

        try:
            search_resp = self.session.get(
                base_url + cfg.get("search_endpoint", "/esearch.fcgi"),
                params=search_params,
                timeout=cfg.get("timeout", 10),
            )
            search_resp.raise_for_status()
            ids = search_resp.json()
            for key in resp_cfg.get("id_path", ["esearchresult", "idlist"]):
                ids = ids.get(key, []) if isinstance(ids, dict) else []
            if not ids:
                return "No results found."

            summary_params = {"db": db, "id": ",".join(ids), "retmode": "json"}
            if api_key:
                summary_params["api_key"] = api_key
            summary_resp = self.session.get(
                base_url + cfg.get("summary_endpoint", "/esummary.fcgi"),
                params=summary_params,
                timeout=cfg.get("timeout", 10),
            )
            summary_resp.raise_for_status()
            summaries = summary_resp.json().get(resp_cfg.get("summary_results_key", "result"), {})
        except requests.exceptions.RequestException as e:
            return f"Error fetching PubMed data: {e}"

        url_template = resp_cfg.get("url_template", "https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
        max_authors = fields.get("max_authors", 3)
        articles = []
        for pmid in ids:
            article = summaries.get(pmid, {})
            articles.append({
                "pmid": pmid,
                "title": article.get(fields.get("title", "title")),
                "authors": [a.get(fields.get("author_name_field", "name"))
                            for a in article.get(fields.get("authors_field", "authors"), [])[:max_authors]],
                "journal": article.get(fields.get("journal", "source")),
                "pub_date": article.get(fields.get("pub_date", "pubdate")),
                "url": url_template.format(pmid=pmid),
            })
        return articles
