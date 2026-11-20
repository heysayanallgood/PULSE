"""
Unit tests for ADR 001: Storage & Virtual Environment Isolation
"""
import os
import shutil
from pathlib import Path
from app.core.storage import run_storage_diagnostics, configure_process_environment, REQUIRED_DIRS

def test_storage_diagnostics_e_drive():
    configure_process_environment()
    diag = run_storage_diagnostics()
    assert diag["status"] == "HEALTHY"
    assert diag["drive"] == "E:"
    assert diag["free_gb"] > 50.0  # Currently ~793 GB free
    assert diag["verified_directories"] == len(REQUIRED_DIRS)

def test_pip_cache_and_temp_on_e():
    configure_process_environment()
    assert "E:" in os.environ["TEMP"]
    assert "E:" in os.environ["TMP"]
    assert "E:" in os.environ["PIP_CACHE_DIR"]
    assert Path(os.environ["TEMP"]).exists()
    assert Path(os.environ["PIP_CACHE_DIR"]).exists()
