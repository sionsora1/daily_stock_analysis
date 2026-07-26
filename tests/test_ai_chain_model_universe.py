# -*- coding: utf-8 -*-
"""Regression tests for the versioned AI-chain investment universe."""

from datetime import date

import pytest
from pydantic import ValidationError

from src.schemas.ai_chain_model import AIChainUniverseConfig
from src.services.ai_chain_universe import (
    load_ai_chain_industry_profiles,
    load_ai_chain_universe,
)


def test_seed_universe_is_versioned_and_has_unique_memberships():
    """The initial universe must be replayable and avoid duplicate positions."""
    universe = load_ai_chain_universe()

    assert universe.schema_version == "1.0"
    assert universe.historical_membership_assumption == "current_universe_backfill"
    assert len(universe.members) >= 50
    assert len({member.code for member in universe.members}) == len(universe.members)
    assert {member.group.value for member in universe.members} == {
        "hardware",
        "edge",
        "application",
    }

    active_members = universe.active_members(date(2026, 7, 24))
    assert any(member.code == "000977" for member in active_members)
    assert all(member.effective_from <= date(2026, 7, 24) for member in active_members)


def test_hardware_profiles_cover_every_hardware_subgroup():
    universe = load_ai_chain_universe()
    profiles = load_ai_chain_industry_profiles()

    universe.validate_industry_profiles(profiles)
    assert len(profiles) == 11
    assert all(profile.effective_from == date(2026, 7, 11) for profile in profiles)


def test_universe_rejects_duplicate_stock_membership():
    payload = {
        "schema_version": "1.0",
        "historical_membership_assumption": "current_universe_backfill",
        "members": [
            {
                "code": "000977",
                "name": "浪潮信息",
                "group": "hardware",
                "tier": "core",
                "hardware_subgroup": "ai_servers_odm_racks",
                "effective_from": "2023-07-01",
                "evidence_summary": "测试",
            },
            {
                "code": "000977",
                "name": "浪潮信息",
                "group": "edge",
                "tier": "observation",
                "effective_from": "2023-07-01",
                "evidence_summary": "测试",
            },
        ],
    }

    with pytest.raises(ValidationError, match="multiple active memberships"):
        AIChainUniverseConfig.model_validate(payload)
