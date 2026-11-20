"""
PULSE Application Configuration (app/core/config.py)
Uses Pydantic Settings with strict secret redaction and environment-based overrides.
"""
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="E:/Pulse/.env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Server Configuration
    APP_NAME: str = "PULSE"
    APP_FULL_NAME: str = "Predictive Urban Mobility & Live Spatiotemporal Engine"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    DEBUG: bool = False

    # Security & API Credentials (ADR 005)
    OTD_VEHICLE_POSITIONS_URL: str = "https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb"
    OTD_API_KEY: Optional[str] = Field(default=None, description="Auth key for Delhi OTD Live Feed")
    OTD_API_KEY_PARAM: str = "key"

    # Real-Time Service Settings
    LIVE_FEED_ENABLED: bool = False
    LIVE_POLL_INTERVAL_SECONDS: int = 30
    LIVE_MAX_STALENESS_SECONDS: int = 90  # STALE threshold (ADR 005)
    LIVE_DEGRADED_TOLERANCE_SECONDS: int = 120

    # Storage Paths (ADR 001)
    WORKSPACE_ROOT: Path = Path("E:/Pulse")
    DATA_ROOT: Path = Path("E:/Pulse/data")
    RAW_DATA_ROOT: Path = Path("E:/Pulse/data/raw")
    STAGING_DATA_ROOT: Path = Path("E:/Pulse/data/staging")
    PROCESSED_DATA_ROOT: Path = Path("E:/Pulse/data/processed")
    DATABASE_ROOT: Path = Path("E:/Pulse/data/database")
    MODEL_ROOT: Path = Path("E:/Pulse/data/models")
    CACHE_ROOT: Path = Path("E:/Pulse/data/cache")
    MANIFEST_ROOT: Path = Path("E:/Pulse/data/manifests")
    LOG_ROOT: Path = Path("E:/Pulse/logs")

    # Raw Source Paths (ADR 006)
    HISTORICAL_SQLITE_DIR: Path = Path("E:/Pulse/delhi-dtc-bus-gtfs-rt-2026-10")
    STATIC_GTFS_DIR: Path = Path("E:/Pulse/delhi_buses_static_gtfs_v1")

    # Timezone & Geospatial Settings (ADR 003)
    TIMEZONE: str = "Asia/Kolkata"
    PROJECTED_CRS: str = "EPSG:32643"  # UTM Zone 43N
    GEOGRAPHIC_CRS: str = "EPSG:4326"

    # Travel Time Model Settings (ADR 002, ADR 004)
    TIME_BUCKET_MINUTES: int = 15
    SEGMENT_MIN_LENGTH_M: float = 300.0
    SEGMENT_MAX_LENGTH_M: float = 500.0
    MAX_GPS_SPEED_MPS: float = 25.0  # ~90 km/h
    MAX_SHAPE_OFFSET_M: float = 50.0

    # Walking & Routing Settings (ADR 004)
    WALKING_SPEED_MPS: float = 1.2  # ~4.3 km/h
    MAX_WALK_RADIUS_M: float = 1000.0
    MIN_TRANSFER_BUFFER_SECONDS: int = 180  # 3 minutes

    def get_redacted_api_key(self) -> str:
        """Returns safe redacted version of OTD_API_KEY for health checks."""
        if not self.OTD_API_KEY:
            return "NOT_CONFIGURED"
        k = self.OTD_API_KEY.strip()
        if len(k) <= 6:
            return "***"
        return f"{k[:3]}...{k[-3:]}"

    def __repr__(self) -> str:
        return f"<Settings: {self.APP_NAME} v{self.APP_VERSION} ({self.APP_ENV})>"


settings = Settings()
