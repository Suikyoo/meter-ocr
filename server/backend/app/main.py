"""FastAPI app: API, MQTT ingest lifecycle, and the built SPA."""
import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import api, db
from .ingest import MqttIngest
from .settings import Settings, load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings, start_mqtt: bool = True,
               clock: Callable[[], datetime] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.connect(settings.db_path).close()  # create the schema before any request
        ingest = MqttIngest(settings.mqtt_url, settings.mqtt_prefix, settings.db_path) \
            if start_mqtt else None
        if ingest:
            ingest.start()
        yield
        if ingest:
            ingest.stop()

    app = FastAPI(title="Meter server", lifespan=lifespan)
    app.state.settings = settings
    app.state.clock = clock or (lambda: datetime.now(settings.tz))
    app.include_router(api.router, prefix="/api")
    if settings.static_dir and os.path.isdir(settings.static_dir):
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")
    return app


app = create_app(load_settings())
