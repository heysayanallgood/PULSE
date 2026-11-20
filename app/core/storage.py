"""
PULSE Storage Diagnostic & Workspace Safeguards (ADR 001)
Ensures host OS C: drive is protected and E: drive workspace is validated.
"""
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Any

REQUIRED_DIRS = [
    Path("E:/Pulse/data/cache/pip"),
    Path("E:/Pulse/data/cache/temp"),
    Path("E:/Pulse/data/cache/duckdb"),
    Path("E:/Pulse/data/raw"),
    Path("E:/Pulse/data/staging"),
    Path("E:/Pulse/data/processed"),
    Path("E:/Pulse/data/database"),
    Path("E:/Pulse/data/models"),
    Path("E:/Pulse/data/manifests"),
    Path("E:/Pulse/data/validation"),
    Path("E:/Pulse/logs"),
]

MIN_FREE_GB_THRESHOLD = 20.0  # Alert threshold for E: drive


class StorageSafetyError(RuntimeError):
    """Raised when storage invariants are violated."""
    pass


def run_storage_diagnostics() -> Dict[str, Any]:
    """
    Validates E: workspace availability, free disk space, and directory writability.
    Enforces ADR 001 isolation invariants.
    """
    workspace = Path("E:/Pulse")
    if not workspace.exists():
        raise StorageSafetyError("CRITICAL: E:/Pulse workspace not accessible. Aborting to protect C: drive.")

    total, used, free = shutil.disk_usage("E:/")
    free_gb = free / (1024 ** 3)
    total_gb = total / (1024 ** 3)

    if free_gb < MIN_FREE_GB_THRESHOLD:
        raise StorageSafetyError(f"CRITICAL: Low disk space on E: ({free_gb:.2f} GB free). Threshold is {MIN_FREE_GB_THRESHOLD} GB.")

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
        "workspace": str(workspace.resolve()),
        "drive": "E:",
        "total_gb": round(total_gb, 2),
        "free_gb": round(free_gb, 2),
        "verified_directories": len(created_or_verified),
        "temp_env": temp_env,
        "tmp_env": tmp_env,
        "pip_cache_env": pip_cache,
        "status": "HEALTHY"
    }


def configure_process_environment():
    """Sets TEMP, TMP, and PIP_CACHE_DIR to E: for the current Python process."""
    os.environ["TEMP"] = "E:/Pulse/data/cache/temp"
    os.environ["TMP"] = "E:/Pulse/data/cache/temp"
    os.environ["PIP_CACHE_DIR"] = "E:/Pulse/data/cache/pip"


if __name__ == "__main__":
    configure_process_environment()
    diag = run_storage_diagnostics()
    print("Storage Diagnostic Report:")
    for k, v in diag.items():
        print(f"  {k}: {v}")
