"""FastAPI app entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routes import reads as reads_routes
from .routes import status as status_routes
from .routes import telemetry as telemetry_routes

app = FastAPI(title="Fleet Telemetry", version="0.1.0")

# Permissive CORS — fine for a take-home single-origin dashboard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _on_startup() -> None:
    init_db()


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.include_router(telemetry_routes.router)
app.include_router(status_routes.router)
app.include_router(reads_routes.router)
