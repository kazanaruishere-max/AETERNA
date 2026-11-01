// Package main
// Module: watchdog.gate
// Responsibility: Pre-entry order validation logic (Risk per trade, Max concurrent, Max daily trades, Bankruptcy check).
// Owner: aeterna-risk
// Tier: A

package main

import (
	"context"
	"fmt"
	"math"
	"os"
	"time"
)

// OrderRequest models incoming order parameters from Python trading engine.
type OrderRequest struct {
	Pair          string  `json:"pair"`
	Direction     string  `json:"direction"`
	LotSize       float64 `json:"lot_size"`
	EntryPrice    float64 `json:"entry_price"`
	SLPrice       float64 `json:"sl_price"`
	AccountEquity float64 `json:"account_equity"`
}

// OrderResponse conveys the risk gate evaluation result.
type OrderResponse struct {
	Allowed bool    `json:"allowed"`
	Reason  string  `json:"reason"`
	RiskUSD float64 `json:"risk_usd"`
	RiskPct float64 `json:"risk_pct"`
}

// RiskGate enforces hard pre-entry risk constraints.
type RiskGate struct {
	cfg *Config
	db  DatabaseReader
}

// NewRiskGate constructs an operational RiskGate instance.
func NewRiskGate(cfg *Config, db DatabaseReader) *RiskGate {
	return &RiskGate{
		cfg: cfg,
		db:  db,
	}
}

// fileExists checks if a file exists and is not a directory.
func fileExists(path string) bool {
	info, err := os.Stat(path)
	if err != nil {
		return false
	}
	return !info.IsDir()
}

// checkLocks verifies whether physical circuit breaker lock files exist.
func (g *RiskGate) checkLocks() bool {
	return fileExists(g.cfg.DailyLockPath) || fileExists(g.cfg.KillswitchLockPath)
}

// checkConcurrency verifies if there is an active position in system_state or trades.
func (g *RiskGate) checkConcurrency(ctx context.Context, state *SystemState) (bool, error) {
	if state.ActivePositionsCount >= g.cfg.MaxConcurrentPositions {
		return true, nil
	}
	openCount, err := g.db.GetOpenPositionsCount(ctx)
	if err != nil {
		return false, fmt.Errorf("check open positions count: %w", err)
	}
	return openCount >= g.cfg.MaxConcurrentPositions, nil
}

// checkDailyTrades verifies if maximum allowed trades for today UTC has been reached.
func (g *RiskGate) checkDailyTrades(ctx context.Context, state *SystemState) (bool, error) {
	if state.TradesTodayCount >= g.cfg.MaxDailyTrades {
		return true, nil
	}
	todayUTC := time.Now().UTC().Format("2006-01-02")
	tradesCount, err := g.db.GetTradesCountToday(ctx, todayUTC)
	if err != nil {
		return false, fmt.Errorf("check trades count today: %w", err)
	}
	return tradesCount >= g.cfg.MaxDailyTrades, nil
}

// ValidateOrder performs fail-fast deterministic checks on a candidate order.
func (g *RiskGate) ValidateOrder(ctx context.Context, req *OrderRequest) (*OrderResponse, error) {
	if g.checkLocks() {
		return &OrderResponse{Allowed: false, Reason: "circuit_breaker_lock_active"}, nil
	}

	state, err := g.db.GetSystemState(ctx)
	if err != nil {
		return &OrderResponse{Allowed: false, Reason: "system_state_not_normal"}, err
	}

	if busy, err := g.checkConcurrency(ctx, state); err != nil || busy {
		if err != nil {
			return &OrderResponse{Allowed: false, Reason: "database_error"}, err
		}
		return &OrderResponse{Allowed: false, Reason: "max_concurrent_exceeded"}, nil
	}

	if maxed, err := g.checkDailyTrades(ctx, state); err != nil || maxed {
		if err != nil {
			return &OrderResponse{Allowed: false, Reason: "database_error"}, err
		}
		return &OrderResponse{Allowed: false, Reason: "max_daily_trades_exceeded"}, nil
	}

	if req.AccountEquity <= 0.0 {
		return &OrderResponse{Allowed: false, Reason: "account_bankrupt"}, nil
	}

	riskUSD := math.Abs(req.EntryPrice-req.SLPrice) * req.LotSize * 100.0
	riskPct := riskUSD / req.AccountEquity
	if riskPct > g.cfg.RiskLimitEpsilon {
		return &OrderResponse{Allowed: false, Reason: "risk_limit_exceeded", RiskUSD: riskUSD, RiskPct: riskPct}, nil
	}

	if state.State != "NORMAL" {
		return &OrderResponse{Allowed: false, Reason: "system_state_not_normal", RiskUSD: riskUSD, RiskPct: riskPct}, nil
	}

	return &OrderResponse{Allowed: true, Reason: "OK", RiskUSD: riskUSD, RiskPct: riskPct}, nil
}
