from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from app.database import session_scope
from app.api.routes_dashboard import get_dashboard

logger = logging.getLogger(__name__)
router = APIRouter()

PUSH_INTERVAL_SECONDS = 3


@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            try:
                with session_scope() as db:
                    payload = get_dashboard(db)
                # jsonable_encoder (the same one FastAPI uses for normal HTTP
                # responses) converts datetimes/etc to JSON-safe values -
                # plain json.dumps (what send_json uses) cannot handle those.
                await websocket.send_json(jsonable_encoder(payload))
            except WebSocketDisconnect:
                raise
            except Exception:
                logger.exception("Dashboard websocket tick failed - will retry next interval")
            await asyncio.sleep(PUSH_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        logger.debug("Dashboard websocket client disconnected")
