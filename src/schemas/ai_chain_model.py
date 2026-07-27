# -*- coding: utf-8 -*-
"""Versioned contracts for the AI-chain decision-support model.

These contracts intentionally separate slowly-changing industry evidence from
daily market data.  They are also the boundary that makes a historical replay
use the membership and industry profiles that were effective on its as-of date.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field, model_validator


class AIChainGroup(str, Enum):
    """Top-level branches in the AI investment universe."""

    HARDWARE = "hardware"
    EDGE = "edge"
    APPLICATION = "application"


class UniverseTier(str, Enum):
    """Business-purity tier used by allocation and scoring guards."""

    CORE = "core"
    OBSERVATION = "observation"


class HardwareSubgroup(str, Enum):
    """Direct-supply hardware groups agreed for the first model version."""

    EDA_IP = "eda_ip"
    SEMICONDUCTOR_MATERIALS = "semiconductor_materials"
    SEMICONDUCTOR_EQUIPMENT = "semiconductor_equipment"
    WAFER_MANUFACTURING = "wafer_manufacturing"
    AI_CHIPS_STORAGE = "ai_chips_storage"
    ADVANCED_PACKAGING_TEST = "advanced_packaging_test"
    NETWORK_CHIPS_OPTICAL_INTERCONNECT = "network_chips_optical_interconnect"
    PCB_CCL_COPPER_INTERCONNECT = "pcb_ccl_copper_interconnect"
    AI_SERVERS_ODM_RACKS = "ai_servers_odm_racks"
    SERVER_POWER_SUPPLY = "server_power_supply"
    LIQUID_COOLING_THERMAL_MANAGEMENT = "liquid_cooling_thermal_management"


class ExpansionCycle(str, Enum):
    """Slow-variable capacity cycle classification."""

    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class DataQualityStatus(str, Enum):
    """Whether daily bars are safe to use for a new model decision."""

    READY = "ready"
    DEGRADED = "degraded"
    INSUFFICIENT = "insufficient"
    FAILED = "failed"


class AdjustmentStatus(str, Enum):
    """Known state of the provider's price-adjustment convention."""

    UNKNOWN = "unknown"
    CONSISTENT = "consistent"
    MIXED = "mixed"


class MarketGate(str, Enum):
    """Portfolio-level market-risk state derived from end-of-day bars."""

    NORMAL = "normal"
    CAUTION = "caution"
    RISK_OFF = "risk_off"


class AIChainModelAction(str, Enum):
    """Decision-support action; never an order instruction."""

    BUY = "buy"
    HOLD = "hold"
    REDUCE = "reduce"
    AVOID = "avoid"
    DATA_INSUFFICIENT = "data_insufficient"


class AIChainModelProfile(BaseModel):
    """Versioned, deterministic parameters for one daily scoring run."""

    model_version: str = "v1"
    holding_days: int = Field(default=20, ge=10, le=30)
    min_history_bars: int = Field(default=60, ge=40, le=260)
    min_coverage_ratio: float = Field(default=0.90, gt=0, le=1)
    min_calibration_sample: int = Field(default=20, ge=1, le=1000)
    core_buy_threshold: float = Field(default=60, ge=0, le=100)
    observation_buy_threshold: float = Field(default=68, ge=0, le=100)
    observation_score_penalty: float = Field(default=5, ge=0, le=30)
    max_single_position: float = Field(default=0.15, gt=0, le=1)
    max_ai_allocation: float = Field(default=0.60, gt=0, le=1)
    max_hardware_subgroup_allocation: float = Field(default=0.20, gt=0, le=1)
    max_observation_allocation: float = Field(default=0.15, ge=0, le=1)
    min_holdings: int = Field(default=6, ge=1, le=20)
    max_holdings: int = Field(default=8, ge=1, le=20)

    @model_validator(mode="after")
    def validate_constraints(self) -> "AIChainModelProfile":
        if self.holding_days not in {10, 20, 30}:
            raise ValueError("holding_days must be one of 10, 20, or 30")
        if self.min_holdings > self.max_holdings:
            raise ValueError("min_holdings cannot exceed max_holdings")
        if self.max_observation_allocation > self.max_ai_allocation:
            raise ValueError("max_observation_allocation cannot exceed max_ai_allocation")
        return self


class AIChainUniverseMember(BaseModel):
    """One time-bounded classification record for a listed company."""

    code: str = Field(pattern=r"^\d{6}$")
    name: str = Field(min_length=1, max_length=32)
    group: AIChainGroup
    tier: UniverseTier
    hardware_subgroup: Optional[HardwareSubgroup] = None
    effective_from: date
    effective_to: Optional[date] = None
    evidence_summary: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_classification(self) -> "AIChainUniverseMember":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot be before effective_from")
        if self.group == AIChainGroup.HARDWARE and self.hardware_subgroup is None:
            raise ValueError("hardware members must specify hardware_subgroup")
        if self.group != AIChainGroup.HARDWARE and self.hardware_subgroup is not None:
            raise ValueError("non-hardware members cannot specify hardware_subgroup")
        return self

    def is_active_on(self, as_of_date: date) -> bool:
        """Return whether this classification record applies on ``as_of_date``."""
        return self.effective_from <= as_of_date and (
            self.effective_to is None or as_of_date <= self.effective_to
        )


