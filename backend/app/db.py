"""Database engine, session, pragmas, and init/seed logic.

Sync SQLAlchemy 2.x over SQLite in WAL mode. See decisions.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

# Repo-root-relative path. `__file__` is backend/app/db.py, so parents[2] is the
# repo root. We then place the DB at backend/telemetry.db.
DB_PATH = Path(__file__).resolve().parents[2] / "backend" / "telemetry.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30.0},
    pool_pre_ping=True,
    future=True,
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Apply WAL + sane sync + FK + busy_timeout on every new connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session():
    """FastAPI dependency. Yields a session, rolls back on exception."""
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Create tables (idempotent) and seed zones, vehicles, and missions."""
    # Import here to avoid circular imports at module load.
    from .models import Base
    from .zones import ZONES

    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        # Seed zones
        for z in ZONES:
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO zone_counts (zone_id, entry_count) "
                    "VALUES (:z, 0)"
                ),
                {"z": z},
            )

        # Seed vehicles v-00 .. v-49
        for i in range(50):
            vid = f"v-{i:02d}"
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO vehicles "
                    "(vehicle_id, status, status_version) "
                    "VALUES (:v, 'idle', 0)"
                ),
                {"v": vid},
            )

        # Seed one active mission per vehicle (only if none exists)
        now = _now_iso()
        for i in range(50):
            vid = f"v-{i:02d}"
            existing = conn.execute(
                text(
                    "SELECT COUNT(*) FROM missions "
                    "WHERE vehicle_id = :v AND status = 'active'"
                ),
                {"v": vid},
            ).scalar_one()
            if existing == 0:
                conn.execute(
                    text(
                        "INSERT INTO missions "
                        "(vehicle_id, status, created_at, cancelled_at) "
                        "VALUES (:v, 'active', :t, NULL)"
                    ),
                    {"v": vid, "t": now},
                )
