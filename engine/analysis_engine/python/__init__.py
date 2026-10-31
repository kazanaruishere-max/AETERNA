"""
Module: engine.analysis_engine.python
Responsibility: Public API of the Python analysis engine & backtest facade.
Owner: aeterna-backtest
Tier: B
"""

from engine.analysis_engine.python.loader import load_candles_from_db
from engine.analysis_engine.python.runner import BacktestRunner
from engine.analysis_engine.python.types import (
    AuditRecordDict,
    BacktestConfigDict,
    BacktestReport,
    BacktestSummaryDict,
    CandleDict,
    MonteCarloResultDict,
    OrderDict,
    PnlResultDict,
)

__all__ = [
    "AuditRecordDict",
    "BacktestConfigDict",
    "BacktestReport",
    "BacktestRunner",
    "BacktestSummaryDict",
    "CandleDict",
    "MonteCarloResultDict",
    "OrderDict",
    "PnlResultDict",
    "load_candles_from_db",
]
