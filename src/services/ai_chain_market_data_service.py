# -*- coding: utf-8 -*-
"""Local-first daily-bar preparation for the AI-chain model.

The service never substitutes missing price or amount values.  It first uses
the project's cached ``StockDaily`` records and requests one stock at a time
only when the requested window is incomplete.  The returned quality report is
part of the model's audit trail and determines whether a later scoring run may
publish a new recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, List, Optional, Protocol, Sequence, Tuple

import pandas as pd

from src.schemas.ai_chain_model import (
    AdjustmentStatus,
    DailyDataQualityReport,
    DataQualityStatus,
)


class DailyDataRepository(Protocol):
    """Narrow storage contract used by this service."""

    def get_range(self, code: str, start_date: date, end_date: date) -> Sequence[Any]:
        ...

    def save_dataframe(self, df: pd.DataFrame, code: str, data_source: str) -> int:
        ...


class DailyDataFetcher(Protocol):
    """Narrow provider contract used by this service."""

    def get_daily_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        days: int,
    ) -> Tuple[pd.DataFrame, str]:
        ...


@dataclass(frozen=True)
class MarketDataPreparationResult:
    """Prepared daily bars and the quality gate result for one stock."""

    daily_bars: pd.DataFrame
    quality: DailyDataQualityReport


class AIChainMarketDataService:
    """Prepare reproducible daily bars without silently masking data issues."""

    _MODEL_COLUMNS = (
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "pct_chg",
        "data_source",
    )
    _OPTIONAL_STORAGE_COLUMNS = ("ma5", "ma10", "ma20", "volume_ratio")
    _NORMALIZED_COLUMNS = _MODEL_COLUMNS + _OPTIONAL_STORAGE_COLUMNS

    def __init__(
        self,
        stock_repository: DailyDataRepository,
        fetcher_manager: DailyDataFetcher,
        *,
        min_coverage_ratio: float = 0.90,
    ) -> None:
        if not 0 < min_coverage_ratio <= 1:
            raise ValueError("min_coverage_ratio must be within (0, 1]")
        self._stock_repository = stock_repository
        self._fetcher_manager = fetcher_manager
        self._min_coverage_ratio = min_coverage_ratio

    def prepare_stock(
        self,
        code: str,
        start_date: date,
        end_date: date,
    ) -> MarketDataPreparationResult:
        """Return local/filled bars and a non-silent quality assessment.

        A remote request deliberately spans only this stock and this requested
        date window.  The provider may return an overlapping window; newest
        fetched rows replace local rows for identical dates before analysis.
        """
        if end_date < start_date:
            raise ValueError("end_date cannot be before start_date")

        reasons: List[str] = []
        local_frame = self._load_local_frame(code, start_date, end_date, reasons)
        source_history = self._frame_sources(local_frame)
        expected_dates = self._expected_trading_dates(start_date, end_date)
        local_coverage = self._coverage_ratio(local_frame, expected_dates)
        used_remote_fetch = False
        combined_frame = local_frame

        if local_coverage < self._min_coverage_ratio:
            used_remote_fetch = True
            try:
                remote_frame, source = self._fetch_remote(code, start_date, end_date)
                if remote_frame.empty:
                    reasons.append("daily data provider returned no rows")
                else:
                    source_history.append(source)
                    normalized_remote = self._normalize_frame(remote_frame, default_source=source)
                    if normalized_remote.empty:
                        reasons.append("daily data provider returned no valid dated rows")
                    else:
                        self._stock_repository.save_dataframe(
                            normalized_remote.drop(columns=["data_source"], errors="ignore"),
                            code,
                            source,
                        )
                        combined_frame = self._merge_frames(local_frame, normalized_remote)
            except Exception as exc:  # Provider errors must become visible quality evidence.
                reasons.append(str(exc).strip() or type(exc).__name__)

        quality = self._build_quality_report(
            code=code,
            frame=combined_frame,
            start_date=start_date,
            end_date=end_date,
            expected_dates=expected_dates,
            source_history=source_history,
            used_remote_fetch=used_remote_fetch,
            failure_reasons=reasons,
        )
        return MarketDataPreparationResult(daily_bars=combined_frame, quality=quality)

    def _load_local_frame(
        self,
        code: str,
        start_date: date,
        end_date: date,
        reasons: List[str],
    ) -> pd.DataFrame:
        try:
            rows = self._stock_repository.get_range(code, start_date, end_date)
        except Exception as exc:
            reasons.append(f"local daily data read failed: {str(exc).strip() or type(exc).__name__}")
            rows = []
        return self._rows_to_frame(rows)

    def _fetch_remote(
        self, code: str, start_date: date, end_date: date
    ) -> Tuple[pd.DataFrame, str]:
        response = self._fetcher_manager.get_daily_data(
            code,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            days=max(1, (end_date - start_date).days + 1),
        )
        if not isinstance(response, tuple) or len(response) != 2:
            raise ValueError("daily data provider returned an invalid response contract")
        frame, source = response
        if not isinstance(frame, pd.DataFrame):
            raise ValueError("daily data provider did not return a DataFrame")
        if not isinstance(source, str) or not source:
            raise ValueError("daily data provider did not report a source name")
        return frame, source

    def _rows_to_frame(self, rows: Iterable[Any]) -> pd.DataFrame:
        records = []
        for row in rows or []:
            record = {column: getattr(row, column, None) for column in self._NORMALIZED_COLUMNS}
            records.append(record)
        return self._normalize_frame(pd.DataFrame(records), default_source="LocalCache")

    def _normalize_frame(self, frame: pd.DataFrame, *, default_source: str) -> pd.DataFrame:
        normalized = frame.copy()
        for column in self._NORMALIZED_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = pd.NA
        normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.date
        normalized = normalized.dropna(subset=["date"])
        for column in ("open", "high", "low", "close", "volume", "amount", "pct_chg"):
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        normalized["data_source"] = normalized["data_source"].fillna(default_source).astype(str)
        for column in self._OPTIONAL_STORAGE_COLUMNS:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        normalized = normalized.loc[:, self._NORMALIZED_COLUMNS]
        normalized = normalized.sort_values("date").drop_duplicates("date", keep="last")
        return normalized.reset_index(drop=True)

    @staticmethod
    def _merge_frames(local_frame: pd.DataFrame, remote_frame: pd.DataFrame) -> pd.DataFrame:
        return (
            pd.concat([local_frame, remote_frame], ignore_index=True)
            .sort_values("date")
            .drop_duplicates("date", keep="last")
            .reset_index(drop=True)
        )

    @staticmethod
    def _expected_trading_dates(start_date: date, end_date: date) -> set[date]:
        return {value.date() for value in pd.bdate_range(start_date, end_date)}

    @staticmethod
    def _coverage_ratio(frame: pd.DataFrame, expected_dates: set[date]) -> float:
        if not expected_dates:
            return 1.0
        available_dates = set(
            frame.loc[frame["close"].notna(), "date"].tolist()
        )
        return min(1.0, len(available_dates & expected_dates) / len(expected_dates))

    @staticmethod
    def _frame_sources(frame: pd.DataFrame) -> List[str]:
        if frame.empty:
            return []
        return list(dict.fromkeys(frame["data_source"].dropna().astype(str).tolist()))

    def _build_quality_report(
        self,
        *,
        code: str,
        frame: pd.DataFrame,
        start_date: date,
        end_date: date,
        expected_dates: set[date],
        source_history: List[str],
        used_remote_fetch: bool,
        failure_reasons: List[str],
    ) -> DailyDataQualityReport:
        available_mask = frame["close"].notna()
        available_dates = set(frame.loc[available_mask, "date"].tolist()) & expected_dates
        available_trading_days = len(available_dates)
        expected_trading_days = len(expected_dates)
        coverage_ratio = (
            1.0
            if expected_trading_days == 0
            else available_trading_days / expected_trading_days
        )
        amount_coverage_ratio = 0.0
        if available_trading_days:
            amount_coverage_ratio = float(
                frame.loc[available_mask & frame["amount"].notna(), "date"].isin(expected_dates).sum()
                / available_trading_days
            )

        last_trade_date: Optional[date] = None
        if not frame.empty:
            valid_dates = frame.loc[available_mask, "date"]
            if not valid_dates.empty:
                last_trade_date = max(valid_dates.tolist())

        status = DataQualityStatus.READY
        if coverage_ratio < self._min_coverage_ratio:
            status = DataQualityStatus.INSUFFICIENT
            if not any("coverage" in reason for reason in failure_reasons):
                failure_reasons.append(
                    f"daily close coverage {coverage_ratio:.1%} is below required {self._min_coverage_ratio:.1%}"
                )
        elif amount_coverage_ratio < self._min_coverage_ratio:
            status = DataQualityStatus.DEGRADED
            failure_reasons.append("amount coverage is below the configured threshold; volume fallback required")

        if not available_trading_days and used_remote_fetch and failure_reasons:
            status = DataQualityStatus.FAILED

        return DailyDataQualityReport(
            code=code,
            start_date=start_date,
            end_date=end_date,
            expected_trading_days=expected_trading_days,
            available_trading_days=available_trading_days,
            coverage_ratio=coverage_ratio,
            amount_coverage_ratio=amount_coverage_ratio,
            last_trade_date=last_trade_date,
            data_sources=list(dict.fromkeys(source_history)),
            adjustment_status=AdjustmentStatus.UNKNOWN,
            status=status,
            used_remote_fetch=used_remote_fetch,
            failure_reasons=failure_reasons,
        )
