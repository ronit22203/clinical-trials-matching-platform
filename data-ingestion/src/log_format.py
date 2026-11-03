"""Log formatter that prints repo-relative paths instead of home-directory paths."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

# Absolute path tokens inside a log line. The lookbehind skips URL schemes
# such as http:// so only filesystem paths are rewritten.
_ABS_PATH = re.compile(r"(?<![\w:])(/(?:[^/\s\"']+/)*[^/\s\"']+)")

_REPO_ROOT = Path(__file__).resolve().parents[2]


def relativize_logged_paths(text: str, root: Path | None = None) -> str:
    """Replace absolute paths under *root* with os.path.relpath results."""
    root_str = os.path.normpath(str(root or _REPO_ROOT))

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(1)
        normalized = os.path.normpath(raw)
        relative = os.path.relpath(normalized, root_str)
        if relative == ".." or relative.startswith(".." + os.sep):
            return raw
        return relative.replace(os.sep, "/")

    return _ABS_PATH.sub(_replace, text)


class RelativePathFormatter(logging.Formatter):
    """Formatter whose rendered message uses paths relative to the repo root."""

    def __init__(self, *args, root: Path | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._root = root or _REPO_ROOT

    def format(self, record: logging.LogRecord) -> str:
        return relativize_logged_paths(super().format(record), self._root)
