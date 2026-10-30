from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.logging_config import setup_logging
from app.database import Base, engine as db_engine, session_scope
from app.engine.recovery import force_safe_state_on_startup
from app.engine.trading_engine import engine as trading_engine
from app.learning.scheduler import scheduler as auto_learning_scheduler
from app.api import (
    routes_auth, routes_setup, routes_trading, routes_dashboard, routes_journal, routes_emergency,
    routes_diagnostics, routes_data, routes_backtest, routes_ml, routes_learning, ws,
)

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="FYERS Auto Trader", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_auth.router)
app.include_router(routes_auth.legacy_callback_router)
app.include_router(routes_setup.router)
app.include_router(routes_trading.router)
app.include_router(routes_dashboard.router)
app.include_router(routes_journal.router)
app.include_router(routes_emergency.router)
app.include_router(routes_diagnostics.router)
app.include_router(routes_data.router)
app.include_router(routes_backtest.router)
app.include_router(routes_ml.router)
app.include_router(routes_learning.router)
app.include_router(ws.router)


@app.on_event("startup")
def on_startup():
    settings = get_settings()

    from migrations.migrate import run_migrations
    applied = run_migrations(settings.database_path)
    if applied:
        logger.info("Applied migrations: %s", applied)

    Base.metadata.create_all(bind=db_engine)  # safety net for any model/migration drift

    with session_scope() as db:
        force_safe_state_on_startup(db)
        trading_engine.load_client_from_db_if_needed(db)

    trading_engine.start_background_loop()
    auto_learning_scheduler.start()
    logger.info("FYERS Auto Trader backend started. RECOVERY CHECK REQUIRED before auto trading can resume.")


@app.on_event("shutdown")
def on_shutdown():
    trading_engine.stop_background_loop()
    auto_learning_scheduler.stop()


@app.get("/api/ping")
def ping():
    return {"status": "ok"}


# --- Serve the frontend's production build, if it has been built -----------
# Lets the whole app run as a single backend process (no separate Vite dev
# server) for day-to-day use - meaningfully lighter on memory, which matters
# for something meant to run unattended for a full trading session. Frontend
# development still uses scripts/start-frontend.ps1's Vite dev server as
# before; this only activates once `npm run build` has produced frontend/dist.
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

    @app.exception_handler(StarletteHTTPException)
    async def spa_fallback(request: Request, exc: StarletteHTTPException):
        # react-router uses client-side routes (/journal, /setup, ...) that
        # don't correspond to a real static file - StaticFiles 404s on those
        # by design (it only falls back to index.html for a directory, not
        # an arbitrary path). Any other 404 (bad /api/... path, etc.) keeps
        # FastAPI's normal JSON error response.
        if exc.status_code == 404 and not request.url.path.startswith(("/api", "/ws")):
            return FileResponse(FRONTEND_DIST / "index.html")
        return await http_exception_handler(request, exc)
else:
    logger.info("frontend/dist not found - run 'npm run build' in frontend/ to serve it from the backend, "
                "or use scripts/start-frontend.ps1 for the Vite dev server.")
