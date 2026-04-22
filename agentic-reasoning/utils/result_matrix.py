"""Generate result matrix from execution summary JSONL."""

import json
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass, asdict


@dataclass
class ExecutionRow:
    """Single row in the result matrix."""
    timestamp: str
    execution_id: str
    user_query: str
    model: str
    latency_ms: float
    tools_called: List[str]
    tool_success_rate: float
    has_response: bool
    response_length: int
    tool_count: int


def load_summary_jsonl(filepath: Path) -> List[Dict[str, Any]]:
    """Load JSONL summary file."""
    rows = []
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def build_result_matrix(jsonl_rows: List[Dict[str, Any]]) -> List[ExecutionRow]:
    """Transform JSONL rows into result matrix."""
    matrix = []
    for row in jsonl_rows:
        exec_row = ExecutionRow(
            timestamp=row.get('timestamp', ''),
            execution_id=row.get('execution_id', ''),
            user_query=row.get('user_query', ''),
            model=row.get('model', ''),
            latency_ms=row.get('latency_ms', 0),
            tools_called=row.get('tools_called', []),
            tool_success_rate=row.get('tool_success_rate', 0),
            has_response=bool(row.get('response', '').strip()),
            response_length=len(row.get('response', '')),
            tool_count=len(row.get('tools_called', []))
        )
        matrix.append(exec_row)
    return matrix


def matrix_to_dicts(matrix: List[ExecutionRow]) -> List[Dict[str, Any]]:
    """Convert matrix to list of dicts for easy consumption."""
    return [asdict(row) for row in matrix]


def get_matrix_from_file(filepath: Path = None) -> List[Dict[str, Any]]:
    """Load JSONL and return result matrix as list of dicts."""
    if filepath is None:
        filepath = Path(__file__).parent.parent / 'log' / 'summary.jsonl'
    
    jsonl_data = load_summary_jsonl(filepath)
    matrix = build_result_matrix(jsonl_data)
    return matrix_to_dicts(matrix)


def print_matrix_summary(matrix: List[Dict[str, Any]]) -> None:
    """Print a formatted summary of the result matrix."""
    if not matrix:
        print("No results found")
        return
    
    print(f"\n{'='*100}")
    print(f"EXECUTION SUMMARY (Total: {len(matrix)})")
    print(f"{'='*100}\n")
    
    for i, row in enumerate(matrix, 1):
        print(f"{i}. Query: {row['user_query'][:70]}")
        print(f"   Execution ID: {row['execution_id']}")
        print(f"   Model: {row['model']}")
        print(f"   Latency: {row['latency_ms']:.2f}ms")
        print(f"   Tools: {', '.join(row['tools_called']) if row['tools_called'] else 'None'}")
        print(f"   Response: {'Yes' if row['has_response'] else 'No'} ({row['response_length']} chars)")
        print()


if __name__ == '__main__':
    matrix = get_matrix_from_file()
    print_matrix_summary(matrix)
    print(f"\nMatrix with {len(matrix)} execution records generated.")
