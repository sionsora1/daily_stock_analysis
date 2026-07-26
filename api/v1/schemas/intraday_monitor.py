# -*- coding: utf-8 -*-
"""Schemas for reusable intraday composite monitors."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class IntradayRepresentativeGroup(BaseModel):
    """Predefined upstream industry-role representatives for one monitor plan."""

    key: str = Field(..., min_length=1, max_length=48)
    label: str = Field(..., min_length=1, max_length=32)
    core_symbols: List[str] = Field(..., min_length=1)
    backup_symbols: List[str] = Field(default_factory=list)


class IntradayMonitorPlanCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    event_symbol: str = Field(..., min_length=1, max_length=16)
    sector_symbol: str = Field(..., min_length=1, max_length=16)
    monitored_symbols: List[str] = Field(..., min_length=1)
    representative_groups: Optional[List[IntradayRepresentativeGroup]] = None
    majority_ratio: float = Field(0.6, gt=0, le=1)
    initial_time: str = Field("10:00", min_length=4, max_length=8)
    confirm_time: str = Field("10:30", min_length=4, max_length=8)
    poll_interval_seconds: int = Field(30, ge=10, le=300)
    listing_day_mode: bool = False
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    enabled: bool = True
    paused: bool = False


class IntradayMonitorPlanUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    event_symbol: Optional[str] = Field(None, min_length=1, max_length=16)
    sector_symbol: Optional[str] = Field(None, min_length=1, max_length=16)
    monitored_symbols: Optional[List[str]] = Field(None, min_length=1)
    representative_groups: Optional[List[IntradayRepresentativeGroup]] = None
    majority_ratio: Optional[float] = Field(None, gt=0, le=1)
    initial_time: Optional[str] = Field(None, min_length=4, max_length=8)
    confirm_time: Optional[str] = Field(None, min_length=4, max_length=8)
    poll_interval_seconds: Optional[int] = Field(None, ge=10, le=300)
    listing_day_mode: Optional[bool] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    enabled: Optional[bool] = None
    paused: Optional[bool] = None


class IntradayMonitorPlanResponse(BaseModel):
    id: int
    name: str
    event_symbol: str
    sector_symbol: str
    monitored_symbols: List[str]
    representative_groups: List[IntradayRepresentativeGroup] = Field(default_factory=list)
    representative_groups_source: str = "none"
    majority_ratio: float
    required_count: int
    initial_time: str
    confirm_time: str
    poll_interval_seconds: int
    listing_day_mode: bool
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    enabled: bool
    paused: bool
    current_status: str
    last_evaluated_at: Optional[str] = None
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class IntradayMonitorPlanListResponse(BaseModel):
    items: List[IntradayMonitorPlanResponse] = Field(default_factory=list)
    total: int


class IntradayMonitorHistoryItem(BaseModel):
    id: int
    plan_id: int
    status: str
    reason: Optional[str] = None
    values: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class IntradayMonitorHistoryResponse(BaseModel):
    items: List[IntradayMonitorHistoryItem] = Field(default_factory=list)
    total: int


class IntradayMonitorDeleteResponse(BaseModel):
    deleted: int
