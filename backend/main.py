from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.config.settings import get_settings
from backend.scheduler.jobs import start_scheduler, stop_scheduler
from backend.execution.backup_poller import backup_poller
from backend.websocket.market_feed import market_feed

# Logging setup
Path("backend/logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("backend/logs/app.log"),
    ],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Gap-Down Trading System (Kite Connect)")
    rs = get_settings()

    # Start background services
    start_scheduler()
    await market_feed.start()
    await backup_poller.start()

    logger.info("Backend listening on http://%s:%d", rs.host, rs.port)
    yield

    # Shutdown
    logger.info("Shutting down…")
    stop_scheduler()
    await market_feed.stop()
    await backup_poller.stop()


def create_app() -> FastAPI:
    rs = get_settings()

    app = FastAPI(
        title="Gap-Down Trading System",
        description="Kite Connect based NSE gap-down fill trading system",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[rs.frontend_base_url, "http://localhost:5555", "http://127.0.0.1:5555"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/api")

    # Serve frontend static build if present
    frontend_dist = Path("frontend/dist")
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
        logger.info("Serving frontend from %s", frontend_dist)

    return app


app = create_app()
