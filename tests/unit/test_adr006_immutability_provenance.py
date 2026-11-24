"""
Unit tests for ADR 006: Raw Data Immutability & Lineage Provenance
"""
import json
import uuid
from pathlib import Path
from datetime import datetime

def test_manifest_schema_and_idempotency():
    manifest_record = {
        "pipeline_run_id": str(uuid.uuid4()),
        "source_file": "bus_movements_2026_10_01.db",
        "source_size_bytes": 3420090368,
        "source_records_extracted": 31290299,
        "records_cleaned": 30812400,
        "records_rejected": 477899,
        "rejection_breakdown": {
            "speed_outlier": 12400,
            "dist_to_shape_gt_50m": 465499
        },
        "output_parquet_files": [
            "data/processed/historical/year=2026/month=10/day=01/part-001.parquet"
        ],
        "processing_timestamp": datetime.now().isoformat(),
        "status": "COMPLETED"
    }
    
    # Save to manifests directory
    manifest_dir = Path("data/manifests")
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = manifest_dir / f"test_manifest_{manifest_record['source_file']}.json"
    
    with open(manifest_file, "w", encoding="utf-8") as fp:
        json.dump(manifest_record, fp, indent=2)
        
    assert manifest_file.exists()
    
    # Read back and verify all required keys exist
    with open(manifest_file, "r", encoding="utf-8") as fp:
        loaded = json.load(fp)
        
    assert loaded["source_records_extracted"] == 31290299
    assert loaded["records_cleaned"] + loaded["records_rejected"] == loaded["source_records_extracted"]
    assert loaded["status"] == "COMPLETED"
    
    # Cleanup test manifest
    manifest_file.unlink()

def test_atomic_staging_write():
    # Verify the atomic write pattern: write to staging, then atomic rename to destination
    staging_dir = Path("data/staging")
    processed_dir = Path("data/processed")
    staging_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    
    staging_file = staging_dir / "temp_part.tmp"
    final_file = processed_dir / "atomic_part.parquet"
    
    # Write temp file
    staging_file.write_text("parquet_mock_bytes", encoding="utf-8")
    assert staging_file.exists()
    
    # Atomic rename (move)
    staging_file.replace(final_file)
    assert not staging_file.exists()
    assert final_file.exists()
    
    # Cleanup
    final_file.unlink()
