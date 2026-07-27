# -*- coding: utf-8 -*-
"""HTTP request and response contracts for the AI-chain model API."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AIChainModelRunRequest(BaseModel):
    as_of_date: Optional[date] = None


class AIChainModelBacktestRequest(BaseModel):
    start_date: date = date(2023, 7, 1)
    end_date: Optional[date] = None
    holding_days: int = Field(default=20, ge=10, le=30)
    rebalance_every_days: int = Field(default=5, ge=1, le=20)
    commission_rate: float = Field(default=0.0003, ge=0, le=0.1)
    sell_tax_rate: float = Field(default=0.0005, ge=0, le=0.1)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.1)


class AIChainModelTaskResponse(BaseModel):
    task_id: str
    kind: str
    status: str
    progress: int = Field(ge=0, le=100)
    message: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class AIChainModelLatestResponse(BaseModel):
    id: int
    as_of_date: str
    model_version: str
    status: str
    market_gate: Optional[str] = None
    data_coverage: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)
    model_profile: Dict[str, Any] = Field(default_factory=dict)
    data_quality: Dict[str, Any] = Field(default_factory=dict)
    scores: List[Dict[str, Any]] = Field(default_factory=list)
    is_stale: bool = False


class AIChainModelHistoryResponse(BaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
