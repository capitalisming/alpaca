"""
core/config.py

Conservative defaults. Every number here is deliberately tight — loosen
consciously per-Track, never by accident. Nothing here talks to the network.
"""

from pydantic import BaseModel, Field


class RiskConfig(BaseModel):
    max_position_size: float = Field(default=0.05, ge=0.0, le=1.0)
    # Sum of |position_size| across all currently-open + proposed exposure.
    max_portfolio_exposure: float = Field(default=0.30, ge=0.0, le=1.0)
    min_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    daily_loss_limit_pct: float = Field(default=0.03, ge=0.0, le=1.0)
    max_data_age_seconds: int = Field(default=60, ge=0)
    duplicate_cooldown_seconds: int = Field(default=30, ge=0)
    symbol_allowlist: frozenset[str] | None = None  # None == no restriction
    kill_switch: bool = False
