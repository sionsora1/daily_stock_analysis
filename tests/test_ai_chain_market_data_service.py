# -*- coding: utf-8 -*-
"""Tests for local-first daily-bar preparation and its quality gate."""

from datetime import date
from types import SimpleNamespace

import pandas as pd

from src.schemas.ai_chain_model import DataQualityStatus
from src.services.ai_chain_market_data_service import AIChainMarketDataService


def _bars(days, *, amount=True, source="LocalCache"):
    records = []
    for index, day in enumerate(days, start=1):
        records.append(
            SimpleNamespace(
                date=day,
                open=float(index),
                high=float(index) + 0.2,
                low=float(index) - 0.2,
                close=float(index),
                volume=1000.0,
                amount=10000.0 if amount else None,
                pct_chg=0.1,
                data_source=source,
            )
        )
    return records


class FakeStockRepository:
    def __init__(self, rows):
        self.rows = rows
        self.saved = []

    def get_range(self, code, start_date, end_date):
        return [row for row in self.rows if start_date <= row.date <= end_date]

    def save_dataframe(self, frame, code, data_source):
        self.saved.append((frame.copy(), code, data_source))
        return len(frame)


class FakeFetcherManager:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get_daily_data(self, code, start_date, end_date, days):
        self.calls.append((code, start_date, end_date, days))
        if self.error:
            raise self.error
        return self.response


def _remote_frame(days, *, amount=True):
    return pd.DataFrame(
        {
            "date": days,
            "open": [10.0] * len(days),
            "high": [10.2] * len(days),
            "low": [9.8] * len(days),
            "close": [10.0] * len(days),
            "volume": [1000.0] * len(days),
            "amount": [10000.0 if amount else None] * len(days),
            "pct_chg": [0.1] * len(days),
        }
    )


def test_complete_local_history_does_not_call_network():
    days = [date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)]
    repo = FakeStockRepository(_bars(days))
    fetcher = FakeFetcherManager()
    service = AIChainMarketDataService(repo, fetcher, min_coverage_ratio=0.95)

    result = service.prepare_stock("000977", days[0], days[-1])

    assert not fetcher.calls
    assert result.quality.status == DataQualityStatus.READY
    assert result.quality.used_remote_fetch is False
    assert result.quality.coverage_ratio == 1.0


def test_missing_local_dates_are_filled_by_one_stock_remote_request():
    days = [date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)]
    repo = FakeStockRepository(_bars(days[:2]))
    fetcher = FakeFetcherManager((_remote_frame(days), "TencentFetcher"))
    service = AIChainMarketDataService(repo, fetcher, min_coverage_ratio=0.95)

    result = service.prepare_stock("000977", days[0], days[-1])

    assert len(fetcher.calls) == 1
    assert repo.saved[0][1:] == ("000977", "TencentFetcher")
    assert result.quality.status == DataQualityStatus.READY
    assert result.quality.data_sources == ["LocalCache", "TencentFetcher"]
    assert len(result.daily_bars) == 3


def test_remote_fill_preserves_existing_technical_columns_for_stock_cache():
    days = [date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)]
    remote = _remote_frame(days)
    remote["ma5"] = [9.5, 9.6, 9.7]
    remote["ma10"] = [9.2, 9.3, 9.4]
    remote["ma20"] = [9.0, 9.1, 9.2]
    remote["volume_ratio"] = [1.1, 1.2, 1.3]
    repo = FakeStockRepository([])
    service = AIChainMarketDataService(
        repo,
        FakeFetcherManager((remote, "TencentFetcher")),
        min_coverage_ratio=0.95,
    )

    service.prepare_stock("000977", days[0], days[-1])

    saved_frame = repo.saved[0][0]
    assert saved_frame["ma20"].tolist() == [9.0, 9.1, 9.2]
    assert saved_frame["volume_ratio"].tolist() == [1.1, 1.2, 1.3]


def test_missing_amount_degrades_quality_without_inventing_zero_amount():
    days = [date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)]
    repo = FakeStockRepository([])
    fetcher = FakeFetcherManager((_remote_frame(days, amount=False), "TencentFetcher"))
    service = AIChainMarketDataService(repo, fetcher, min_coverage_ratio=0.95)

    result = service.prepare_stock("000977", days[0], days[-1])

    assert result.quality.status == DataQualityStatus.DEGRADED
    assert result.quality.amount_coverage_ratio == 0.0
    assert result.daily_bars["amount"].isna().all()


def test_unfilled_gap_and_source_failure_returns_insufficient_quality():
    days = [date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)]
    repo = FakeStockRepository(_bars(days[:1]))
    fetcher = FakeFetcherManager(error=RuntimeError("provider unavailable"))
    service = AIChainMarketDataService(repo, fetcher, min_coverage_ratio=0.95)

    result = service.prepare_stock("000977", days[0], days[-1])

    assert result.quality.status == DataQualityStatus.INSUFFICIENT
    assert result.quality.coverage_ratio < 0.95
    assert "provider unavailable" in result.quality.failure_reasons[0]
