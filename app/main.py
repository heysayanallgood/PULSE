"""
PULSE — Predictive Urban Mobility & Live Spatiotemporal Engine
FastAPI Production Application Entrypoint (app/main.py)
"""
import time
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.logging import logger
from app.core.storage import run_storage_diagnostics, configure_process_environment
from app.services.realtime_service import realtime_service
from app.api.v1.stops import router as stops_router
from app.api.v1.routes import router as routes_router
from app.api.v1.journeys import router as journeys_router
from app.api.v1.vehicles import router as vehicles_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.validation import router as validation_router

_START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle management."""
    # 1. Startup: Enforce storage invariants (ADR 001)
    configure_process_environment()
    diag = run_storage_diagnostics()
    logger.info(f"PULSE {settings.APP_VERSION} starting up. Storage check: {diag['status']} ({diag['free_gb']} GB free on E:)")
    
    # Launch live GTFS-RT feed poller in background if enabled
    poll_task = None
    if settings.LIVE_FEED_ENABLED and settings.OTD_API_KEY:
        poll_task = asyncio.create_task(realtime_service.start_background_poller())
        logger.info("Launched live GTFS-RT background poller task.")
    
    # 2. Yield control to application
    yield
    
    # 3. Shutdown: Clean up resources
    if poll_task:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
    logger.info("PULSE application shutting down cleanly.")


app = FastAPI(
    title=settings.APP_FULL_NAME,
    description="Delhi DTC Bus Spatiotemporal Travel-Time Model & Multi-Criteria Journey Planner (Problem 1, HopCode).",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for local development and web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mount API v1 Routers
app.include_router(stops_router, prefix="/api/v1")
app.include_router(routes_router, prefix="/api/v1")
app.include_router(journeys_router, prefix="/api/v1")
app.include_router(vehicles_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(validation_router, prefix="/api/v1")

# Mount Frontend Static Files if directory exists
static_path = Path("E:/Pulse/frontend/static")
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="E:/Pulse/frontend/static"), name="static")


@app.get("/", tags=["UI"], response_class=HTMLResponse)
def index_page():
    """Serves the PULSE Interactive Web Application with injected configuration."""
    index_file = Path("E:/Pulse/frontend/index.html")
    if index_file.exists():
        html = index_file.read_text(encoding="utf-8")
        carto_key = settings.CARTO_API_KEY or ""
        config_script = f"<script>window.PULSE_CONFIG = {{ cartoApiKey: '{carto_key}', liveEnabled: {'true' if settings.LIVE_FEED_ENABLED else 'false'} }};</script>"
        if "</head>" in html:
            html = html.replace("</head>", f"  {config_script}\n</head>")
        return HTMLResponse(content=html)
    return HTMLResponse(content="<h1>PULSE API is Running</h1><p><a href='/docs'>Swagger API Documentation</a></p>")


@app.get("/api/v1/config", tags=["System"])
def get_public_config() -> Dict[str, Any]:
    """Returns safe client-side UI configurations (basemap keys, intervals)."""
    return {
        "carto_api_key": settings.CARTO_API_KEY,
        "live_feed_enabled": settings.LIVE_FEED_ENABLED,
        "poll_interval_seconds": settings.LIVE_POLL_INTERVAL_SECONDS,
        "app_version": settings.APP_VERSION
    }


@app.get("/api", tags=["Root"])
def root() -> Dict[str, Any]:
    """Root endpoint returning service identity and navigation links."""
    return {
        "service": settings.APP_NAME,
        "full_name": settings.APP_FULL_NAME,
        "version": settings.APP_VERSION,
        "team": "HopCode",
        "hackathon": "Transport Stack Hackathon 2026",
        "problem": "Phase 1 - Problem 1: Real-time Bus Traffic Model & Journey Planner",
        "docs_url": "/docs",
        "status_url": "/api/v1/system/status"
    }


@app.get("/api/v1/health", tags=["System"])
def get_health() -> Dict[str, Any]:
    """Liveness probe reporting process status and uptime."""
    uptime_seconds = round(time.time() - _START_TIME, 2)
    return {
        "status": "HEALTHY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": uptime_seconds,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV
    }


@app.get("/api/v1/ready", tags=["System"])
def get_readiness() -> JSONResponse:
    """Readiness probe validating storage, disk space, and data directory access."""
    try:
        diag = run_storage_diagnostics()
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "READY",
                "storage": diag,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "NOT_READY",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )


@app.get("/api/v1/system/status", tags=["System"])
def get_system_status() -> Dict[str, Any]:
    """Comprehensive system status across storage, datasets, models, and live feeds."""
    diag = run_storage_diagnostics()
    
    # Check historical SQLite archive
    hist_dir = settings.HISTORICAL_SQLITE_DIR
    hist_files = list(hist_dir.glob("bus_movements_*.db")) if hist_dir.exists() else []
    
    # Check GTFS directory
    gtfs_dir = settings.STATIC_GTFS_DIR
    gtfs_files = list(gtfs_dir.glob("*.txt")) if gtfs_dir.exists() else []
    
    return {
        "system": {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.APP_ENV,
            "timezone": settings.TIMEZONE,
            "uptime_seconds": round(time.time() - _START_TIME, 2)
        },
        "storage": {
            "drive": diag["drive"],
            "free_gb": diag["free_gb"],
            "total_gb": diag["total_gb"],
            "status": diag["status"]
        },
        "datasets": {
            "historical_sqlite": {
                "directory": str(hist_dir),
                "database_count": len(hist_files),
                "expected_count": 31,
                "status": "READY" if len(hist_files) == 31 else "PARTIAL",
                "provenance": "HISTORICAL (Immutable Raw)"
            },
            "static_gtfs": {
                "directory": str(gtfs_dir),
                "file_count": len(gtfs_files),
                "status": "READY" if len(gtfs_files) >= 5 else "INCOMPLETE",
                "provenance": "STATIC_GTFS (Immutable Raw)"
            }
        },
        "live_feed": {
            "endpoint": settings.OTD_VEHICLE_POSITIONS_URL,
            "enabled": settings.LIVE_FEED_ENABLED,
            "api_key_status": settings.get_redacted_api_key(),
            "max_staleness_seconds": settings.LIVE_MAX_STALENESS_SECONDS,
            "status": "ACTIVE" if settings.LIVE_FEED_ENABLED and settings.OTD_API_KEY else "INACTIVE_HISTORICAL_FALLBACK"
        }
    }


@app.get("/api/v1/data/sources", tags=["Data"])
def get_data_sources() -> Dict[str, Any]:
    """Inventory of available data sources, schemas, and provenance states."""
    return {
        "sources": [
            {
                "id": "delhi_dtc_historical_gps_2026_10",
                "type": "HISTORICAL_GPS",
                "format": "SQLite3 (31 daily databases)",
                "location": str(settings.HISTORICAL_SQLITE_DIR),
                "total_size_gb": 115.5,
                "date_range": "2026-10-01 to 2026-10-31",
                "access_mode": "READ_ONLY (mode=ro)",
                "provenance": "HISTORICAL",
                "status": "VERIFIED"
            },
            {
                "id": "delhi_buses_static_gtfs_v1",
                "type": "STATIC_GTFS",
                "format": "GTFS CSV",
                "location": str(settings.STATIC_GTFS_DIR),
                "total_size_mb": 161.74,
                "stops_count": 6862,
                "routes_count": 2574,
                "trips_count": 80357,
                "shapes_count": 965607,
                "access_mode": "READ_ONLY",
                "provenance": "SCHEDULE_BASED",
                "status": "VERIFIED"
            },
            {
                "id": "delhi_otd_live_vehicle_positions",
                "type": "LIVE_GTFS_RT",
                "format": "Protocol Buffers (GTFS-RT VehiclePositions.pb)",
                "endpoint": settings.OTD_VEHICLE_POSITIONS_URL,
                "auth_param": settings.OTD_API_KEY_PARAM,
                "provenance": "LIVE",
                "status": "CONFIGURABLE"
            }
        ]
    }
