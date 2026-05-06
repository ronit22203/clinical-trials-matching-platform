"""
sys.path isolation for agentic-reasoning tests.

This conftest MUST be loaded by pytest before any test file in this directory
is imported.  It purges any stale 'src.*' modules cached from prior test
directories and ensures agentic-reasoning/src is the first match for
'import src.*'.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REASONING_ROOT = _REPO_ROOT / "agentic-reasoning"

# Purge any 'src' package cached from data-acquisition or data-ingestion.
for _k in list(sys.modules):
    if _k == "src" or _k.startswith("src."):
        del sys.modules[_k]

# Remove other module roots so they can't shadow this one.
for _other in ("data-acquisition", "data-ingestion"):
    _other_root = str(_REPO_ROOT / _other)
    while _other_root in sys.path:
        sys.path.remove(_other_root)

# Put agentic-reasoning at the head of sys.path.
_root_str = str(_REASONING_ROOT)
while _root_str in sys.path:
    sys.path.remove(_root_str)
sys.path.insert(0, _root_str)
