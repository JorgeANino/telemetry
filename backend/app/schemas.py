"""Pydantic v2 request/response models."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class TelemetryEventIn(BaseModel):
    model_config = {"str_strip_whitespace": True}

    vehicle_id: str
    timestamp: str
    lat: float
    lon: float
    battery_pct: float
    speed_mps: float
    status: Literal["idle", "moving", "charging", "fault"]
    error_codes: list[str] = []
    zone_entered: Optional[str] = None


class StatusUpdateIn(BaseModel):
    model_config = {"str_strip_whitespace": True}

    new_status: Literal["idle", "moving", "charging", "fault"]
