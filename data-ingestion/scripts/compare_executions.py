#!/usr/bin/env python3
"""
Compare two pipeline executions for determinism verification.

Usage:
  python scripts/compare_executions.py --doc <uuid> --exec1 <uuid> --exec2 <uuid>
  python scripts/compare_executions.py --doc <uuid> --exec1 <uuid> --exec2 <uuid> --version-check
  python scripts/compare_executions.py --doc <uuid> --exec1 <uuid> --exec2 <uuid> --stage-diff convert
  python scripts/compare_executions.py list-documents
  python scripts/compare_executions.py list-executions --doc <uuid>
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.determinism import DeterminismTracker


def cmd_list_documents():
    tracker = DeterminismTracker()
    docs = tracker.list_documents()
    print("\nTRACKED DOCUMENTS:")
    print("─" * 52)
    print(f"{'Document ID':<40}  Filename")
    print("─" * 52)
    for doc_uuid, filename, _ in docs:
        print(f"{doc_uuid}  {filename}")
    print()


def cmd_list_executions(doc_uuid: str):
    tracker = DeterminismTracker()
    execs = tracker.list_executions(doc_uuid)
    print(f"\nEXECUTIONS FOR DOCUMENT: {doc_uuid}")
    print("─" * 74)
    print(f"{'Execution ID':<40}  {'Timestamp':<25}  Status")
    print("─" * 74)
    for exec_uuid, started_at, status in execs:
        print(f"{exec_uuid}  {started_at:<25}  {status}")
    print()


def cmd_compare(
    doc_uuid: str,
    exec1: str,
    exec2: str,
    version_check: bool = False,
    stage_diff: str = None,
) -> bool:
    tracker = DeterminismTracker()

    records1 = {r[0]: r for r in tracker.get_stage_records(exec1)}
    records2 = {r[0]: r for r in tracker.get_stage_records(exec2)}
    all_stages = sorted(set(records1) | set(records2))

    matched = 0
    total = len(all_stages)

    print("\nCOMPARING EXECUTIONS")
    print("─" * 72)
    print(f"  Exec 1: {exec1}")
    print(f"  Exec 2: {exec2}")
    print("─" * 72)

    for stage in all_stages:
        if stage not in records1:
            print(f"  {stage:<15} MISSING in exec1")
            continue
        if stage not in records2:
            print(f"  {stage:<15} MISSING in exec2")
            continue

        hash1 = records1[stage][1]
        hash2 = records2[stage][1]

        if hash1 == hash2:
            print(f"  {stage:<15} ✓ MATCH  ({hash1[:12]}...)")
            matched += 1
        else:
            print(f"  {stage:<15} ✗ DIFFER")
            print(f"    exec1: {hash1}")
            print(f"    exec2: {hash2}")

            if stage_diff and stage_diff == stage:
                fp1 = json.loads(records1[stage][2])
                fp2 = json.loads(records2[stage][2])
                print(f"\n  Stage fingerprint diff for '{stage}':")
                for key in sorted(set(fp1) | set(fp2)):
                    v1 = fp1.get(key, "<missing>")
                    v2 = fp2.get(key, "<missing>")
                    if v1 != v2:
                        print(f"    {key}:")
                        print(f"      exec1: {v1}")
                        print(f"      exec2: {v2}")

    print("─" * 72)
    print(f"  Result: {matched}/{total} stages matched")

    if version_check:
        env1 = tracker.get_environment(exec1)
        env2 = tracker.get_environment(exec2)
        drift_keys = [
            "python_version", "pip_freeze_hash", "os",
            "git_sha", "cuda_available", "mps_available",
        ]
        print("\nVERSION CHECK")
        print("─" * 72)
        has_drift = False
        for key in drift_keys:
            v1 = env1.get(key, "<missing>")
            v2 = env2.get(key, "<missing>")
            if v1 != v2:
                print(f"  ✗ {key}:")
                print(f"      exec1: {v1}")
                print(f"      exec2: {v2}")
                has_drift = True
        if not has_drift:
            print("  ✓ No environment drift detected")

    print()
    return matched == total


def main():
    parser = argparse.ArgumentParser(
        description="Compare pipeline executions for determinism verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list-documents", help="List all tracked documents")

    le = subparsers.add_parser("list-executions", help="List executions for a document")
    le.add_argument("--doc", required=True, metavar="UUID", help="Document UUID")

    # Default mode: compare two executions
    parser.add_argument("--doc", metavar="UUID", help="Document UUID")
    parser.add_argument("--exec1", metavar="UUID", help="First execution UUID")
    parser.add_argument("--exec2", metavar="UUID", help="Second execution UUID")
    parser.add_argument("--version-check", action="store_true",
                        help="Check for environment/dependency drift between executions")
    parser.add_argument("--stage-diff", metavar="STAGE",
                        help="Show fingerprint diff for a specific stage on mismatch")

    args = parser.parse_args()

    if args.command == "list-documents":
        cmd_list_documents()
    elif args.command == "list-executions":
        cmd_list_executions(args.doc)
    elif args.doc and args.exec1 and args.exec2:
        success = cmd_compare(
            args.doc, args.exec1, args.exec2,
            version_check=args.version_check,
            stage_diff=args.stage_diff,
        )
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
