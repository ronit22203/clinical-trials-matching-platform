import json
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any

# --- Mappings for FDA Codes (Cleaning Logic) ---
SEX_CODE = {"1": "Male", "2": "Female", "0": "Unknown"}
DRUG_ROLE = {
    "1": "Suspect",
    "2": "Concomitant",
    "3": "Interacting",
    "0": "Unknown"
}
SERIOUSNESS = {
    "1": "Yes",
    "2": "No"
}

def clean_drug_entry(drug: Dict[str, Any]) -> Dict[str, str]:
    """Extracts semantic value from a drug entry, discarding administrative noise."""
    characterization = drug.get("drugcharacterization", "0")
    role = DRUG_ROLE.get(characterization, f"Role-{characterization}")
    
    return {
        "name": drug.get("medicinalproduct", "Unknown Drug"),
        "role": role,
        "indication": drug.get("drugindication", "Unknown Indication"),
        "dosage": drug.get("drugdosagetext", drug.get("drugstructuredosagenumb", "N/A"))
    }

def normalize_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Flattens a single safety report into an LLM-optimized context object."""
    
    # 1. Demographics
    patient = report.get("patient", {})
    age = patient.get("patientonsetage", "Unknown")
    sex_code = patient.get("patientsex", "0")
    sex = SEX_CODE.get(sex_code, "Unknown")
    
    # 2. Reactions (Flatten list of objects to list of strings)
    reactions = []
    if "reaction" in patient:
        # Handle both list and single dict edge cases in raw JSON
        raw_reactions = patient["reaction"]
        if isinstance(raw_reactions, dict): raw_reactions = [raw_reactions]
        
        for r in raw_reactions:
            term = r.get("reactionmeddrapt")
            if term:
                reactions.append(term)

    # 3. Drugs (Select fields only)
    drugs = []
    if "drug" in patient:
        raw_drugs = patient["drug"]
        if isinstance(raw_drugs, dict): raw_drugs = [raw_drugs]
        
        for d in raw_drugs:
            drugs.append(clean_drug_entry(d))

    # 4. Construct Clean Object
    return {
        "id": report.get("safetyreportid"),
        "date": report.get("receivedate"),
        "serious": SERIOUSNESS.get(report.get("serious"), "Unknown"),
        "patient": {
            "age": age,
            "sex": sex,
            "weight_kg": patient.get("patientweight", "N/A")
        },
        "drugs": drugs,
        "reactions": reactions,
        "summary": report.get("summary", {}).get("narrativeincludeclinical", "No narrative provided")
    }

def process_file(input_path_str: str):
    input_path = Path(input_path_str).resolve()
    
    if not input_path.exists():
        print(f"[ERROR] File not found: {input_path}")
        sys.exit(1)

    print(f"--- Processing: {input_path.name} ---")

    # 1. Setup Output Directory
    output_dir = input_path.parent / "processed"
    output_dir.mkdir(exist_ok=True)
    
    # 2. Load Raw Data
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON: {e}")
        sys.exit(1)

    # Handle if 'results' key exists or if it's a raw list
    results = data.get("results", data) if isinstance(data, dict) else data
    if not isinstance(results, list):
        # Fallback for single object
        results = [results]

    normalized_data = []
    redundant_archive = {}

    # 3. Processing Loop
    for report in results:
        r_id = report.get("safetyreportid")
        
        if not r_id:
            continue # Skip malformed records without IDs

        # A. Create Normalized Entry
        clean_entry = normalize_report(report)
        normalized_data.append(clean_entry)

        # B. Archive Full Entry (Redundant Data)
        redundant_archive[r_id] = report

    # 4. Write Outputs
    norm_filename = f"normalized_{input_path.stem}.json"
    arch_filename = f"redundant_{input_path.stem}_map.json"

    norm_path = output_dir / norm_filename
    arch_path = output_dir / arch_filename

    print(f"Writing {len(normalized_data)} records to normalized output...")
    with open(norm_path, 'w', encoding='utf-8') as f:
        json.dump(normalized_data, f, indent=2)

    print(f"Archiving raw data maps...")
    with open(arch_path, 'w', encoding='utf-8') as f:
        json.dump(redundant_archive, f, indent=2)

    print(f"\n[SUCCESS] Processing Complete.")
    print(f"1. LLM Context:   {norm_path}")
    print(f"2. Raw Archive:   {arch_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Normalize FDA JSON data for LLM context injection.")
    parser.add_argument("input_file", help="Path to the source .json file")
    
    args = parser.parse_args()
    process_file(args.input_file)