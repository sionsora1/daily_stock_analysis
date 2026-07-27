# -*- coding: utf-8 -*-
"""HTTP contracts for the manual AI-chain model endpoints."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.endpoints import ai_chain_model


class _FakeModelService:
    def __init__(self):
        self.latest = {
            "id": 7,
            "as_of_date": "2026-07-24",
            "model_version": "v1",
            "status": "succeeded",
            "market_gate": "normal",
            "data_coverage": 0.96,
            "warnings": [],
            "model_profile": {"holding_days": 20},
            "data_quality": {"000977": {"status": "ready"}},
            "scores": [{"code": "000977", "score": 72.3, "group": "hardware"}],
            "is_stale": False,
        }

    @staticmethod
    def _task(kind):
        return {
            "task_id": f"{kind}-task",
            "kind": kind,
            "status": "pending",
            "progress": 0,
            "message": "queued",
            "result": None,
            "error": None,
            "created_at": "2026-07-24T15:00:00",
            "started_at": None,
            "completed_at": None,
        }

    def submit_daily_run(self, **_kwargs):
        return self._task("daily_run")

    def submit_backtest(self, **_kwargs):
        return self._task("backtest")

    def get_task(self, task_id):
        if task_id == "missing":
            raise KeyError(task_id)
        return self._task("daily_run")

    def get_latest(self):
        return self.latest

    def get_history(self, *, page, page_size):
        return {"items": [self.latest], "total": 1, "page": page, "page_size": page_size}

    @staticmethod
    def get_backtest(backtest_run_id, *, page, page_size):
        if backtest_run_id == 404:
            return None
        return {"id": backtest_run_id, "status": "succeeded", "points": [], "point_total": 0}


def _client(monkeypatch):
    service = _FakeModelService()
    monkeypatch.setattr(ai_chain_model, "_service", lambda: service)
    app = FastAPI()
    app.include_router(ai_chain_model.router, prefix="/api/v1/ai-chain-model")
    return TestClient(app), service


def test_manual_run_and_latest_snapshot_contract(monkeypatch):
    client, _ = _client(monkeypatch)

    submitted = client.post("/api/v1/ai-chain-model/runs", json={"as_of_date": "2026-07-24"})
    latest = client.get("/api/v1/ai-chain-model/latest")
    coverage = client.get("/api/v1/ai-chain-model/data-coverage")

    assert submitted.status_code == 200
    assert submitted.json()["kind"] == "daily_run"
    assert latest.status_code == 200
    assert latest.json()["scores"][0]["code"] == "000977"
    assert coverage.json()["items"]["000977"]["status"] == "ready"


def test_history_backtest_and_not_found_contracts(monkeypatch):
    client, _ = _client(monkeypatch)

    history = client.get("/api/v1/ai-chain-model/history?page=1&page_size=10")
    backtest = client.post("/api/v1/ai-chain-model/backtests", json={"holding_days": 20})
    missing_task = client.get("/api/v1/ai-chain-model/runs/missing")
    missing_backtest = client.get("/api/v1/ai-chain-model/backtests/404")

    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert backtest.status_code == 200
    assert backtest.json()["kind"] == "backtest"
    assert missing_task.status_code == 404
    assert missing_backtest.status_code == 404
