"""SQLAlchemy 2.x declarative models.

Timestamps are stored as ISO-8601 strings, not native datetimes, because
SQLite's datetime story is messy and we never need to compute on them in SQL
beyond ordering, which works fine lexicographically on ISO-8601.
`error_codes` is JSON-encoded into a TEXT column for the same reason.
"""
from __future__ import annotations

from sqlalchemy import Index, Integer, String, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    timestamp: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    battery_pct: Mapped[float] = mapped_column(Float, nullable=False)
    speed_mps: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error_codes_json: Mapped[str] = mapped_column(String, nullable=False, default="[]")
    zone_entered: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    __table_args__ = (
        Index("ix_telemetry_vehicle_ts", "vehicle_id", "timestamp"),
    )


class Vehicle(Base):
    __tablename__ = "vehicles"

    vehicle_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="idle")
    battery_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_timestamp: Mapped[str | None] = mapped_column(String, nullable=True)
    # Paper-trail counter, bumped on each status change. NOT used for
    # optimistic locking — the real concurrency guard is BEGIN IMMEDIATE.
    status_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    timestamp: Mapped[str] = mapped_column(String, index=True, nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str] = mapped_column(String, nullable=False, default="")

    __table_args__ = (
        Index("ix_anomalies_vehicle_ts", "vehicle_id", "timestamp"),
    )


class ZoneCount(Base):
    __tablename__ = "zone_counts"

    zone_id: Mapped[str] = mapped_column(String, primary_key=True)
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # active|cancelled|completed
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    cancelled_at: Mapped[str | None] = mapped_column(String, nullable=True)


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False, default="fault_transition")
