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
PATTERN_WINDOW = timedelta(minutes=3)
SAMPLE_RETENTION = timedelta(minutes=8)
SAMPLE_ANCHOR_TOLERANCE = timedelta(seconds=90)
MAX_QUOTE_AGE_SECONDS = 90
PATTERN_OK = {"attack_with_volume", "pullback_contracted", "steady"}
REPRESENTATIVE_MIN_GROUPS = 2

# Default groups only apply to the bundled 长鑫/半导体设备材料 monitor pool.
# They are deliberately based on industry role rather than intraday momentum so
# the monitor never promotes a stock to "representative" just because it is
# temporarily leading the tape.
DEFAULT_REPRESENTATIVE_GROUPS = (
    {
        "key": "equipment",
        "label": "设备",
        "core_symbols": ("002371", "603690"),
        "backup_symbols": ("603283", "603929", "603163"),
    },
    {
        "key": "components",
        "label": "关键零部件",
        "core_symbols": ("688409", "300260"),
        "backup_symbols": ("688596",),
    },
    {
        "key": "materials",
        "label": "材料",
        "core_symbols": ("603688", "002409", "600206"),
        "backup_symbols": (
            "603650", "688019", "300054", "300666", "688126",
            "688268", "688106", "605358",
        ),
    },
)

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


def _default_representative_groups(symbols: Sequence[str]) -> List[Dict[str, Any]]:
    """Return the default three-way structure only for a compatible pool."""
    available = set(clean_symbols(symbols))
    groups: List[Dict[str, Any]] = []
    for template in DEFAULT_REPRESENTATIVE_GROUPS:
        core_symbols = [code for code in template["core_symbols"] if code in available]
        if not core_symbols:
            continue
        groups.append(
            {
                "key": template["key"],
                "label": template["label"],
                "core_symbols": core_symbols,
                "backup_symbols": [
                    code for code in template["backup_symbols"] if code in available
                ],
            }
        )
    # Do not apply a partial default structure to an unrelated custom pool.
    return groups if len(groups) == len(DEFAULT_REPRESENTATIVE_GROUPS) else []


def _normalise_representative_groups(
    values: Any,
    monitored_symbols: Optional[Sequence[str]],
    *,
    use_default_when_unspecified: bool = False,
) -> List[Dict[str, Any]]:
    """Validate the persistent industry-role configuration for a plan."""
    allowed = set(clean_symbols(monitored_symbols or [])) if monitored_symbols is not None else None
    if values is None:
        return _default_representative_groups(monitored_symbols or []) if use_default_when_unspecified else []
    if not isinstance(values, list):
        raise IntradayMonitorValidationError("representative_groups must be a list")

    groups: List[Dict[str, Any]] = []
    seen_keys = set()
    assigned_symbols = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise IntradayMonitorValidationError("each representative group must be an object")
        label = str(value.get("label") or "").strip()[:32]
        if not label:
            raise IntradayMonitorValidationError("representative group label is required")
        key = str(value.get("key") or f"group_{index + 1}").strip()[:48]
        if not key or key in seen_keys:
            raise IntradayMonitorValidationError("representative group keys must be unique")
        seen_keys.add(key)
        core_symbols = clean_symbols(value.get("core_symbols") or [])
        backup_symbols = clean_symbols(value.get("backup_symbols") or [])
        if not core_symbols:
            raise IntradayMonitorValidationError(
                "each representative group must contain at least one core symbol"
            )
        overlap = set(core_symbols) & set(backup_symbols)
        if overlap:
            raise IntradayMonitorValidationError(
                "representative group core_symbols and backup_symbols must not overlap"
            )
        repeated_group_symbols = sorted(set([*core_symbols, *backup_symbols]) & assigned_symbols)
        if repeated_group_symbols:
            raise IntradayMonitorValidationError(
                "a representative symbol can belong to only one industry group: "
                + ", ".join(repeated_group_symbols)
            )
        assigned_symbols.update(core_symbols)
        assigned_symbols.update(backup_symbols)
        if allowed is not None:
            outside_pool = sorted(set([*core_symbols, *backup_symbols]) - allowed)
            if outside_pool:
                raise IntradayMonitorValidationError(
                    "representative group symbols must be included in monitored_symbols: "
                    + ", ".join(outside_pool)
                )
        groups.append(
            {
                "key": key,
                "label": label,
                "core_symbols": core_symbols,
                "backup_symbols": backup_symbols,
            }
        )
    return groups


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


