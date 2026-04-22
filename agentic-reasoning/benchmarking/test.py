#!/usr/bin/env python
"""
Benchmarking test runner for Clinical Agents using golden.json dataset.
Tests agent against expected tool usage across 20 test cases.
"""

import json
import subprocess
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


def load_golden_dataset(filepath: str) -> dict:
    """Load the golden test suite from JSON."""
    with open(filepath) as f:
        return json.load(f)


REPO_ROOT = Path(__file__).parent.parent


def get_log_line_count(log_dir: str = "log") -> int:
    """Return the current number of lines in summary.jsonl (used as a before-snapshot)."""
    log_path = REPO_ROOT / log_dir / "summary.jsonl"
    if not log_path.exists():
        return 0
    with open(log_path) as f:
        return sum(1 for _ in f)


def get_new_log_tools(before_lines: int, log_dir: str = "log") -> Optional[list]:
    """Extract tools_called from the log entry written after before_lines."""
    log_path = REPO_ROOT / log_dir / "summary.jsonl"
    if not log_path.exists():
        return None
    
    try:
        with open(log_path) as f:
            lines = f.readlines()
        # Only consider lines added since before_lines
        new_lines = [l for l in lines[before_lines:] if l.strip()]
        if new_lines:
            log_data = json.loads(new_lines[-1])
            return log_data.get("tools_called", [])
    except (json.JSONDecodeError, IndexError):
        return None
    
    return None


def run_test_case(test: dict, agent_config: str = "assistant") -> dict:
    """Run a single test case and return results."""
    test_id = test["id"]
    test_name = test["name"]
    query = test["query"]
    expected_tools = set(test["expected_tools"])
    
    print(f"\n{'=' * 70}")
    print(f"Test {test_id}: {test_name}")
    print(f"Query: {query[:80]}{'...' if len(query) > 80 else ''}")
    print(f"Expected tools: {', '.join(sorted(expected_tools)) if expected_tools else 'none'}")
    print(f"{'=' * 70}")
    
    start_time = time.time()
    before_lines = get_log_line_count()
    
    try:
        # Run the CLI with the query
        result = subprocess.run(
            [
                "python", "-m", "src.cli",
                "--agent", agent_config,
                query
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=REPO_ROOT
        )
        latency_ms = (time.time() - start_time) * 1000
        
        # Extract tools called from the log entry written during this run
        tools_called = get_new_log_tools(before_lines) or []
        actual_tools = set(tools_called)
        
        # Determine success
        success = actual_tools == expected_tools
        
        result_entry = {
            "id": test_id,
            "name": test_name,
            "expected": sorted(list(expected_tools)),
            "actual": sorted(list(actual_tools)),
            "success": success,
            "latency_ms": latency_ms,
            "stderr": result.stderr[:500] if result.stderr else ""
        }
        
        if success:
            print(f"PASS - Tools called: {', '.join(sorted(actual_tools)) if actual_tools else 'none'}")
        else:
            print(f"FAIL")
            print(f"Expected: {', '.join(sorted(expected_tools)) if expected_tools else 'none'}")
            print(f"Got:      {', '.join(sorted(actual_tools)) if actual_tools else 'none'}")
            if result.stderr:
                print(f"   Error: {result.stderr[:200]}")
        
        print(f"Latency: {latency_ms:.0f} ms")
        
        return result_entry
        
    except subprocess.TimeoutExpired:
        latency_ms = (time.time() - start_time) * 1000
        print(f"❌ FAIL - Timeout (120s)")
        return {
            "id": test_id,
            "name": test_name,
            "expected": sorted(list(expected_tools)),
            "actual": [],
            "success": False,
            "latency_ms": latency_ms,
            "stderr": "Timeout exceeded"
        }
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        print(f"FAIL - Exception: {str(e)[:100]}")
        return {
            "id": test_id,
            "name": test_name,
            "expected": sorted(list(expected_tools)),
            "actual": [],
            "success": False,
            "latency_ms": latency_ms,
            "stderr": str(e)[:200]
        }


def main():
    """Main benchmarking runner."""
    # Load golden dataset
    golden_path = Path(__file__).parent / "golden.json"
    if not golden_path.exists():
        print(f"Error: golden.json not found at {golden_path}")
        sys.exit(1)
    
    dataset = load_golden_dataset(str(golden_path))
    tests = dataset.get("tests", [])
    
    if not tests:
        print("Error: No tests found in golden.json")
        sys.exit(1)
    
    print(f"\n{'=' * 70}")
    print(f"Clinical Agents Benchmarking")
    print(f"{dataset.get('test_suite', 'Test Suite')}")
    print(f"Description: {dataset.get('description', 'N/A')}")
    print(f"Tests: {len(tests)}")
    print(f"Started: {datetime.now().isoformat()}")
    print(f"{'=' * 70}\n")
    
    results = []
    
    # Run all tests
    for test in tests:
        result = run_test_case(test)
        results.append(result)
        time.sleep(2)  # Be nice to APIs
    
    # Print summary
    print(f"\n{'=' * 70}")
    print("TEST SUMMARY")
    print(f"{'=' * 70}\n")
    
    passed = sum(1 for r in results if r["success"])
    failed = len(results) - passed
    
    for result in results:
        status = "PASS" if result["success"] else "FAIL"
        print(f"{status} [{result['id']:2d}] {result['name']:<30} ({result['latency_ms']:>6.0f} ms)")
        if not result["success"]:
            exp = ", ".join(result["expected"]) if result["expected"] else "none"
            act = ", ".join(result["actual"]) if result["actual"] else "none"
            print(f"     Expected: {exp}")
            print(f"     Got:      {act}")
    
    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed out of {len(results)} tests")
    print(f"Success rate: {100 * passed / len(results):.1f}%")
    print(f"{'=' * 70}\n")
    
    # Save results to JSON
    output_file = Path(__file__).parent / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(results),
            "passed": passed,
            "failed": failed,
            "success_rate": 100 * passed / len(results),
            "results": results
        }, f, indent=2)
    
    print(f"Results saved to: {output_file}\n")
    
    # Exit with appropriate code
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
