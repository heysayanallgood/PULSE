"""
PULSE Storage Diagnostic & Workspace Safeguards (ADR 001)
Validates that required data directories exist and are writable.
"""
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Any

from app.core.config import settings

REQUIRED_DIRS = [
    settings.CACHE_ROOT / "pip",
    settings.CACHE_ROOT / "temp",
    settings.CACHE_ROOT / "duckdb",
    settings.RAW_DATA_ROOT,
    settings.STAGING_DATA_ROOT,
    settings.PROCESSED_DATA_ROOT,
    settings.DATABASE_ROOT,
    settings.MODEL_ROOT,
    settings.MANIFEST_ROOT,
    settings.DATA_ROOT / "validation",
    settings.LOG_ROOT,
]

MIN_FREE_GB_THRESHOLD = 20.0  # Alert threshold for workspace drive


class StorageSafetyError(RuntimeError):
    """Raised when storage invariants are violated."""
    pass


def run_storage_diagnostics() -> Dict[str, Any]:
    """
    Validates workspace availability, free disk space, and directory writability.
    Enforces ADR 001 isolation invariants.
    """
    workspace = settings.WORKSPACE_ROOT.resolve()
    if not workspace.exists():
        raise StorageSafetyError(f"CRITICAL: Workspace {workspace} not accessible.")

    drive = workspace.anchor  # e.g. "E:\\" or "D:\\"
    total, used, free = shutil.disk_usage(drive)
    free_gb = free / (1024 ** 3)
    total_gb = total / (1024 ** 3)

    if free_gb < MIN_FREE_GB_THRESHOLD:
        raise StorageSafetyError(f"CRITICAL: Low disk space on {drive} ({free_gb:.2f} GB free). Threshold is {MIN_FREE_GB_THRESHOLD} GB.")

    # Ensure all required directories exist and are writable
    created_or_verified = []
    for d in REQUIRED_DIRS:
        d.mkdir(parents=True, exist_ok=True)
        # Test writability with a tiny canary file
        test_file = d / ".canary"
        try:
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
            created_or_verified.append(str(d))
        except Exception as e:
            raise StorageSafetyError(f"CRITICAL: Directory {d} is not writable: {e}")

    # Verify environment variables
    temp_env = os.environ.get("TEMP", "")
    tmp_env = os.environ.get("TMP", "")
    pip_cache = os.environ.get("PIP_CACHE_DIR", "")

    return {
        "workspace": str(workspace),
        "drive": drive,
        "total_gb": round(total_gb, 2),
        "free_gb": round(free_gb, 2),
        "verified_directories": len(created_or_verified),
        "temp_env": temp_env,
        "tmp_env": tmp_env,
        "pip_cache_env": pip_cache,
        "status": "HEALTHY"
    }


def configure_process_environment():
    """Sets TEMP, TMP, and PIP_CACHE_DIR to the workspace cache for the current Python process."""
    cache = str((settings.CACHE_ROOT / "temp").resolve())
    pip = str((settings.CACHE_ROOT / "pip").resolve())
    os.environ["TEMP"] = cache
    os.environ["TMP"] = cache
    os.environ["PIP_CACHE_DIR"] = pip


if __name__ == "__main__":
    configure_process_environment()
    diag = run_storage_diagnostics()
    print("Storage Diagnostic Report:")
    for k, v in diag.items():
        print(f"  {k}: {v}")