class AIChainIndustryProfile(BaseModel):
    """Evidence-backed slow variables for one hardware subgroup version."""

    version: str = Field(min_length=1, max_length=64)
    hardware_subgroup: HardwareSubgroup
    effective_from: date
    effective_to: Optional[date] = None
    barrier_score: int = Field(ge=1, le=5)
    scarcity_score: int = Field(ge=1, le=5)
    ai_demand_transmission_score: int = Field(ge=1, le=5)
    expansion_cycle: ExpansionCycle
    evidence_date: date
    evidence_summary: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_effective_period(self) -> "AIChainIndustryProfile":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot be before effective_from")
        return self

    def is_active_on(self, as_of_date: date) -> bool:
        return self.effective_from <= as_of_date and (
            self.effective_to is None or as_of_date <= self.effective_to
        )


class DailyDataQualityReport(BaseModel):
    """Auditable quality result emitted for one stock's daily-bar preparation."""

    code: str = Field(pattern=r"^\d{6}$")
    start_date: date
    end_date: date
    expected_trading_days: int = Field(ge=0)
    available_trading_days: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0, le=1)
    amount_coverage_ratio: float = Field(ge=0, le=1)
    last_trade_date: Optional[date] = None
    data_sources: List[str] = Field(default_factory=list)
    adjustment_status: AdjustmentStatus = AdjustmentStatus.UNKNOWN
    status: DataQualityStatus
    used_remote_fetch: bool = False
    failure_reasons: List[str] = Field(default_factory=list)


class AIChainScoreResult(BaseModel):
    """Published deterministic score for one stock on one end-of-day run."""

    code: str = Field(pattern=r"^\d{6}$")
    name: str
    group: AIChainGroup
    tier: UniverseTier
    hardware_subgroup: Optional[HardwareSubgroup] = None
    score: float = Field(ge=0, le=100)
    group_rank: Optional[int] = Field(default=None, ge=1)
    overall_rank: Optional[int] = Field(default=None, ge=1)
    factor_snapshot: Dict[str, Any] = Field(default_factory=dict)
    quality_snapshot: Dict[str, Any] = Field(default_factory=dict)
    probability_up: Optional[float] = Field(default=None, ge=0, le=1)
    probability_outperform: Optional[float] = Field(default=None, ge=0, le=1)
    expected_return: Optional[float] = None
    return_low: Optional[float] = None
    return_high: Optional[float] = None
    drawdown_risk: Optional[float] = Field(default=None, ge=0)
    action: AIChainModelAction
    suggested_weight: float = Field(default=0, ge=0, le=1)
    reason: Optional[str] = None


class AIChainModelResult(BaseModel):
    """Pure-function output saved by the orchestration service as a run."""

    as_of_date: date
    model_profile: AIChainModelProfile
    market_gate: MarketGate
    market_gate_reason: str
    scores: List[AIChainScoreResult]
    warnings: List[str] = Field(default_factory=list)


class AIChainUniverseConfig(BaseModel):
    """The full, versioned stock pool used by the model."""

    schema_version: str = Field(min_length=1, max_length=64)
    historical_membership_assumption: str = Field(min_length=1, max_length=128)
    members: List[AIChainUniverseMember] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_no_overlapping_memberships(self) -> "AIChainUniverseConfig":
        by_code: dict[str, list[AIChainUniverseMember]] = {}
        for member in self.members:
            by_code.setdefault(member.code, []).append(member)

        for code, records in by_code.items():
            ordered = sorted(records, key=lambda item: item.effective_from)
            for previous, current in zip(ordered, ordered[1:]):
                if previous.effective_to is None or current.effective_from <= previous.effective_to:
                    raise ValueError(f"stock {code} has multiple active memberships")
        return self

    def active_members(self, as_of_date: date) -> List[AIChainUniverseMember]:
        """Return the one active classification record per stock as of a date."""
        return [member for member in self.members if member.is_active_on(as_of_date)]

    def validate_industry_profiles(
        self, profiles: Iterable[AIChainIndustryProfile]
    ) -> None:
        """Require a slow-variable profile for every configured hardware group."""
        required = {
            member.hardware_subgroup
            for member in self.members
            if member.hardware_subgroup is not None
        }
        configured = {profile.hardware_subgroup for profile in profiles}
        missing = required - configured
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"missing industry profiles for hardware subgroups: {names}")
