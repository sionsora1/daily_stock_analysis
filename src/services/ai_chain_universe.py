# -*- coding: utf-8 -*-
"""Load and validate the versioned AI-chain investment universe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from src.schemas.ai_chain_model import (
    AIChainIndustryProfile,
    AIChainUniverseConfig,
)


DEFAULT_DATA_DIRECTORY = Path(__file__).resolve().parents[2] / "data"
UNIVERSE_FILENAME = "ai_chain_universe.json"
INDUSTRY_PROFILE_FILENAME = "ai_chain_industry_profiles.json"


def _read_json(path: Path) -> object:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"AI-chain model data file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI-chain model data file is not valid JSON: {path}") from exc


def load_ai_chain_universe(path: Optional[Path] = None) -> AIChainUniverseConfig:
    """Load the stock-pool history, using a caller-supplied file when needed."""
    resolved_path = path or DEFAULT_DATA_DIRECTORY / UNIVERSE_FILENAME
    return AIChainUniverseConfig.model_validate(_read_json(resolved_path))


def load_ai_chain_industry_profiles(
    path: Optional[Path] = None,
) -> List[AIChainIndustryProfile]:
    """Load versioned slow-variable industry profiles for direct hardware groups."""
    resolved_path = path or DEFAULT_DATA_DIRECTORY / INDUSTRY_PROFILE_FILENAME
    payload = _read_json(resolved_path)
    if not isinstance(payload, list):
        raise ValueError("AI-chain industry profile data must be a JSON list")
    return [AIChainIndustryProfile.model_validate(item) for item in payload]
