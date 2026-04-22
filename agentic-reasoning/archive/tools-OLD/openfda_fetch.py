#!/usr/bin/env python3
"""
openFDA Drug Adverse Event Lookup Tool
Usage: python fda_drug_events.py "DRUG NAME" [--limit N]
"""

import requests
import argparse
import json
import os

def save_json(data, filename):
    os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

def fetch_adverse_events(drug_name, limit=5):
    url = "https://api.fda.gov/drug/event.json"
    params = {
        "search": f'patient.drug.medicinalproduct:"{drug_name}"',
        "limit": limit
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return None

def display_reports(data):
    if not data or 'results' not in data:
        print("No results found.")
        return

    total = data.get('meta', {}).get('results', {}).get('total', 0)
    print(f"\nFound {total} total reports. Showing first {len(data['results'])}:\n")
    
    for i, report in enumerate(data['results'], 1):
        print(f"--- Report #{i} ---")
        patient = report.get('patient', {})
        
        # Age
        if 'patientonsetage' in patient:
            age = patient['patientonsetage']
            age_unit = patient.get('patientonsetageunit', '')
            print(f"Age: {age} {age_unit}")
        # Sex
        sex_map = {'1': 'Male', '2': 'Female', '0': 'Unknown'}
        sex_code = str(patient.get('patientsex', '0'))
        print(f"Sex: {sex_map.get(sex_code, 'Unknown')}")
        
        # Drugs
        drugs = patient.get('drug', [])
        drug_info = []
        for d in drugs:
            name = d.get('medicinalproduct', 'Unknown')
            role_map = {'1': 'Suspect', '2': 'Concomitant', '3': 'Interacting'}
            role_code = str(d.get('drugcharacterization', ''))
            role = role_map.get(role_code, 'Unknown')
            drug_info.append(f"{name} ({role})")
        print(f"Drug(s): {', '.join(drug_info)}")
        
        # Reactions
        reactions = patient.get('reaction', [])
        reaction_list = [r.get('reactionmeddrapt', 'Unknown') for r in reactions]
        print(f"Reaction(s): {', '.join(reaction_list)}")
        
        # Report metadata
        print(f"Reported in: {report.get('occurcountry', 'Unknown')}")
        if 'receivedate' in report:
            print(f"Received date: {report['receivedate']}")
        print()

def main():
    parser = argparse.ArgumentParser(description="Fetch adverse event reports from openFDA")
    parser.add_argument("drug", help="Name of the drug (e.g., 'Aspirin')")
    parser.add_argument("--limit", type=int, default=5, help="Number of reports to fetch (default: 5)")
    parser.add_argument("--output", help="Output file name")
    parser.add_argument("--format", choices=['json', 'csv', 'text'], default='text', help="Output format (default: text)")
    args = parser.parse_args()
    
    data = fetch_adverse_events(args.drug, args.limit)
    if data:
        if args.format == 'json' and args.output:
            save_json(data, args.output)
        else:
            display_reports(data)

if __name__ == "__main__":
    main()