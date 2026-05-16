"""FastAPI app entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routes import reads as reads_routes
from .routes import status as status_routes
from .routes import telemetry as telemetry_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Fleet Telemetry", version="0.1.0", lifespan=lifespan)

# Pinned to the local dev origins of the bundled dashboard. Credentials are
# not used; expand the list explicitly if the dashboard is hosted elsewhere.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
)


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.include_router(telemetry_routes.router)
app.include_router(status_routes.router)
app.include_router(reads_routes.router)
