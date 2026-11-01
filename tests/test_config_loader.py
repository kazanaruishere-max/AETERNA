"""Unit tests for XAUUSD dynamic parameters YAML loader and invariant validation.

Verifies:
1. Loading the default parameters.yaml returns fully populated immutable models.
2. Missing file raises FileNotFoundError.
3. Financial risk invariant violations raise ValueError.
4. Exit logic invariant violations (e.g. min_reward_risk_ratio < 2.0) raise ValueError.
5. Loaded configuration models are immutable (frozen=True).
6. Corrupted YAML syntax or invalid structure raises ValueError.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from pydantic import ValidationError

from instruments.xauusd.config.loader import (
    NewsScheduleConfig,
    XAUUSDConfig,
    load_xauusd_config,
)


@pytest.fixture
def default_config_dict() -> dict[str, Any]:
    """Load default raw YAML dictionary for mutation tests."""
    config_file = (
        Path(__file__).parent.parent
        / "instruments"
        / "xauusd"
        / "config"
        / "parameters.yaml"
    )
    with open(config_file, "r", encoding="utf-8") as f:
        loaded: object = yaml.safe_load(f)
    assert isinstance(loaded, dict), "Default parameters.yaml must be a dictionary"
    typed_data = cast(dict[str, Any], loaded)
    copied: dict[str, Any] = copy.deepcopy(typed_data)
    return copied


def _write_yaml(path: Path, data: dict[str, Any]) -> Path:
    """Helper to dump dictionary into a YAML file."""
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
    return path


def test_load_default_parameters_yaml() -> None:
    """Verify loading default parameters.yaml populates all fields accurately."""
    config = load_xauusd_config()
    assert isinstance(config, XAUUSDConfig)

    # Broker
    assert config.broker.account_leverage == 200
    assert config.broker.contract_size == 100

    # Scheduling
    assert config.scheduling.timezone_storage == "UTC"
    assert config.scheduling.session_regions["london"] == "Europe/London"
    assert config.scheduling.session_regions["new_york"] == "America/New_York"
    assert config.scheduling.rollover_buffer_minutes == 15

    # Risk
    assert config.risk.risk_per_trade_pct == 0.5
    assert config.risk.max_daily_loss_pct == 2.0
    assert config.risk.max_drawdown_killswitch_pct == 10.0
    assert config.risk.max_concurrent_positions == 1
    assert config.risk.max_trades_per_day == 5

    # Exit
    assert config.exit.sl_method == "atr"
    assert config.exit.sl_atr_multiplier == 1.5
    assert config.exit.sl_atr_period == 14
    assert config.exit.min_reward_risk_ratio == 2.0
    assert config.exit.trailing_start_r == 1.0
    assert config.exit.time_invalidation_bars == 8
    assert config.exit.atr_timeframe == "M15"
    assert config.exit.regime_timeframe == "H4"
    assert config.exit.strategy_timeframe == "H1"
    assert config.exit.partial_close_ratio == 0.5

    # State Machine
    assert config.state_machine.z_threshold_pause == 3.0
    assert config.state_machine.z_threshold_resume == 1.5
    assert config.state_machine.k_stable_reads == 12
    assert config.state_machine.m_stability_minutes == 5
    assert config.state_machine.pre_news_watch_minutes == 10
    assert config.state_machine.ewma_alpha == 0.08


    # News Schedule Defaults
    assert isinstance(config.news_schedule_defaults, NewsScheduleConfig)
    assert config.news_schedule_defaults.cpi_time_eastern == "08:30:00"
    assert config.news_schedule_defaults.nfp_time_eastern == "08:30:00"
    assert config.news_schedule_defaults.gdp_time_eastern == "08:30:00"
    assert config.news_schedule_defaults.pce_time_eastern == "08:30:00"
    assert config.news_schedule_defaults.fomc_time_eastern == "14:00:00"
    # Liquidity
    assert config.liquidity.low_liquidity_tick_z_threshold == -2.0
    assert config.liquidity.graduated_sizing_scale == 0.5
    assert config.liquidity.rollover_buffer_minutes == 15

    # Research
    assert config.research.monte_carlo_iterations == 1000
    assert config.research.retrain_light_cadence_days == 14
    assert config.research.retrain_full_cadence_days == 30

    # Also test explicit path loading
    explicit_path = (
        Path(__file__).parent.parent
        / "instruments"
        / "xauusd"
        / "config"
        / "parameters.yaml"
    )
    config_explicit = load_xauusd_config(explicit_path)
    assert config_explicit == config


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    """Verify non-existent config path raises FileNotFoundError."""
    missing_file = tmp_path / "non_existent_config.yaml"
    with pytest.raises(FileNotFoundError):
        load_xauusd_config(missing_file)

    with pytest.raises(FileNotFoundError):
        load_xauusd_config("some/fictional/path/parameters.yaml")


def test_risk_invariant_violation_raises(
    tmp_path: Path, default_config_dict: dict[str, Any]
) -> None:
    """Verify modifying risk_per_trade_pct to 1.5% or max_concurrent_positions to 2 raises ValueError."""
    # Test risk_per_trade_pct = 1.5%
    data_risk = copy.deepcopy(default_config_dict)
    data_risk["risk"]["risk_per_trade_pct"] = 1.5
    yaml_file = _write_yaml(tmp_path / "risk_pct_violation.yaml", data_risk)
    with pytest.raises(ValueError, match=r"risk_per_trade_pct"):
        load_xauusd_config(yaml_file)

    # Test max_concurrent_positions = 2
    data_pos = copy.deepcopy(default_config_dict)
    data_pos["risk"]["max_concurrent_positions"] = 2
    yaml_file_pos = _write_yaml(tmp_path / "pos_violation.yaml", data_pos)
    with pytest.raises(ValueError, match=r"max_concurrent_positions"):
        load_xauusd_config(yaml_file_pos)

    # Test max_daily_loss_pct = 3.0%
    data_loss = copy.deepcopy(default_config_dict)
    data_loss["risk"]["max_daily_loss_pct"] = 3.0
    yaml_file_loss = _write_yaml(tmp_path / "loss_violation.yaml", data_loss)
    with pytest.raises(ValueError, match=r"max_daily_loss_pct"):
        load_xauusd_config(yaml_file_loss)

    # Test max_drawdown_killswitch_pct = 12.0%
    data_dd = copy.deepcopy(default_config_dict)
    data_dd["risk"]["max_drawdown_killswitch_pct"] = 12.0
    yaml_file_dd = _write_yaml(tmp_path / "dd_violation.yaml", data_dd)
    with pytest.raises(ValueError, match=r"max_drawdown_killswitch_pct"):
        load_xauusd_config(yaml_file_dd)


def test_min_reward_risk_ratio_violation_raises(
    tmp_path: Path, default_config_dict: dict[str, Any]
) -> None:
    """Verify min_reward_risk_ratio < 2.0 raises ValueError."""
    data_rr = copy.deepcopy(default_config_dict)
    data_rr["exit"]["min_reward_risk_ratio"] = 1.5
    yaml_file = _write_yaml(tmp_path / "rr_violation.yaml", data_rr)
    with pytest.raises(ValueError, match=r"min_reward_risk_ratio"):
        load_xauusd_config(yaml_file)

    # Test time_invalidation_bars != 8
    data_time = copy.deepcopy(default_config_dict)
    data_time["exit"]["time_invalidation_bars"] = 12
    yaml_file_time = _write_yaml(tmp_path / "time_violation.yaml", data_time)
    with pytest.raises(ValueError, match=r"time_invalidation_bars"):
        load_xauusd_config(yaml_file_time)


def test_immutability_frozen_config() -> None:
    """Verify that returned configuration models are strictly immutable."""
    config = load_xauusd_config()

    with pytest.raises((ValidationError, TypeError)):
        config.risk.risk_per_trade_pct = 1.0  # type: ignore[reportAttributeAccessIssue]

    with pytest.raises((ValidationError, TypeError)):
        config.broker.account_leverage = 500  # type: ignore[reportAttributeAccessIssue]

    with pytest.raises((ValidationError, TypeError)):
        config.exit.min_reward_risk_ratio = 3.0  # type: ignore[reportAttributeAccessIssue]


    with pytest.raises((ValidationError, TypeError)):
        config.news_schedule_defaults.cpi_time_eastern = "09:00:00"  # type: ignore[reportAttributeAccessIssue]

def test_corrupt_yaml_raises_error(tmp_path: Path) -> None:
    """Verify corrupt YAML syntax or non-mapping structure raises ValueError."""
    # 1. Broken syntax
    syntax_err_file = tmp_path / "broken_syntax.yaml"
    syntax_err_file.write_text("broker:\n  account_leverage: [unclosed", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Corrupt YAML"):
        load_xauusd_config(syntax_err_file)

    # 2. Non-mapping root structure (list)
    list_file = tmp_path / "list_root.yaml"
    list_file.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Invalid YAML structure"):
        load_xauusd_config(list_file)

    # 3. Empty YAML file
    empty_file = tmp_path / "empty.yaml"
    empty_file.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Invalid YAML structure"):
        load_xauusd_config(empty_file)

    # 4. Missing required section
    missing_section_file = tmp_path / "missing_section.yaml"
    missing_section_file.write_text("broker:\n  account_leverage: 200\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Schema validation error"):
        load_xauusd_config(missing_section_file)


def test_corrupt_yaml_raises_value_error(tmp_path: Path) -> None:
    """Alias for test_corrupt_yaml_raises_error as specified in TASK-M3-03.md §6."""
    test_corrupt_yaml_raises_error(tmp_path)
