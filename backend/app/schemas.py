"""Pydantic v2 request/response models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


def _to_utc_iso(value: str) -> str:
    """Parse a tz-aware ISO-8601 string and return a canonical UTC form.

    All comparisons downstream (`/anomalies` time filter, anomaly cache
    out-of-order guard) are lexicographic — that's only correct if every
    stored timestamp shares a single offset. Normalising at the boundary
    keeps the surface permissive while removing the lex-compare hazard.
    """
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f"invalid ISO-8601 timestamp: {value!r}") from e
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone offset: {value!r}")
    return dt.astimezone(timezone.utc).isoformat()


class TelemetryEventIn(BaseModel):
    model_config = {"str_strip_whitespace": True}

    # `v-NN` shape — keeps the schema permissive enough for 2-4 digit IDs
    # while rejecting empty / arbitrary strings.
    vehicle_id: Annotated[str, Field(pattern=r"^v-\d{2,4}$")]
    timestamp: str
    lat: float
    lon: float
    battery_pct: float
    speed_mps: float
    status: Literal["idle", "moving", "charging", "fault"]
    error_codes: list[str] = []
    zone_entered: str | None = None

    @field_validator("timestamp")
    @classmethod
    def _normalise_timestamp(cls, v: str) -> str:
        return _to_utc_iso(v)


class StatusUpdateIn(BaseModel):
    model_config = {"str_strip_whitespace": True}

    new_status: Literal["idle", "moving", "charging", "fault"]