def _parse_market_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO timestamp and normalize it to the mainland market timezone."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=CN_TZ)
    return parsed.astimezone(CN_TZ)


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


def _trim_samples(samples: Sequence[Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    cutoff = now - SAMPLE_RETENTION
    retained: List[Dict[str, Any]] = []
    for item in samples:
        sampled_at = _parse_market_timestamp(item.get("as_of")) if isinstance(item, dict) else None
        if sampled_at is not None and sampled_at >= cutoff:
            retained.append(item)
    return retained


def _sample_near(
    code: str,
    samples: Sequence[Dict[str, Any]],
    target: datetime,
) -> Optional[Dict[str, Any]]:
    """Return the valid sample nearest a rolling-window anchor.

    A full monitoring-pool refresh can take longer than its nominal polling
    interval. Restricting the lookup to samples strictly before an anchor
    turns a small scheduling delay into a permanent ``warming_up`` state. A
    sample on either side of the historical anchor is valid when it remains
    inside the existing tolerance. Ties prefer the earlier sample to keep the
    comparison conservative.
    """
    candidate: Optional[Tuple[timedelta, bool, Dict[str, Any]]] = None
    for item in samples:
        sampled_at = _parse_market_timestamp(item.get("as_of")) if isinstance(item, dict) else None
        quotes = item.get("quotes") if isinstance(item, dict) else None
        quote = quotes.get(code) if isinstance(quotes, dict) else None
        if sampled_at is None or not isinstance(quote, dict):
            continue
        distance = abs(sampled_at - target)
        if distance > SAMPLE_ANCHOR_TOLERANCE:
            continue
        is_before = sampled_at <= target
        if candidate is None or (distance, not is_before) < (candidate[0], not candidate[1]):
            candidate = (distance, is_before, quote)
    if candidate is None:
        return None
    return candidate[2]


def _quote_freshness(quote: Any, now: datetime) -> Dict[str, Any]:
    """Keep stale quotes from affecting a confirmation signal.

    Some providers do not expose a provider timestamp.  A newly fetched quote
    from those sources remains usable, but the snapshot marks its freshness as
    unknown so the page can make that limitation visible.
    """
    source_stale = getattr(quote, "is_stale", None)
    provider_timestamp = getattr(quote, "provider_timestamp", None)
    fetched_at = getattr(quote, "fetched_at", None)
    provider_time = _parse_market_timestamp(provider_timestamp)
    fetched_time = _parse_market_timestamp(fetched_at)
    timestamp = provider_time or fetched_time
    timestamp_source = "provider_timestamp" if provider_time else ("fetched_at" if fetched_time else None)
    age_seconds: Optional[int] = None
    if timestamp is not None:
        age_seconds = max(0, int((now - timestamp).total_seconds()))

    if source_stale is True:
        return {
            "usable": False,
            "status": "stale",
            "reason": "source_marked_stale",
            "age_seconds": age_seconds,
            "timestamp_source": timestamp_source,
        }
    if age_seconds is not None and age_seconds > MAX_QUOTE_AGE_SECONDS:
        return {
            "usable": False,
            "status": "stale",
            "reason": "quote_age_exceeded",
            "age_seconds": age_seconds,
            "timestamp_source": timestamp_source,
        }
    if provider_time is None:
        return {
            "usable": True,
            "status": "unknown",
            "reason": "provider_timestamp_unavailable",
            "age_seconds": age_seconds,
            "timestamp_source": timestamp_source,
        }
    return {
        "usable": True,
        "status": "fresh",
        "reason": None,
        "age_seconds": age_seconds,
        "timestamp_source": timestamp_source,
    }


def _pattern_for(
    code: str,
    quote: Any,
    samples: Sequence[Dict[str, Any]],
    now: datetime,
) -> Tuple[str, Optional[float], Optional[float]]:
    """Classify recent three-minute amount flow and price behaviour."""
    current = _quote_to_sample(quote)
    recent_anchor = _sample_near(code, samples, now - PATTERN_WINDOW)
    previous_anchor = _sample_near(code, samples, now - PATTERN_WINDOW * 2)
    if recent_anchor is None or previous_anchor is None:
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

        if not partial or "representative_groups" in normalized:
            normalized["representative_groups"] = _normalise_representative_groups(
                normalized.get("representative_groups"),
                normalized.get("monitored_symbols"),
                use_default_when_unspecified=not partial,
            )

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
            normalized["monitored_symbols"] = json.dumps(
                self._serialize_monitor_config(
                    normalized["monitored_symbols"],
                    normalized.get("representative_groups", []),
                ),
                ensure_ascii=False,
            )
        normalized.pop("representative_groups", None)
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
            "representative_groups": self._parse_representative_groups(existing),
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
        if {"monitored_symbols", "representative_groups"} & set(normalized):
            normalized["monitored_symbols"] = json.dumps(
                self._serialize_monitor_config(
                    validated["monitored_symbols"],
                    validated["representative_groups"],
                ),
                ensure_ascii=False,
            )
            normalized.pop("representative_groups", None)
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
    def _serialize_monitor_config(
        symbols: Sequence[str],
        representative_groups: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "symbols": clean_symbols(symbols),
            "representative_groups": list(representative_groups),
        }

    @staticmethod
    def _parse_monitor_config(row: IntradayMonitorPlanRecord) -> Dict[str, Any]:
        try:
            value = json.loads(row.monitored_symbols or "[]")
        except (TypeError, json.JSONDecodeError):
            value = []
        if isinstance(value, list):
            return {
                "symbols": clean_symbols(value),
                "representative_groups": None,
                "representative_groups_source": "legacy",
            }
        if not isinstance(value, dict):
            return {
                "symbols": [],
                "representative_groups": [],
                "representative_groups_source": "invalid",
            }
        symbols = value.get("symbols", value.get("monitored_symbols", []))
        groups = value.get("representative_groups")
        return {
            "symbols": clean_symbols(symbols if isinstance(symbols, list) else []),
            "representative_groups": groups,
            "representative_groups_source": "configured" if "representative_groups" in value else "legacy",
        }

    @classmethod
    def _parse_symbols(cls, row: IntradayMonitorPlanRecord) -> List[str]:
        return cls._parse_monitor_config(row)["symbols"]

    @classmethod
    def _parse_representative_groups(cls, row: IntradayMonitorPlanRecord) -> List[Dict[str, Any]]:
        config = cls._parse_monitor_config(row)
        try:
            return _normalise_representative_groups(
                config["representative_groups"],
                config["symbols"],
                use_default_when_unspecified=config["representative_groups"] is None,
            )
        except IntradayMonitorValidationError:
            logger.warning("[intraday-monitor] ignore invalid representative group config id=%s", row.id)
            return []

    @classmethod
    def _representative_groups_source(cls, row: IntradayMonitorPlanRecord) -> str:
        config = cls._parse_monitor_config(row)
        if config["representative_groups"] is None:
            return "default" if cls._parse_representative_groups(row) else "none"
        return config["representative_groups_source"]

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
        monitored_symbols = cls._parse_symbols(row)
        return {
            "id": row.id,
            "name": row.name,
            "event_symbol": row.event_symbol,
            "sector_symbol": row.sector_symbol,
            "monitored_symbols": monitored_symbols,
            "representative_groups": cls._parse_representative_groups(row),
            "representative_groups_source": cls._representative_groups_source(row),
            "majority_ratio": row.majority_ratio,
            "required_count": required_breadth(len(monitored_symbols), row.majority_ratio),
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

        timeline_start = datetime(2026, 7, 27, 9, 54, 0, tzinfo=CN_TZ)
        timeline_end = datetime(2026, 7, 27, 10, 32, 0, tzinfo=CN_TZ)
        timeline = []
        timestamp = timeline_start
        while timestamp <= timeline_end:
            timeline.append(timestamp)
            timestamp += timedelta(seconds=30)
        failure_index = timeline.index(datetime(2026, 7, 27, 10, 31, 0, tzinfo=CN_TZ))
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
                "representative_coverage": snapshot.get("representative_coverage", {}),
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
    def _instrument(
        code: str,
        quote: Any,
        samples: Sequence[Dict[str, Any]],
        now: datetime,
    ) -> Dict[str, Any]:
        price = _safe_float(getattr(quote, "price", None))
        open_price = _safe_float(getattr(quote, "open_price", None))
        amount = _safe_float(getattr(quote, "amount", None))
        volume = _safe_int(getattr(quote, "volume", None))
        turnover_rate = _safe_float(getattr(quote, "turnover_rate", None))
        pattern, recent_flow, previous_flow = _pattern_for(code, quote, samples, now)
        freshness = _quote_freshness(quote, now)
        fields_missing = []
        if price is None:
            fields_missing.append("price")
        if open_price is None:
            fields_missing.append("open_price")
        if amount is None:
            fields_missing.append("amount")
        data_issues = list(fields_missing)
        if not freshness["usable"]:
            data_issues.append(str(freshness["reason"] or "stale_quote"))
        valid = not data_issues and price > open_price and pattern in PATTERN_OK
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
            "data_issues": data_issues,
            "data_source": _source_name(quote),
            "fetched_at": getattr(quote, "fetched_at", None),
            "provider_timestamp": getattr(quote, "provider_timestamp", None),
            "is_stale": freshness["status"] == "stale",
            "source_is_stale": getattr(quote, "is_stale", None),
            "freshness": freshness["status"],
            "is_fresh": freshness["usable"],
            "quote_age_seconds": freshness["age_seconds"],
            "freshness_reason": freshness["reason"],
            "freshness_timestamp_source": freshness["timestamp_source"],
        }

    @staticmethod
    def _representative_coverage(
        groups: Sequence[Dict[str, Any]],
        markers: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Evaluate whether strength spans distinct upstream industry roles.

        A backup may stand in only when *all* core representatives in that
        direction have unusable data.  A weak core representative is never
        replaced by a hot backup stock, which prevents circular selection.
        """
        markers_by_code = {str(item.get("code")): item for item in markers}
        marker_roles: Dict[str, List[str]] = {}
        snapshots: List[Dict[str, Any]] = []
        for group in groups:
            label = str(group.get("label") or group.get("key") or "代表组")
            core_symbols = clean_symbols(group.get("core_symbols") or [])
            backup_symbols = clean_symbols(group.get("backup_symbols") or [])
            core_markers = [markers_by_code[code] for code in core_symbols if code in markers_by_code]
            backup_markers = [markers_by_code[code] for code in backup_symbols if code in markers_by_code]
            for code in core_symbols:
                marker_roles.setdefault(code, []).append(f"{label}·核心")
            for code in backup_symbols:
                marker_roles.setdefault(code, []).append(f"{label}·备用")

            core_valid_codes = [item["code"] for item in core_markers if item.get("valid")]
            backup_valid_codes = [item["code"] for item in backup_markers if item.get("valid")]
            core_usable = [item for item in core_markers if not item.get("data_issues")]
            fallback_used = not core_usable and bool(backup_valid_codes)
            valid = bool(core_valid_codes) or fallback_used
            if core_valid_codes:
                reason = "核心代表走强"
                used_role = "core"
            elif fallback_used:
                reason = "核心行情不足，备用代表走强"
                used_role = "backup"
            else:
                reason = "核心代表尚未走强"
                used_role = None
            snapshots.append(
                {
                    "key": group.get("key"),
                    "label": label,
                    "core_symbols": core_symbols,
                    "backup_symbols": backup_symbols,
                    "core_valid_codes": core_valid_codes,
                    "backup_valid_codes": backup_valid_codes,
                    "core_available": len(core_usable),
                    "valid": valid,
                    "used_role": used_role,
                    "fallback_used": fallback_used,
                    "reason": reason,
                }
            )
        for marker in markers:
            marker["representative_roles"] = marker_roles.get(str(marker.get("code")), [])
        required = min(REPRESENTATIVE_MIN_GROUPS, len(snapshots)) if snapshots else 0
        strong = sum(1 for item in snapshots if item["valid"])
        return {
            "enabled": bool(snapshots),
            "groups": snapshots,
            "strong": strong,
            "required": required,
            "valid": not snapshots or strong >= required,
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
        sample_quotes = {
            code: _quote_to_sample(quote)
            for code, quote in quotes.items()
            if _quote_freshness(quote, now)["usable"]
        }
        samples = _trim_samples(
            [*old_samples, {"as_of": now.isoformat(), "quotes": sample_quotes}],
            now,
        )

        event = self._instrument(event_symbol, quotes[event_symbol], samples, now) if event_symbol in quotes else {
            "code": event_symbol,
            "name": event_symbol,
            "valid": False,
            "fields_missing": ["quote"],
            "data_issues": ["quote"],
            "data_source": None,
        }
        sector = self._instrument(sector_symbol, quotes[sector_symbol], samples, now) if sector_symbol in quotes else {
            "code": sector_symbol,
            "name": sector_symbol,
            "valid": False,
            "fields_missing": ["quote"],
            "data_issues": ["quote"],
            "data_source": None,
        }
        markers = [
            self._instrument(code, quotes[code], samples, now)
            if code in quotes
            else {
                "code": code,
                "name": code,
                "valid": False,
                "fields_missing": ["quote"],
                "data_issues": ["quote"],
                "data_source": None,
            }
            for code in symbols
        ]
        required = required_breadth(len(markers), row.majority_ratio)
        strong_count = sum(1 for marker in markers if marker.get("valid"))
        representative = self._representative_coverage(
            self._parse_representative_groups(row),
            markers,
        )
        complete = not any(item.get("data_issues") for item in [event, sector, *markers])
        breadth_valid = complete and strong_count >= required
        all_valid = (
            complete
            and bool(event.get("valid"))
            and bool(sector.get("valid"))
            and breadth_valid
            and representative["valid"]
        )

        phase, initial_reached, confirm_reached = self._phase_for(row, now)
        streak = int(previous.get("streak") or 0)
        streak = streak + 1 if all_valid and initial_reached else 0
        previous_confirm_streak = int(previous.get("confirm_streak") or 0)
        confirm_streak = previous_confirm_streak + 1 if all_valid and confirm_reached else 0
        previous_status = row.current_status or STATUS_OBSERVE
        if not complete:
            status = STATUS_INSUFFICIENT
            reason = "长鑫、159516或监控池行情缺失/陈旧，暂停综合统计，不产生买入/失效信号"
        elif not initial_reached:
            status = STATUS_OBSERVE
            reason = f"等待{row.initial_time}后的首个有效观察窗口"
        elif not all_valid or streak < MIN_STREAK:
            status = STATUS_INVALIDATED if previous_status == STATUS_CONFIRMED and not all_valid else STATUS_CONTINUE
            if representative["enabled"] and not representative["valid"]:
                reason = (
                    f"监控池强势但核心代表仅覆盖{representative['strong']}/{representative['required']}个产业方向，继续观察"
                    if status != STATUS_INVALIDATED
                    else "确认后产业链核心代表覆盖不足，信号失效"
                )
            else:
                reason = "三层条件未同时满足，继续观察；已确认信号暂不追高" if status != STATUS_INVALIDATED else "确认后长鑫、ETF或多数标的转弱，信号失效"
        elif confirm_reached and confirm_streak >= MIN_STREAK:
            status = STATUS_CONFIRMED
            representation_clause = (
                f"，且核心代表覆盖至少{representative['required']}个产业方向"
                if representative["enabled"]
                else ""
            )
            reason = f"长鑫、159516及监控池至少{required}/{len(markers)}同时满足价格与3分钟量价结构{representation_clause}"
        else:
            status = STATUS_PRELIMINARY
            reason = (
                f"初步信号：三层条件满足，等待{row.confirm_time}确认"
                if not confirm_reached
                else f"确认窗口第{confirm_streak}/{MIN_STREAK}次有效刷新，继续观察"
            )

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
            "representative_coverage": representative,
            "markers": markers,
            "trigger_values": {
                "event_above_open": event.get("above_open", False),
                "sector_above_open": sector.get("above_open", False),
                "strong_count": strong_count,
                "required_count": required,
                "representative_enabled": representative["enabled"],
                "representative_strong": representative["strong"],
                "representative_required": representative["required"],
                "representative_valid": representative["valid"],
                "streak": streak,
                "confirm_streak": confirm_streak,
                "confirm_required": MIN_STREAK,
                "initial_reached": initial_reached,
                "confirm_reached": confirm_reached,
            },
            "streak": streak,
            "confirm_streak": confirm_streak,
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

    @staticmethod
    def _is_due(row: IntradayMonitorPlanRecord, now: datetime) -> bool:
        last_evaluated_at = _parse_market_timestamp(getattr(row, "last_evaluated_at", None))
        if last_evaluated_at is None:
            return True
        interval = max(10, int(getattr(row, "poll_interval_seconds", DEFAULT_POLL_SECONDS) or DEFAULT_POLL_SECONDS))
        return now >= last_evaluated_at + timedelta(seconds=interval)

    def run_cycle(self, *, now: Optional[datetime] = None, force: bool = False) -> int:
        current = now or datetime.now(CN_TZ)
        plans = self.repository.list_active_plans()
        evaluated = 0
        for row in plans:
            if not force and not self._is_due(row, current):
                continue
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
