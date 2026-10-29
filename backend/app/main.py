from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.logging_config import setup_logging
from app.database import Base, engine as db_engine, session_scope
from app.engine.recovery import force_safe_state_on_startup
from app.engine.trading_engine import engine as trading_engine
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
    logger.info("FYERS Auto Trader backend started. RECOVERY CHECK REQUIRED before auto trading can resume.")


@app.on_event("shutdown")
def on_shutdown():
    trading_engine.stop_background_loop()


@app.get("/api/ping")
def ping():
    return {"status": "ok"}
