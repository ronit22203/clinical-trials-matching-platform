"""Structured execution logging for clinical agents."""
import json
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import subprocess


class ExecutionLogger:
    """Captures and logs execution metadata in structured JSON format."""

    def __init__(self, log_dir: str = "log"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.execution_id = str(uuid.uuid4())
        self.timestamp = datetime.now().isoformat()
        # Fetch git hash once at init rather than on every log call.
        self._git_commit: Optional[str] = self._fetch_git_commit()

    def _fetch_git_commit(self) -> Optional[str]:
        """Get current git commit hash (called once at init)."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.log_dir.parent,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def get_git_commit(self) -> Optional[str]:
        return self._git_commit

    def log_execution(
        self,
        model: str,
        system_instruction: str,
        user_query: str,
        response: str,
        latency_ms: float,
        tokens_input: int = 0,
        tokens_output: int = 0,
        temperature: float = 0.7,
        top_p: float = 0.9,
        tools_called: Optional[List[str]] = None,
        tool_success_rate: float = 1.0,
        tool_responses: Optional[Dict[str, Any]] = None,
        router_confidence: Optional[float] = None,
        router_intent: Optional[str] = None,
        memory_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a complete execution with all metadata (fire-and-forget via background thread)."""
        tokens_total = tokens_input + tokens_output

        log_entry = {
            "timestamp": self.timestamp,
            "execution_id": self.execution_id,
            "model": model,
            "system_instruction": system_instruction[:200] + "..." if len(system_instruction) > 200 else system_instruction,
            "user_query": user_query,
            "response": response[:500] + "..." if len(response) > 500 else response,
            "latency_ms": round(latency_ms, 2),
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "tokens_total": tokens_total,
            "temperature": temperature,
            "top_p": top_p,
            "tools_called": tools_called or [],
            "tool_success_rate": round(tool_success_rate, 2),
            "tool_responses": tool_responses or {},
        }

        if router_confidence is not None:
            log_entry["router_confidence"] = round(router_confidence, 2)
        if router_intent is not None:
            log_entry["router_intent"] = router_intent
        if memory_snapshot is not None:
            log_entry["memory_snapshot"] = memory_snapshot

        if self._git_commit:
            log_entry["git_commit"] = self._git_commit

        threading.Thread(target=self._write, args=(log_entry,), daemon=True).start()

    def _write(self, log_entry: dict) -> None:
        """Write log entry to disk (runs in background thread)."""
        log_file = self.log_dir / f"{log_entry['execution_id']}.json"
        with open(log_file, "w") as f:
            json.dump(log_entry, f, indent=2)

        summary_file = self.log_dir / "summary.jsonl"
        with open(summary_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
