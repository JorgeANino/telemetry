"""Pytest fixtures: per-test fresh SQLite DB with WAL pragmas applied."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

# Ensure the `app` package (under backend/) is importable when pytest is run
# from either the repo root or the backend/ directory.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


@event.listens_for(Engine, "connect")
def _test_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


@pytest.fixture(autouse=True)
def _reset_anomaly_cache():
    """Clear the in-process last-event cache before each test so cached
    battery readings from prior tests don't bleed into the next test's
    anomaly evaluation.
    """
    from app import anomaly

    anomaly._reset_cache_for_tests()
    yield
    anomaly._reset_cache_for_tests()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Build a fresh DB per test, monkeypatch the app's engine/SessionLocal,
    run init_db(), and yield a TestClient.
    """
    from app import db as db_module
    from app.main import app

    db_file = tmp_path / "test.db"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        pool_pre_ping=True,
        future=True,
    )
    test_sessionmaker = sessionmaker(
        bind=test_engine, autoflush=False, autocommit=False, future=True
    )

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", test_sessionmaker)
    monkeypatch.setattr(db_module, "DB_PATH", db_file)

    db_module.init_db()

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def session(client):
    """Yield a SQLAlchemy session bound to the test DB created above."""
    from app import db as db_module

    s = db_module.SessionLocal()
    try:
        yield s
    finally:
        s.close()
