from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from config.settings import LOG_DIR, settings
from execution.backup_poller import backup_poller
from models.state import state_manager
from scheduler.jobs import scheduler_service
from utils.kite_client import kite_client


def configure_logging() -> None:
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    root.handlers.clear()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(LOG_DIR / "app.log")
    file_handler.setFormatter(formatter)

    root.addHandler(stream_handler)
    root.addHandler(file_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    if settings.kite_access_token:
        user_id = None
        await state_manager.set_access_token(settings.kite_access_token, None)
        try:
            profile = await kite_client.get_profile()
            user_id = profile.get("user_id") or profile.get("user_name") or profile.get("email")
        except Exception:
            logging.getLogger(__name__).exception("failed to validate access token loaded from .env")
        await state_manager.set_access_token(settings.kite_access_token, user_id)
        logging.getLogger(__name__).info("loaded Kite access token from .env")
    await backup_poller.start()
    await scheduler_service.start()
    yield
    await scheduler_service.stop()
    await backup_poller.stop()
    await kite_client.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Build a robust list of origins combining settings.cors_origins and server defaults
configured_origins = list(settings.cors_origins) if settings.cors_origins else []
extra_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://15.206.229.206:3000",  # Your Ubuntu production frontend
    "*"                            # Temporary fallback to resolve CORS instantly
]

for origin in extra_origins:
    if origin not in configured_origins:
        configured_origins.append(origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix=settings.api_prefix)
