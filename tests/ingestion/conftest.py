"""
sys.path isolation for data-ingestion tests.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INGESTION_ROOT = _REPO_ROOT / "data-ingestion"

for _k in list(sys.modules):
    if _k == "src" or _k.startswith("src."):
        del sys.modules[_k]

for _other in ("agentic-reasoning", "data-acquisition"):
    _other_root = str(_REPO_ROOT / _other)
    while _other_root in sys.path:
        sys.path.remove(_other_root)

_root_str = str(_INGESTION_ROOT)
while _root_str in sys.path:
    sys.path.remove(_root_str)
sys.path.insert(0, _root_str)
