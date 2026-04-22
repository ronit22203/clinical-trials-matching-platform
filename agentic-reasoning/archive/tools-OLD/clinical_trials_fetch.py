
#!/usr/bin/env python3
"""
ClinicalTrials.gov API v2 CLI Fetch Tool
Usage: python clinical_trials_fetch.py "CONDITION" [--limit N] [--status STATUS]
"""
import argparse
import requests
import sys
import json
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')
try:
    from tool_calling_example import fetch_clinical_trials as agent_fetch_clinical_trials
except ImportError:
    agent_fetch_clinical_trials = None

def fetch_clinical_trials(condition, limit=5, status=None):
    url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.cond": condition,
        "pageSize": limit
    }
    if status:
        params["filter.overallStatus"] = status
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            print(json.dumps({"error": f"API returned status {response.status_code}"}), file=sys.stderr)
            sys.exit(1)
        data = response.json()
        return data
    except requests.exceptions.Timeout:
        print(json.dumps({"error": "Request timed out"}), file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

def extract_fields(studies):
    results = []
    for study in studies:
        entry = {
            "nctId": study.get("protocolSection", {}).get("identificationModule", {}).get("nctId"),
            "briefTitle": study.get("protocolSection", {}).get("identificationModule", {}).get("briefTitle"),
            "overallStatus": study.get("protocolSection", {}).get("statusModule", {}).get("overallStatus"),
            "leadSponsor": study.get("protocolSection", {}).get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("leadSponsorName"),
            "briefSummary": study.get("protocolSection", {}).get("descriptionModule", {}).get("briefSummary")
        }
        results.append(entry)
    return results

def main():
    parser = argparse.ArgumentParser(description="Fetch studies from ClinicalTrials.gov API v2")
    parser.add_argument("condition", help="Disease or condition to search for (maps to query.cond)")
    parser.add_argument("--limit", type=int, default=5, help="Number of results to return (default: 5)")
    parser.add_argument("--status", type=str, help="Recruitment status filter (e.g., RECRUITING)")
    parser.add_argument("--agent", action="store_true", help="Use agentic tool_calling_example for fetching trials")
    args = parser.parse_args()

    if args.agent:
        if agent_fetch_clinical_trials is None:
            print(json.dumps({"error": "Agentic fetch not available"}), file=sys.stderr)
            sys.exit(1)
        try:
            output = agent_fetch_clinical_trials(args.condition, args.limit, args.status)
            print(json.dumps(output, ensure_ascii=False, indent=None))
        except Exception as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)
    else:
        data = fetch_clinical_trials(args.condition, args.limit, args.status)
        studies = data.get("studies", [])
        output = extract_fields(studies)
        print(json.dumps(output, ensure_ascii=False, indent=None))

if __name__ == "__main__":
    main()
