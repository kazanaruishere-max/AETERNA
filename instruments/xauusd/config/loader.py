"""Dynamic parameters YAML loader and schema validator for XAUUSD.

Enforces hard mathematical, risk, and architectural invariants from
docs/aeterna/invariant-cheatsheet.md and docs/architecture.md §9.
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class BrokerConfig(BaseModel):
    """Broker execution parameters."""

    model_config = ConfigDict(frozen=True)

    account_leverage: int = Field(gt=0)
    contract_size: int = Field(gt=0)


class SchedulingConfig(BaseModel):
    """Timezone and session scheduling parameters."""

    model_config = ConfigDict(frozen=True)

    timezone_storage: str
    session_regions: dict[str, str]
    rollover_buffer_minutes: int = Field(ge=15)


class RiskConfig(BaseModel):
    """Financial risk limits and position constraints."""

    model_config = ConfigDict(frozen=True)

    risk_per_trade_pct: float = Field(ge=0.1, le=1.0)
    max_daily_loss_pct: float = Field(ge=1.0, le=5.0)
    max_drawdown_killswitch_pct: float = Field(ge=5.0, le=15.0)
    max_concurrent_positions: int = Field(ge=1, le=1)
    max_trades_per_day: int = Field(ge=1, le=10)


class ExitConfig(BaseModel):
    """Multi-layer exit and trade invalidation rules."""

    model_config = ConfigDict(frozen=True)

    sl_method: str
    sl_atr_multiplier: float = Field(gt=0)
    sl_atr_period: int = Field(gt=0)
    min_reward_risk_ratio: float = Field(ge=2.0)
    trailing_start_r: float = Field(ge=1.0)
    time_invalidation_bars: int = Field(ge=1)
    atr_timeframe: str
    regime_timeframe: str
    strategy_timeframe: str
    partial_close_ratio: float = Field(gt=0, le=1.0)


class StateMachineConfig(BaseModel):
    """Volatility and news state machine thresholds."""

    model_config = ConfigDict(frozen=True)

    z_threshold_pause: float = Field(gt=0)
    z_threshold_resume: float = Field(gt=0)
    k_stable_reads: int = Field(gt=0)
    m_stability_minutes: int = Field(gt=0)
    pre_news_watch_minutes: int = Field(gt=0)
    ewma_alpha: float = Field(gt=0, lt=1.0)


class NewsScheduleConfig(BaseModel):
    """Default release times for major macroeconomic news events (Eastern Time)."""

    model_config = ConfigDict(frozen=True)

    cpi_time_eastern: str
    nfp_time_eastern: str
    gdp_time_eastern: str
    pce_time_eastern: str
    fomc_time_eastern: str

class LiquidityConfig(BaseModel):
    """Liquidity gating and graduated sizing parameters."""

    model_config = ConfigDict(frozen=True)

    low_liquidity_tick_z_threshold: float = Field(lt=0)
    graduated_sizing_scale: float = Field(gt=0, le=1.0)
    rollover_buffer_minutes: int = Field(ge=15)


class ResearchConfig(BaseModel):
    """Research and model retraining cadence."""

    model_config = ConfigDict(frozen=True)

    monte_carlo_iterations: int = Field(ge=100)
    retrain_light_cadence_days: int = Field(ge=1)
    retrain_full_cadence_days: int = Field(ge=1)


class XAUUSDConfig(BaseModel):
    """Aggregated starting configuration for XAUUSD trading system."""

    model_config = ConfigDict(frozen=True)

    broker: BrokerConfig
    scheduling: SchedulingConfig
    risk: RiskConfig
    exit: ExitConfig
    state_machine: StateMachineConfig
    news_schedule_defaults: NewsScheduleConfig
    liquidity: LiquidityConfig
    research: ResearchConfig


def validate_xauusd_invariants(config: XAUUSDConfig) -> None:
    """Validate strict numerical and operational hard invariants.

    Raises:
        ValueError: If any architectural, financial, or operational invariant is violated.
    """
    # 1. Financial Risk Invariants
    if not math.isclose(config.risk.risk_per_trade_pct, 0.5, abs_tol=1e-9):
        raise ValueError(
            f"Financial invariant violated: risk_per_trade_pct must be exactly 0.5, got {config.risk.risk_per_trade_pct}"
        )
    if not math.isclose(config.risk.max_daily_loss_pct, 2.0, abs_tol=1e-9):
        raise ValueError(
            f"Financial invariant violated: max_daily_loss_pct must be exactly 2.0, got {config.risk.max_daily_loss_pct}"
        )
    if not math.isclose(config.risk.max_drawdown_killswitch_pct, 10.0, abs_tol=1e-9):
        raise ValueError(
            f"Financial invariant violated: max_drawdown_killswitch_pct must be exactly 10.0, got {config.risk.max_drawdown_killswitch_pct}"
        )
    if config.risk.max_concurrent_positions != 1:
        raise ValueError(
            f"Financial invariant violated: max_concurrent_positions must be exactly 1, got {config.risk.max_concurrent_positions}"
        )
    if config.risk.max_trades_per_day != 5:
        raise ValueError(
            f"Financial invariant violated: max_trades_per_day must be exactly 5, got {config.risk.max_trades_per_day}"
        )

    # 2. Exit Logic Invariants
    if config.exit.sl_method != "atr":
        raise ValueError(
            f"Exit invariant violated: sl_method must be 'atr', got '{config.exit.sl_method}'"
        )
    if not math.isclose(config.exit.sl_atr_multiplier, 1.5, abs_tol=1e-9):
        raise ValueError(
            f"Exit invariant violated: sl_atr_multiplier must be 1.5, got {config.exit.sl_atr_multiplier}"
        )
    if config.exit.sl_atr_period != 14:
        raise ValueError(
            f"Exit invariant violated: sl_atr_period must be 14, got {config.exit.sl_atr_period}"
        )
    if config.exit.min_reward_risk_ratio < 2.0:
        raise ValueError(
            f"Exit invariant violated: min_reward_risk_ratio must be >= 2.0, got {config.exit.min_reward_risk_ratio}"
        )
    if not math.isclose(config.exit.trailing_start_r, 1.0, abs_tol=1e-9):
        raise ValueError(
            f"Exit invariant violated: trailing_start_r must be 1.0, got {config.exit.trailing_start_r}"
        )
    if not math.isclose(config.exit.partial_close_ratio, 0.5, abs_tol=1e-9):
        raise ValueError(
            f"Exit invariant violated: partial_close_ratio must be 0.5, got {config.exit.partial_close_ratio}"
        )
    if config.exit.time_invalidation_bars != 8:
        raise ValueError(
            f"Exit invariant violated: time_invalidation_bars must be 8, got {config.exit.time_invalidation_bars}"
        )

    # 3. State Machine Invariants
    if not math.isclose(config.state_machine.z_threshold_pause, 3.0, abs_tol=1e-9):
        raise ValueError(
            f"State machine invariant violated: z_threshold_pause must be 3.0, got {config.state_machine.z_threshold_pause}"
        )
    if not math.isclose(config.state_machine.z_threshold_resume, 1.5, abs_tol=1e-9):
        raise ValueError(
            f"State machine invariant violated: z_threshold_resume must be 1.5, got {config.state_machine.z_threshold_resume}"
        )
    if config.state_machine.k_stable_reads != 12:
        raise ValueError(
            f"State machine invariant violated: k_stable_reads must be 12, got {config.state_machine.k_stable_reads}"
        )
    if config.state_machine.m_stability_minutes != 5:
        raise ValueError(
            f"State machine invariant violated: m_stability_minutes must be 5, got {config.state_machine.m_stability_minutes}"
        )
    if not math.isclose(config.state_machine.ewma_alpha, 0.08, abs_tol=1e-9):
        raise ValueError(
            f"State machine invariant violated: ewma_alpha must be 0.08, got {config.state_machine.ewma_alpha}"
        )

    # 4. Liquidity Invariants
    if not math.isclose(config.liquidity.low_liquidity_tick_z_threshold, -2.0, abs_tol=1e-9):
        raise ValueError(
            f"Liquidity invariant violated: low_liquidity_tick_z_threshold must be -2.0, got {config.liquidity.low_liquidity_tick_z_threshold}"
        )
    if not math.isclose(config.liquidity.graduated_sizing_scale, 0.5, abs_tol=1e-9):
        raise ValueError(
            f"Liquidity invariant violated: graduated_sizing_scale must be 0.5, got {config.liquidity.graduated_sizing_scale}"
        )
    if config.liquidity.rollover_buffer_minutes != 15:
        raise ValueError(
            f"Liquidity invariant violated: rollover_buffer_minutes must be 15, got {config.liquidity.rollover_buffer_minutes}"
        )


def load_xauusd_config(config_path: str | Path | None = None) -> XAUUSDConfig:
    """Load, parse, and strictly validate XAUUSD parameters.yaml.

    Default path: instruments/xauusd/config/parameters.yaml
    Raises FileNotFoundError if file is missing.
    Raises ValueError on schema or numerical invariant violations, or corrupted YAML.
    """
    if config_path is None:
        target_path = Path(__file__).parent / "parameters.yaml"
    else:
        target_path = Path(config_path)

    if not target_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {target_path}")

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            raw_data: object = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(f"Corrupt YAML in configuration file '{target_path}': {exc}") from exc

    if not isinstance(raw_data, dict):
        raise ValueError(  # noqa: TRY004
            f"Invalid YAML structure in '{target_path}': expected mapping, got {type(raw_data).__name__}"
        )

    try:
        config = XAUUSDConfig.model_validate(raw_data)
    except Exception as exc:
        raise ValueError(f"Schema validation error in '{target_path}': {exc}") from exc

    validate_xauusd_invariants(config)
    return config
