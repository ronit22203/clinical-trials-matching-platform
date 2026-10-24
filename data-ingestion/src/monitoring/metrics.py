"""Prometheus metric definitions and helpers for data-ingestion."""

from __future__ import annotations

import time

try:
    from prometheus_client import Counter, Histogram
except ImportError:  # pragma: no cover
    Counter = None  # type: ignore[misc, assignment]
    Histogram = None  # type: ignore[misc, assignment]

_OCR_DURATION = (
    Histogram(
        "ocr_duration_seconds",
        "Wall time to OCR a batch of PDF pages",
        ["backend"],
        buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
    )
    if Histogram is not None
    else None
)
_OCR_PAGES = (
    Counter("ocr_pages_total", "Pages processed by OCR", ["backend"])
    if Counter is not None
    else None
)
_OCR_ERRORS = (
    Counter("ocr_errors_total", "OCR failures", ["backend"])
    if Counter is not None
    else None
)
_OCR_CONFIDENCE = (
    Histogram(
        "ocr_confidence",
        "Per-block OCR confidence scores",
        ["backend"],
        buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0),
    )
    if Histogram is not None
    else None
)

_EMBED_DURATION = (
    Histogram(
        "embed_encode_duration_seconds",
        "Wall time to encode a batch of chunk texts",
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    )
    if Histogram is not None
    else None
)
_EMBED_VECTORS = (
    Counter("embed_vectors_total", "Vectors produced by the embedding model")
    if Counter is not None
    else None
)
_EMBED_BATCH = (
    Histogram(
        "embed_batch_size",
        "Number of texts per embedding encode call",
        buckets=(1, 4, 8, 16, 32, 64, 128, 256),
    )
    if Histogram is not None
    else None
)

_QDRANT_UPSERT_DURATION = (
    Histogram(
        "qdrant_upsert_duration_seconds",
        "Wall time to upsert a batch of points into Qdrant",
        ["collection"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
    if Histogram is not None
    else None
)
_QDRANT_POINTS = (
    Counter(
        "qdrant_points_upserted_total",
        "Points upserted into Qdrant",
        ["collection"],
    )
    if Counter is not None
    else None
)


def observe_ocr(
    *,
    backend: str,
    pages: int,
    duration_seconds: float,
    confidences: list[float] | None = None,
    error: bool = False,
) -> None:
    """Record OCR batch latency, page count, and optional confidence samples."""
    label = backend or "unknown"
    if error:
        if _OCR_ERRORS is not None:
            _OCR_ERRORS.labels(backend=label).inc()
        return
    if _OCR_DURATION is not None:
        _OCR_DURATION.labels(backend=label).observe(duration_seconds)
    if _OCR_PAGES is not None and pages > 0:
        _OCR_PAGES.labels(backend=label).inc(pages)
    if _OCR_CONFIDENCE is not None and confidences:
        for value in confidences:
            _OCR_CONFIDENCE.labels(backend=label).observe(value)


def observe_embed_encode(*, vectors: int, duration_seconds: float) -> None:
    """Record embedding encode latency and vector count."""
    if _EMBED_DURATION is not None:
        _EMBED_DURATION.observe(duration_seconds)
    if _EMBED_BATCH is not None and vectors > 0:
        _EMBED_BATCH.observe(vectors)
    if _EMBED_VECTORS is not None and vectors > 0:
        _EMBED_VECTORS.inc(vectors)


def observe_qdrant_upsert(
    *, collection: str, points: int, duration_seconds: float
) -> None:
    """Record Qdrant upsert latency and point count."""
    name = collection or "unknown"
    if _QDRANT_UPSERT_DURATION is not None:
        _QDRANT_UPSERT_DURATION.labels(collection=name).observe(duration_seconds)
    if _QDRANT_POINTS is not None and points > 0:
        _QDRANT_POINTS.labels(collection=name).inc(points)


def timed_seconds() -> float:
    """Return a high-resolution monotonic timestamp."""
    return time.perf_counter()
