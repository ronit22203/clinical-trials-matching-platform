#!/usr/bin/env python3
"""Generate a bcrypt hash for a plaintext password.

Usage:
    python3 scripts/hash_password.py <password>
    make auth-setup PASSWORD=admin

Paste the printed hash into .env.local as a single-quoted value:
    AUTH_PASSWORD_HASH='$2b$12$...'
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:  # noqa: PLR2004
        print("Usage: python3 scripts/hash_password.py <password>", file=sys.stderr)
        sys.exit(1)

    try:
        import bcrypt
    except ImportError:
        repo = Path(__file__).resolve().parents[1]
        for rel in (
            "agentic-reasoning/.venv/bin/python",
            "data-ingestion/.venv/bin/python",
        ):
            candidate = repo / rel
            if candidate.exists() and Path(sys.executable).resolve() != candidate.resolve():
                os.execv(str(candidate), [str(candidate), str(Path(__file__).resolve()), *sys.argv[1:]])
        print(
            "bcrypt not found. Use the reasoning venv:\n"
            "  ./agentic-reasoning/.venv/bin/python scripts/hash_password.py <password>\n"
            "or: ./agentic-reasoning/.venv/bin/pip install bcrypt",
            file=sys.stderr,
        )
        sys.exit(1)

    hashed = bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode()
    print(hashed)


if __name__ == "__main__":
    main()
