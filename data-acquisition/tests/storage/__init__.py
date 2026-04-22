"""
Storage tests for multi-cloud GraphRAG.

This package contains integration tests for:
- AWS S3 (primary storage)
- Azure Blob Storage (fallback)
- Local filesystem (catastrophic fallback)
- Multi-cloud failover scenarios
"""

import pytest

# Markers for test filtering
pytestmark = [
    pytest.mark.storage,
]
