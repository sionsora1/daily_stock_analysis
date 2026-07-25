# -*- coding: utf-8 -*-
"""Reusable intraday composite signal monitor.

The monitor deliberately uses a qualitative three-minute price/amount
structure instead of hard-coded percentage or volume-ratio thresholds.  The
event stock, sector ETF and stock-pool breadth must all agree before a
confirmed signal is emitted.
"""

from __future__ import annotations

import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from data_provider.base import DataFetcherManager, normalize_stock_code
from src.repositories.intraday_monitor_repo import IntradayMonitorRepository
from src.storage import IntradayMonitorPlanRecord

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_POLL_SECONDS = 30
DEFAULT_HISTORY_DAYS = 30
MIN_STREAK = 2
SAMPLE_WINDOW = 12
PATTERN_OK = {"attack_with_volume", "pullback_contracted", "steady"}

STATUS_OBSERVE = "observe"
STATUS_PRELIMINARY = "preliminary"
STATUS_CONFIRMED = "confirmed"
STATUS_CONTINUE = "continue_observing"
STATUS_INVALIDATED = "invalidated"
STATUS_INSUFFICIENT = "data_insufficient"
STATUS_INACTIVE = "inactive"


class IntradayMonitorValidationError(ValueError):
    """Invalid monitor plan payload."""


