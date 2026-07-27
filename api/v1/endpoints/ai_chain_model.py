# -*- coding: utf-8 -*-
"""Manual API surface for deterministic AI-chain model runs and backtests."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.v1.schemas.ai_chain_model import (
    AIChainModelBacktestRequest,
    AIChainModelHistoryResponse,
    AIChainModelLatestResponse,
    AIChainModelRunRequest,
    AIChainModelTaskResponse,
)
from api.v1.schemas.common import ErrorResponse
from src.services.ai_chain_model_service import (
    AIChainModelTaskError,
    get_ai_chain_model_service,
)


router = APIRouter()


def _service():
    return get_ai_chain_model_service()


@router.post(
    "/runs",
    response_model=AIChainModelTaskResponse,
    responses={409: {"model": ErrorResponse}},
    summary="Submit an AI-chain daily model run",
)
def submit_run(request: AIChainModelRunRequest) -> AIChainModelTaskResponse:
    try:
        return AIChainModelTaskResponse(**_service().submit_daily_run(requested_as_of_date=request.as_of_date))
    except AIChainModelTaskError as exc:
        raise HTTPException(status_code=409, detail={"error": "task_running", "message": str(exc)})


@router.get(
    "/runs/{task_id}",
    response_model=AIChainModelTaskResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get an AI-chain manual task status",
)
def get_run_task(task_id: str) -> AIChainModelTaskResponse:
    try:
        return AIChainModelTaskResponse(**_service().get_task(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": str(exc)})


@router.get(
    "/latest",
    response_model=AIChainModelLatestResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get the latest successful AI-chain model snapshot",
)
def get_latest() -> AIChainModelLatestResponse:
    payload = _service().get_latest()
    if payload is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "no successful AI-chain model snapshot"})
    return AIChainModelLatestResponse(**payload)


@router.get("/history", response_model=AIChainModelHistoryResponse, summary="List successful AI-chain snapshots")
def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=200),
) -> AIChainModelHistoryResponse:
    return AIChainModelHistoryResponse(**_service().get_history(page=page, page_size=page_size))


@router.post(
    "/backtests",
    response_model=AIChainModelTaskResponse,
    responses={409: {"model": ErrorResponse}},
    summary="Submit an AI-chain walk-forward backtest",
)
def submit_backtest(request: AIChainModelBacktestRequest) -> AIChainModelTaskResponse:
    try:
        return AIChainModelTaskResponse(
            **_service().submit_backtest(
                start_date=request.start_date,
                end_date=request.end_date,
                holding_days=request.holding_days,
                rebalance_every_days=request.rebalance_every_days,
                cost_model={
                    "commission_rate": request.commission_rate,
                    "sell_tax_rate": request.sell_tax_rate,
                    "slippage_rate": request.slippage_rate,
                },
            )
        )
    except AIChainModelTaskError as exc:
        raise HTTPException(status_code=409, detail={"error": "task_running", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "validation_error", "message": str(exc)})


@router.get(
    "/backtests/{backtest_run_id}",
    response_model=dict[str, Any],
    responses={404: {"model": ErrorResponse}},
    summary="Get an AI-chain backtest result",
)
def get_backtest(
    backtest_run_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    payload = _service().get_backtest(backtest_run_id, page=page, page_size=page_size)
    if payload is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "AI-chain backtest not found"})
    return payload


@router.get("/data-coverage", response_model=dict[str, Any], summary="Get latest AI-chain data quality coverage")
def get_data_coverage() -> dict[str, Any]:
    payload = _service().get_latest()
    if payload is None:
        return {"items": [], "is_stale": True}
    return {
        "as_of_date": payload["as_of_date"],
        "is_stale": payload.get("is_stale", False),
        "items": payload.get("data_quality", {}),
    }
