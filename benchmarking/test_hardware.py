"""Hardware labels for the benchmark report."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provenance import classify_hardware


def test_local_mac_is_a_macbook() -> None:
    hardware = classify_hardware(
        system="Darwin",
        nvidia_name="NVIDIA L4",
        mac_model="MacBook Air",
        mac_chip="Apple M4",
    )
    assert hardware == {"environment": "local", "device": "MacBook Air (Apple M4)"}


def test_gpu_server_is_nvidia_production() -> None:
    hardware = classify_hardware(
        system="Linux",
        nvidia_name="NVIDIA L4",
        mac_model=None,
        mac_chip=None,
    )
    assert hardware == {"environment": "production", "device": "NVIDIA L4"}


def test_gpu_name_without_vendor_is_prefixed() -> None:
    hardware = classify_hardware(
        system="Linux",
        nvidia_name="L4",
        mac_model=None,
        mac_chip=None,
    )
    assert hardware["environment"] == "production"
    assert hardware["device"] == "NVIDIA L4"