def clean_symbols(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        code = normalize_stock_code(str(value or "").strip())
        if not code or code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result


def required_breadth(total: int, ratio: float) -> int:
    if total <= 0:
        return 0
    return max(1, min(total, int(math.ceil(total * ratio))))


def parse_clock(value: str, field_name: str) -> time:
    try:
        hour, minute = (int(part) for part in value.strip().split(":", 1))
        parsed = time(hour=hour, minute=minute)
    except (AttributeError, TypeError, ValueError):
        raise IntradayMonitorValidationError(f"{field_name} must use HH:MM format")
    return parsed


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _source_name(quote: Any) -> Optional[str]:
    source = getattr(quote, "source", None)
    if source is None:
        return None
    return getattr(source, "value", None) or str(source)


def market_phase(now: datetime) -> str:
    current = now.timetz().replace(tzinfo=None)
    if current < time(9, 30):
        return "pre_open"
    if current < time(11, 30):
        return "morning"
    if current < time(13, 0):
        return "lunch_break"
    if current < time(14, 57):
        return "afternoon"
    if current < time(15, 0):
        return "closing_window"
    return "post_close"


def is_continuous_auction(now: datetime) -> bool:
    current = now.timetz().replace(tzinfo=None)
    return (time(9, 30) <= current < time(11, 30)) or (
        time(13, 0) <= current < time(14, 57)
    )


def _quote_to_sample(quote: Any) -> Dict[str, Any]:
    return {
        "price": _safe_float(getattr(quote, "price", None)),
        "open_price": _safe_float(getattr(quote, "open_price", None)),
        "amount": _safe_float(getattr(quote, "amount", None)),
        "volume": _safe_int(getattr(quote, "volume", None)),
    }


def _pattern_for(
    code: str,
    quote: Any,
    samples: Sequence[Dict[str, Any]],
) -> Tuple[str, Optional[float], Optional[float]]:
    """Classify recent three-minute amount flow and price behaviour."""
    if len(samples) < SAMPLE_WINDOW:
        return "warming_up", None, None

    current = _quote_to_sample(quote)
    series = [item.get("quotes", {}).get(code, {}) for item in samples]
    series.append(current)
    if len(series) < SAMPLE_WINDOW + 1:
        return "warming_up", None, None

    recent_anchor = series[-7]
    previous_anchor = series[-13] if len(series) >= 13 else None
    if previous_anchor is None:
        return "warming_up", None, None

    amount_now = current.get("amount")
    recent_amount = recent_anchor.get("amount")
    previous_amount = previous_anchor.get("amount")
    price_now = current.get("price")
    price_anchor = recent_anchor.get("price")
    if None in (amount_now, recent_amount, previous_amount, price_now, price_anchor):
        return "data_unavailable", None, None

    recent_flow = max(0.0, float(amount_now) - float(recent_amount))
    previous_flow = max(0.0, float(recent_amount) - float(previous_amount))
    price_delta = float(price_now) - float(price_anchor)
    if recent_flow > 0 and price_delta >= 0 and (previous_flow <= 0 or recent_flow >= previous_flow):
        return "attack_with_volume", recent_flow, previous_flow

    if recent_flow > 0 and price_delta < 0 and recent_flow <= previous_flow:
        return "pullback_contracted", recent_flow, previous_flow

    if recent_flow > 0 and price_delta >= 0:
        return "steady", recent_flow, previous_flow

    return "weak", recent_flow, previous_flow


class IntradayMonitorService:
    """Evaluate plans and persist only meaningful state transitions."""

    def __init__(
        self,
        repository: Optional[IntradayMonitorRepository] = None,
        fetcher_manager: Optional[DataFetcherManager] = None,
    ):
        self.repository = repository or IntradayMonitorRepository()
        self.fetcher_manager = fetcher_manager or DataFetcherManager()

    @staticmethod
    def validate_plan_fields(fields: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
        normalized = dict(fields)
        if not partial or "name" in normalized:
            if not str(normalized.get("name") or "").strip():
                raise IntradayMonitorValidationError("name is required")
            normalized["name"] = str(normalized["name"]).strip()[:128]

        for key in ("event_symbol", "sector_symbol"):
            if not partial or key in normalized:
                value = normalize_stock_code(str(normalized.get(key) or "").strip())
                if not value:
                    raise IntradayMonitorValidationError(f"{key} is required")
                normalized[key] = value

        if not partial or "monitored_symbols" in normalized:
            symbols = normalized.get("monitored_symbols") or []
            if isinstance(symbols, str):
                symbols = [item.strip() for item in symbols.split(",")]
            normalized["monitored_symbols"] = clean_symbols(symbols)
            if not normalized["monitored_symbols"]:
                raise IntradayMonitorValidationError("monitored_symbols must contain at least one symbol")

        if not partial or "majority_ratio" in normalized:
            ratio = float(normalized.get("majority_ratio", 0.6))
            if not 0 < ratio <= 1:
                raise IntradayMonitorValidationError("majority_ratio must be between 0 and 1")
            normalized["majority_ratio"] = ratio

        for key, default in (("initial_time", "10:00"), ("confirm_time", "10:30")):
            if not partial or key in normalized:
                value = str(normalized.get(key) or default)
                parse_clock(value, key)
                normalized[key] = value
        if "initial_time" in normalized and "confirm_time" in normalized:
            if parse_clock(normalized["confirm_time"], "confirm_time") < parse_clock(normalized["initial_time"], "initial_time"):
                raise IntradayMonitorValidationError("confirm_time must not be earlier than initial_time")

        if not partial or "poll_interval_seconds" in normalized:
            interval = int(normalized.get("poll_interval_seconds", DEFAULT_POLL_SECONDS))
            if not 10 <= interval <= 300:
                raise IntradayMonitorValidationError("poll_interval_seconds must be between 10 and 300")
            normalized["poll_interval_seconds"] = interval

        for key in ("start_date", "end_date"):
            if key in normalized and normalized[key] is not None and not isinstance(normalized[key], date):
                try:
                    normalized[key] = date.fromisoformat(str(normalized[key]))
                except ValueError:
                    raise IntradayMonitorValidationError(f"{key} must use YYYY-MM-DD format")
        if normalized.get("start_date") and normalized.get("end_date"):
            if normalized["end_date"] < normalized["start_date"]:
                raise IntradayMonitorValidationError("end_date must not be earlier than start_date")
        if "listing_day_mode" in normalized:
            normalized["listing_day_mode"] = bool(normalized["listing_day_mode"])
        return normalized

    def create_plan(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self.validate_plan_fields(fields)
        if isinstance(normalized.get("monitored_symbols"), list):
            normalized["monitored_symbols"] = json.dumps(normalized["monitored_symbols"], ensure_ascii=False)
        row = self.repository.create_plan(normalized)
        return self.plan_to_dict(row)

    def update_plan(self, plan_id: int, fields: Dict[str, Any]) -> Dict[str, Any]:
        existing = self.repository.get_plan(plan_id)
        if existing is None:
            raise KeyError(f"Intraday monitor plan not found: {plan_id}")
        merged = {
            "name": existing.name,
            "event_symbol": existing.event_symbol,
            "sector_symbol": existing.sector_symbol,
            "monitored_symbols": self._parse_symbols(existing),
            "majority_ratio": existing.majority_ratio,
            "initial_time": existing.initial_time,
            "confirm_time": existing.confirm_time,
            "poll_interval_seconds": existing.poll_interval_seconds,
            "listing_day_mode": existing.listing_day_mode,
            "start_date": existing.start_date,
            "end_date": existing.end_date,
            "enabled": existing.enabled,
            "paused": existing.paused,
        }
        merged.update(fields)
        validated = self.validate_plan_fields(merged)
        normalized = {key: validated[key] for key in fields if key in validated}
        if "monitored_symbols" in normalized:
            normalized["monitored_symbols"] = json.dumps(normalized["monitored_symbols"], ensure_ascii=False)
        row = self.repository.update_plan(plan_id, normalized)
        if row is None:  # repository can race with deletion
            raise KeyError(f"Intraday monitor plan not found: {plan_id}")
        return self.plan_to_dict(row)

    def set_enabled(self, plan_id: int, enabled: bool) -> Dict[str, Any]:
        row = self.repository.update_plan(plan_id, {"enabled": enabled})
        if row is None:
            raise KeyError(f"Intraday monitor plan not found: {plan_id}")
        return self.plan_to_dict(row)

    def set_paused(self, plan_id: int, paused: bool) -> Dict[str, Any]:
        row = self.repository.update_plan(plan_id, {"paused": paused})
        if row is None:
            raise KeyError(f"Intraday monitor plan not found: {plan_id}")
        return self.plan_to_dict(row)

    def delete_plan(self, plan_id: int) -> bool:
        return self.repository.delete_plan(plan_id)

    @staticmethod
    def _parse_symbols(row: IntradayMonitorPlanRecord) -> List[str]:
        try:
            values = json.loads(row.monitored_symbols or "[]")
        except (TypeError, json.JSONDecodeError):
            values = []
        return clean_symbols(values if isinstance(values, list) else [])

    @staticmethod
    def _parse_snapshot(row: IntradayMonitorPlanRecord) -> Dict[str, Any]:
        try:
            value = json.loads(row.current_snapshot or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    @classmethod
    def plan_to_dict(cls, row: IntradayMonitorPlanRecord) -> Dict[str, Any]:
        snapshot = cls._parse_snapshot(row)
        return {
            "id": row.id,
            "name": row.name,
            "event_symbol": row.event_symbol,
            "sector_symbol": row.sector_symbol,
            "monitored_symbols": cls._parse_symbols(row),
            "majority_ratio": row.majority_ratio,
            "required_count": required_breadth(len(cls._parse_symbols(row)), row.majority_ratio),
            "initial_time": row.initial_time,
            "confirm_time": row.confirm_time,
            "poll_interval_seconds": row.poll_interval_seconds,
            "listing_day_mode": row.listing_day_mode,
            "start_date": row.start_date.isoformat() if row.start_date else None,
            "end_date": row.end_date.isoformat() if row.end_date else None,
            "enabled": row.enabled,
            "paused": row.paused,
            "current_status": row.current_status,
            "last_evaluated_at": row.last_evaluated_at.isoformat() if row.last_evaluated_at else None,
            "snapshot": snapshot,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def list_plans(self) -> List[Dict[str, Any]]:
        return [self.plan_to_dict(row) for row in self.repository.list_plans()]

    def get_plan(self, plan_id: int) -> Dict[str, Any]:
        row = self.repository.get_plan(plan_id)
        if row is None:
            raise KeyError(f"Intraday monitor plan not found: {plan_id}")
        return self.plan_to_dict(row)

    def get_history(self, plan_id: int, *, days: int = DEFAULT_HISTORY_DAYS) -> List[Dict[str, Any]]:
        return [
            {
                "id": row.id,
                "plan_id": row.plan_id,
                "status": row.status,
                "reason": row.reason,
                "values": self._load_json(row.values_json),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in self.repository.list_history(plan_id, days=days)
        ]

    def simulate_plan(self, plan_id: int) -> Dict[str, Any]:
        """Run a deterministic dry-run without changing the real plan state."""
        row = self.repository.get_plan(plan_id)
        if row is None:
            raise KeyError(f"Intraday monitor plan not found: {plan_id}")

        simulation_plan = SimpleNamespace(
            **{
                key: getattr(row, key)
                for key in (
                    "id", "name", "event_symbol", "sector_symbol", "monitored_symbols",
                    "majority_ratio", "initial_time", "confirm_time", "poll_interval_seconds",
                    "listing_day_mode", "start_date", "end_date", "enabled", "paused",
                )
            },
            current_status=STATUS_OBSERVE,
            current_snapshot="{}",
            last_evaluated_at=None,
        )
        simulation_repo = _SimulationRepository(simulation_plan)
        simulation_fetcher = _SimulationFetcher()
        simulation_service = IntradayMonitorService(
            repository=simulation_repo,
            fetcher_manager=simulation_fetcher,
        )

        timeline = [
            datetime(2026, 7, 27, 9, 54, 0, tzinfo=CN_TZ) + timedelta(seconds=30 * index)
            for index in range(12)
        ]
        timeline.extend(
            [
                datetime(2026, 7, 27, 10, 0, 0, tzinfo=CN_TZ),
                datetime(2026, 7, 27, 10, 0, 30, tzinfo=CN_TZ),
                datetime(2026, 7, 27, 10, 29, 30, tzinfo=CN_TZ),
                datetime(2026, 7, 27, 10, 30, 0, tzinfo=CN_TZ),
                datetime(2026, 7, 27, 10, 30, 30, tzinfo=CN_TZ),
                datetime(2026, 7, 27, 10, 31, 0, tzinfo=CN_TZ),
                datetime(2026, 7, 27, 10, 31, 30, tzinfo=CN_TZ),
                datetime(2026, 7, 27, 10, 32, 0, tzinfo=CN_TZ),
            ]
        )
        failure_index = len(timeline) - 3
        steps: List[Dict[str, Any]] = []
        transitions: List[Dict[str, Any]] = []
        previous_status: Optional[str] = None
        for index, timestamp in enumerate(timeline):
            simulation_fetcher.step = index
            simulation_fetcher.failure = index == failure_index
            snapshot = simulation_service.evaluate_plan(simulation_plan, now=timestamp)
            step = {
                "as_of": timestamp.isoformat(),
                "status": snapshot.get("status"),
                "reason": snapshot.get("reason"),
                "breadth": snapshot.get("breadth", {}),
                "trigger_values": snapshot.get("trigger_values", {}),
                "event": snapshot.get("event", {}),
                "sector": snapshot.get("sector", {}),
            }
            steps.append(step)
            if step["status"] != previous_status:
                transitions.append(step)
                previous_status = step["status"]

        expected = [STATUS_CONTINUE, STATUS_PRELIMINARY, STATUS_CONFIRMED, STATUS_INVALIDATED, STATUS_CONTINUE, STATUS_CONFIRMED]
        transition_statuses = [item["status"] for item in transitions]
        return {
            "plan_id": plan_id,
            "mode": "simulation",
            "as_of": timeline[-1].isoformat(),
            "passed": all(status in transition_statuses for status in expected),
            "expected_statuses": expected,
            "transition_statuses": transition_statuses,
            "transitions": transitions,
            "steps": steps,
            "message": "模拟行情未调用真实数据源，也未写入真实方案状态。",
        }

    @staticmethod
    def _load_json(value: Optional[str]) -> Dict[str, Any]:
        try:
            result = json.loads(value or "{}")
            return result if isinstance(result, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    def _is_plan_in_date_range(self, row: IntradayMonitorPlanRecord, today: date) -> bool:
        return not ((row.start_date and today < row.start_date) or (row.end_date and today > row.end_date))

    def _fetch_quotes(self, symbols: Sequence[str]) -> Dict[str, Any]:
        quotes: Dict[str, Any] = {}
        workers = min(8, max(1, len(symbols)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="intraday-quote") as executor:
            futures = {
                executor.submit(
                    self.fetcher_manager.get_realtime_quote,
                    symbol,
                    log_final_failure=False,
                ): symbol
                for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    quote = future.result()
                    if quote is not None:
                        quotes[symbol] = quote
                except Exception as exc:  # provider fallback must not kill the monitor
                    logger.warning("[intraday-monitor] quote failed code=%s reason=%s", symbol, exc)
        return quotes

    @staticmethod
    def _instrument(code: str, quote: Any, samples: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        price = _safe_float(getattr(quote, "price", None))
        open_price = _safe_float(getattr(quote, "open_price", None))
        amount = _safe_float(getattr(quote, "amount", None))
        volume = _safe_int(getattr(quote, "volume", None))
        turnover_rate = _safe_float(getattr(quote, "turnover_rate", None))
        pattern, recent_flow, previous_flow = _pattern_for(code, quote, samples)
        fields_missing = []
        if price is None:
            fields_missing.append("price")
        if open_price is None:
            fields_missing.append("open_price")
        if amount is None:
            fields_missing.append("amount")
        valid = not fields_missing and price > open_price and pattern in PATTERN_OK
        return {
            "code": code,
            "name": str(getattr(quote, "name", "") or code),
            "price": price,
            "change_pct": _safe_float(getattr(quote, "change_pct", None)),
            "open_price": open_price,
            "amount": amount,
            "volume": volume,
            "turnover_rate": turnover_rate,
            "pattern": pattern,
            "recent_flow": recent_flow,
            "previous_flow": previous_flow,
            "above_open": bool(price is not None and open_price is not None and price > open_price),
            "valid": valid,
            "fields_missing": fields_missing,
            "data_source": _source_name(quote),
            "fetched_at": getattr(quote, "fetched_at", None),
            "provider_timestamp": getattr(quote, "provider_timestamp", None),
            "is_stale": getattr(quote, "is_stale", None),
        }

    @staticmethod
    def _phase_for(row: IntradayMonitorPlanRecord, now: datetime) -> Tuple[str, bool, bool]:
        phase = market_phase(now)
        initial = parse_clock(row.initial_time, "initial_time")
        confirm = parse_clock(row.confirm_time, "confirm_time")
        current = now.timetz().replace(tzinfo=None)
        return phase, current >= initial, current >= confirm

    def _build_snapshot(self, row: IntradayMonitorPlanRecord, now: datetime) -> Dict[str, Any]:
        symbols = self._parse_symbols(row)
        event_symbol = normalize_stock_code(row.event_symbol)
        sector_symbol = normalize_stock_code(row.sector_symbol)
        all_symbols = clean_symbols([event_symbol, sector_symbol, *symbols])
        previous = self._parse_snapshot(row)
        old_samples = previous.get("samples", [])
        old_samples = old_samples if isinstance(old_samples, list) else []
        quotes = self._fetch_quotes(all_symbols)
        sample_quotes = {code: _quote_to_sample(quote) for code, quote in quotes.items()}
        samples = [*old_samples, {"as_of": now.isoformat(), "quotes": sample_quotes}][-SAMPLE_WINDOW:]

        event = self._instrument(event_symbol, quotes[event_symbol], samples) if event_symbol in quotes else {
            "code": event_symbol,
            "name": event_symbol,
            "valid": False,
            "fields_missing": ["quote"],
            "data_source": None,
        }
        sector = self._instrument(sector_symbol, quotes[sector_symbol], samples) if sector_symbol in quotes else {
            "code": sector_symbol,
            "name": sector_symbol,
            "valid": False,
            "fields_missing": ["quote"],
            "data_source": None,
        }
        markers = [
            self._instrument(code, quotes[code], samples)
            if code in quotes
            else {
                "code": code,
                "name": code,
                "valid": False,
                "fields_missing": ["quote"],
                "data_source": None,
            }
            for code in symbols
        ]
        required = required_breadth(len(markers), row.majority_ratio)
        strong_count = sum(1 for marker in markers if marker.get("valid"))
        complete = not any(item.get("fields_missing") for item in [event, sector, *markers])
        breadth_valid = complete and strong_count >= required
        all_valid = complete and bool(event.get("valid")) and bool(sector.get("valid")) and breadth_valid

        streak = int(previous.get("streak") or 0)
        streak = streak + 1 if all_valid else 0
        phase, initial_reached, confirm_reached = self._phase_for(row, now)
        previous_status = row.current_status or STATUS_OBSERVE
        if not complete:
            status = STATUS_INSUFFICIENT
            reason = "长鑫或159516或监控池数据不完整，暂停综合统计，不产生买入/失效信号"
        elif not initial_reached:
            status = STATUS_OBSERVE
            reason = f"等待{row.initial_time}后的首个有效观察窗口"
        elif not all_valid or streak < MIN_STREAK:
            status = STATUS_INVALIDATED if previous_status == STATUS_CONFIRMED and not all_valid else STATUS_CONTINUE
            reason = "三层条件未同时满足，继续观察；已确认信号暂不追高" if status != STATUS_INVALIDATED else "确认后长鑫、ETF或多数标的转弱，信号失效"
        elif confirm_reached:
            status = STATUS_CONFIRMED
            reason = f"长鑫、159516及监控池至少{required}/{len(markers)}同时满足价格与3分钟量价结构"
        else:
            status = STATUS_PRELIMINARY
            reason = f"初步信号：三层条件满足，等待{row.confirm_time}确认"

        sources = sorted({item.get("data_source") for item in [event, sector, *markers] if item.get("data_source")})
        snapshot = {
            "status": status,
            "phase": phase,
            "as_of": now.isoformat(),
            "data_quality": "ok" if complete else "partial",
            "data_sources": sources,
            "event": event,
            "sector": sector,
            "breadth": {
                "total": len(markers),
                "available": sum(1 for marker in markers if "quote" not in marker.get("fields_missing", [])),
                "strong": strong_count,
                "required": required,
                "ratio": strong_count / len(markers) if markers else 0,
                "valid": breadth_valid,
            },
            "markers": markers,
            "trigger_values": {
                "event_above_open": event.get("above_open", False),
                "sector_above_open": sector.get("above_open", False),
                "strong_count": strong_count,
                "required_count": required,
                "streak": streak,
                "initial_reached": initial_reached,
                "confirm_reached": confirm_reached,
            },
            "streak": streak,
            "reason": reason,
            "samples": samples,
        }
        return snapshot

    def evaluate_plan(self, row: IntradayMonitorPlanRecord, *, now: Optional[datetime] = None) -> Dict[str, Any]:
        current = now or datetime.now(CN_TZ)
        today = current.date()
        if not self._is_plan_in_date_range(row, today):
            snapshot = {
                "status": STATUS_INACTIVE,
                "phase": "outside_effective_date",
                "as_of": current.isoformat(),
                "data_quality": "unavailable",
                "reason": "不在方案有效日期内",
                "trigger_values": {},
                "samples": self._parse_snapshot(row).get("samples", []),
            }
            self.repository.update_state(row.id, status=STATUS_INACTIVE, snapshot_json=json.dumps(snapshot, ensure_ascii=False), evaluated_at=current.replace(tzinfo=None))
            return snapshot

        if not is_continuous_auction(current):
            previous = self._parse_snapshot(row)
            snapshot = dict(previous) if previous else {
                "status": row.current_status or STATUS_OBSERVE,
                "data_quality": "unavailable",
                "reason": "等待连续竞价时段",
                "trigger_values": {},
                "samples": [],
            }
            snapshot.update({"as_of": current.isoformat(), "phase": market_phase(current)})
            self.repository.update_state(row.id, status=snapshot.get("status", row.current_status), snapshot_json=json.dumps(snapshot, ensure_ascii=False), evaluated_at=current.replace(tzinfo=None))
            return snapshot

        snapshot = self._build_snapshot(row, current)
        previous_status = row.current_status or STATUS_OBSERVE
        status = snapshot["status"]
        self.repository.update_state(
            row.id,
            status=status,
            snapshot_json=json.dumps(snapshot, ensure_ascii=False),
            evaluated_at=current.replace(tzinfo=None),
        )
        if status != previous_status:
            history_values = dict(snapshot)
            history_values.pop("samples", None)
            self.repository.create_history(
                {
                    "plan_id": row.id,
                    "status": status,
                    "reason": snapshot.get("reason"),
                    "values_json": json.dumps(history_values, ensure_ascii=False),
                    "created_at": current.replace(tzinfo=None),
                }
            )
        return snapshot

    def run_cycle(self, *, now: Optional[datetime] = None) -> int:
        current = now or datetime.now(CN_TZ)
        plans = self.repository.list_active_plans()
        evaluated = 0
        for row in plans:
            try:
                self.evaluate_plan(row, now=current)
                evaluated += 1
            except Exception as exc:  # one plan must not stop other plans
                logger.exception("[intraday-monitor] plan evaluation failed id=%s: %s", row.id, exc)
        self.repository.purge_old_history(days=DEFAULT_HISTORY_DAYS)
        return evaluated

    async def run_forever(self) -> None:
        """Background loop; it is intentionally a no-op when no plan is enabled."""
        import asyncio

        while True:
            try:
                interval = DEFAULT_POLL_SECONDS
                plans = self.repository.list_active_plans()
                if plans:
                    interval = max(10, min(row.poll_interval_seconds or DEFAULT_POLL_SECONDS for row in plans))
                    await asyncio.to_thread(self.run_cycle)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # background monitoring is best effort
                logger.exception("[intraday-monitor] background cycle failed: %s", exc)
                await asyncio.sleep(DEFAULT_POLL_SECONDS)


class _SimulationQuote:
    """Minimal quote object matching the fields consumed by the monitor."""

    def __init__(self, code: str, *, price: float, amount: float):
        self.code = code
        self.name = {
            "688825": "长鑫科技",
            "159516": "半导体材料设备 ETF",
        }.get(code, code)
        self.source = "simulation"
        self.price = price
        self.open_price = 100.0
        self.change_pct = price - 100.0
        self.amount = amount
        self.volume = int(amount / 100)
        self.turnover_rate = 5.0
        self.fetched_at = "2026-07-27T10:32:00+08:00"
        self.provider_timestamp = self.fetched_at
        self.is_stale = False


class _SimulationFetcher:
    """Deterministic source used only by ``simulate_plan``."""

    def __init__(self):
        self.step = 0
        self.failure = False

    def get_realtime_quote(self, code: str, *, log_final_failure: bool = False) -> _SimulationQuote:
        del log_final_failure
        base_price = 101.0 + self.step * 0.05
        if self.failure and code == "688825":
            base_price = 99.0
        return _SimulationQuote(
            code,
            price=base_price,
            amount=1_000_000.0 + self.step * 100_000.0,
        )


class _SimulationRepository:
    """In-memory repository so dry-runs cannot alter the real database."""

    def __init__(self, plan: Any):
        self.plan = plan
        self.history: List[Dict[str, Any]] = []

    def get_plan(self, plan_id: int) -> Optional[Any]:
        return self.plan if self.plan.id == plan_id else None

    def update_state(
        self,
        plan_id: int,
        *,
        status: str,
        snapshot_json: str,
        evaluated_at: datetime,
    ) -> Optional[Any]:
        if self.plan.id != plan_id:
            return None
        self.plan.current_status = status
        self.plan.current_snapshot = snapshot_json
        self.plan.last_evaluated_at = evaluated_at
        return self.plan

    def create_history(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        self.history.append(fields)
        return fields
