# -*- coding: utf-8 -*-
"""Intraday composite monitor API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.intraday_monitor import (
    IntradayMonitorDeleteResponse,
    IntradayMonitorHistoryItem,
    IntradayMonitorHistoryResponse,
    IntradayMonitorPlanCreateRequest,
    IntradayMonitorPlanListResponse,
    IntradayMonitorPlanResponse,
    IntradayMonitorPlanUpdateRequest,
)
from src.services.intraday_monitor_service import (
    IntradayMonitorService,
    IntradayMonitorValidationError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _service() -> IntradayMonitorService:
    return IntradayMonitorService()


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": "validation_error", "message": str(exc)})


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": "not_found", "message": str(exc)})


def _internal(message: str, exc: Exception) -> HTTPException:
    logger.error("%s: %s", message, exc, exc_info=True)
    return HTTPException(status_code=500, detail={"error": "internal_error", "message": f"{message}: {exc}"})


@router.get(
    "/plans",
    response_model=IntradayMonitorPlanListResponse,
    responses={500: {"model": ErrorResponse}},
    summary="List intraday monitor plans",
)
def list_plans() -> IntradayMonitorPlanListResponse:
    try:
        items = _service().list_plans()
        return IntradayMonitorPlanListResponse(items=items, total=len(items))
    except Exception as exc:
        raise _internal("List intraday monitor plans failed", exc)


@router.post(
    "/plans",
    response_model=IntradayMonitorPlanResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Create intraday monitor plan",
)
def create_plan(request: IntradayMonitorPlanCreateRequest) -> IntradayMonitorPlanResponse:
    try:
        return IntradayMonitorPlanResponse(**_service().create_plan(request.model_dump()))
    except IntradayMonitorValidationError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal("Create intraday monitor plan failed", exc)


@router.get(
    "/plans/{plan_id}",
    response_model=IntradayMonitorPlanResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Get intraday monitor plan",
)
def get_plan(plan_id: int) -> IntradayMonitorPlanResponse:
    try:
        return IntradayMonitorPlanResponse(**_service().get_plan(plan_id))
    except KeyError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal("Get intraday monitor plan failed", exc)


@router.patch(
    "/plans/{plan_id}",
    response_model=IntradayMonitorPlanResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Update intraday monitor plan",
)
def update_plan(plan_id: int, request: IntradayMonitorPlanUpdateRequest) -> IntradayMonitorPlanResponse:
    try:
        payload = request.model_dump(exclude_unset=True)
        return IntradayMonitorPlanResponse(**_service().update_plan(plan_id, payload))
    except IntradayMonitorValidationError as exc:
        raise _bad_request(exc)
    except KeyError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal("Update intraday monitor plan failed", exc)


@router.delete(
    "/plans/{plan_id}",
    response_model=IntradayMonitorDeleteResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Delete intraday monitor plan",
)
def delete_plan(plan_id: int) -> IntradayMonitorDeleteResponse:
    try:
        deleted = _service().delete_plan(plan_id)
        if not deleted:
            raise KeyError(f"Intraday monitor plan not found: {plan_id}")
        return IntradayMonitorDeleteResponse(deleted=1)
    except KeyError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal("Delete intraday monitor plan failed", exc)


@router.post("/plans/{plan_id}/enable", response_model=IntradayMonitorPlanResponse)
def enable_plan(plan_id: int) -> IntradayMonitorPlanResponse:
    try:
        return IntradayMonitorPlanResponse(**_service().set_enabled(plan_id, True))
    except KeyError as exc:
        raise _not_found(exc)


@router.post("/plans/{plan_id}/disable", response_model=IntradayMonitorPlanResponse)
def disable_plan(plan_id: int) -> IntradayMonitorPlanResponse:
    try:
        return IntradayMonitorPlanResponse(**_service().set_enabled(plan_id, False))
    except KeyError as exc:
        raise _not_found(exc)


@router.post("/plans/{plan_id}/pause", response_model=IntradayMonitorPlanResponse)
def pause_plan(plan_id: int) -> IntradayMonitorPlanResponse:
    try:
        return IntradayMonitorPlanResponse(**_service().set_paused(plan_id, True))
    except KeyError as exc:
        raise _not_found(exc)


@router.post("/plans/{plan_id}/resume", response_model=IntradayMonitorPlanResponse)
def resume_plan(plan_id: int) -> IntradayMonitorPlanResponse:
    try:
        return IntradayMonitorPlanResponse(**_service().set_paused(plan_id, False))
    except KeyError as exc:
        raise _not_found(exc)


@router.post(
    "/plans/{plan_id}/simulate",
    response_model=Dict[str, Any],
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Run deterministic intraday monitor simulation",
)
def simulate_plan(plan_id: int) -> Dict[str, Any]:
    try:
        return _service().simulate_plan(plan_id)
    except KeyError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal("Simulate intraday monitor plan failed", exc)


@router.post("/evaluate", response_model=IntradayMonitorPlanListResponse)
def evaluate_now() -> IntradayMonitorPlanListResponse:
    try:
        service = _service()
        service.run_cycle()
        items = service.list_plans()
        return IntradayMonitorPlanListResponse(items=items, total=len(items))
    except Exception as exc:
        raise _internal("Evaluate intraday monitor plans failed", exc)


@router.get(
    "/plans/{plan_id}/history",
    response_model=IntradayMonitorHistoryResponse,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="List intraday monitor status history",
)
def list_history(
    plan_id: int,
    days: int = Query(30, ge=1, le=30),
) -> IntradayMonitorHistoryResponse:
    try:
        service = _service()
        service.get_plan(plan_id)
        items = service.get_history(plan_id, days=days)
        return IntradayMonitorHistoryResponse(
            items=[IntradayMonitorHistoryItem(**item) for item in items],
            total=len(items),
        )
    except KeyError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal("List intraday monitor history failed", exc)
