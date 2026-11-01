// Package main
// Module: watchdog.circuit_breaker
// Responsibility: Soft Stop 2.0% daily loss, Hard Killswitch 10.0% drawdown, & Deadman Switch liveness.
// Owner: aeterna-risk
// Tier: A

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// DailyLockPayload structures the written DAILY_CIRCUIT_BREAKER.lock file.
type DailyLockPayload struct {
	TimestampUTC string  `json:"timestamp_utc"`
	EquityUSD    float64 `json:"equity_usd"`
	DailyLossUSD float64 `json:"daily_loss_usd"`
	DailyLossPct float64 `json:"daily_loss_pct"`
}

// EmergencyLockPayload structures the written EMERGENCY_KILLSWITCH.lock file.
type EmergencyLockPayload struct {
	TimestampUTC  string  `json:"timestamp_utc"`
	TriggerReason string  `json:"trigger_reason"`
	PeakEquity    float64 `json:"peak_equity"`
	CurrentEquity float64 `json:"current_equity"`
	DrawdownPct   float64 `json:"drawdown_pct"`
}

// CircuitBreaker orchestrates soft stop, hard drawdown killswitch, and deadman liveness monitoring.
type CircuitBreaker struct {
	cfg        *Config
	db         DatabaseReader
	procMgr    ProcessManager
	peakEquity float64
	mu         sync.Mutex
}

// NewCircuitBreaker constructs an active CircuitBreaker supervisor.
func NewCircuitBreaker(cfg *Config, db DatabaseReader, procMgr ProcessManager) *CircuitBreaker {
	peak := cfg.PeakEquity
	return &CircuitBreaker{
		cfg:        cfg,
		db:         db,
		procMgr:    procMgr,
		peakEquity: peak,
	}
}

// SetPeakEquity explicitly overrides the high-watermark equity (useful in testing).
func (cb *CircuitBreaker) SetPeakEquity(peak float64) {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	cb.peakEquity = peak
}

// CalculateDrawdownPct computes peak-to-trough drawdown with strict division-by-zero protection.
func CalculateDrawdownPct(peakEquity, currentEquity float64) float64 {
	if peakEquity <= 0.0 {
		return 0.0
	}
	if currentEquity >= peakEquity {
		return 0.0
	}
	return ((peakEquity - currentEquity) / peakEquity) * 100.0
}

// writeLockFileAtomically ensures reliable lock file creation across Windows and POSIX.
func writeLockFileAtomically(path string, data []byte) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("create lock dir %s: %w", dir, err)
	}
	tmpPath := fmt.Sprintf("%s.tmp.%d", path, time.Now().UnixNano())
	if err := os.WriteFile(tmpPath, data, 0o644); err != nil {
		return fmt.Errorf("write tmp lock file: %w", err)
	}
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		log.Printf("[WARN] Failed to remove pre-existing lock file %s: %v", path, err)
	}
	if err := os.Rename(tmpPath, path); err != nil {
		if rmErr := os.Remove(tmpPath); rmErr != nil && !os.IsNotExist(rmErr) {
			log.Printf("[WARN] Failed to cleanup tmp lock file %s: %v", tmpPath, rmErr)
		}
		return os.WriteFile(path, data, 0o644)
	}
	return nil
}

// CheckDailyLoss evaluates whether 2.0% daily loss soft stop threshold has been breached.
func (cb *CircuitBreaker) CheckDailyLoss(ctx context.Context, state *SystemState) (bool, error) {
	lossUSD := 0.0
	if state.DailyPnLUSD < 0 {
		lossUSD = math.Abs(state.DailyPnLUSD)
	}

	todayUTC := time.Now().UTC().Format("2006-01-02")
	closedLoss, err := cb.db.GetDailyLossUSD(ctx, todayUTC)
	if err == nil && closedLoss > lossUSD {
		lossUSD = closedLoss
	}

	baseEquity := cb.cfg.InitialDailyEquity
	if baseEquity <= 0.0 {
		baseEquity = state.EquityUSD + lossUSD
	}
	if baseEquity <= 0.0 {
		return false, nil
	}

	lossPct := (lossUSD / baseEquity) * 100.0
	if lossPct >= cb.cfg.MaxDailyLossPct*100.0 {
		payload := DailyLockPayload{
			TimestampUTC: time.Now().UTC().Format(time.RFC3339),
			EquityUSD:    state.EquityUSD,
			DailyLossUSD: lossUSD,
			DailyLossPct: lossPct,
		}
		data, err := json.MarshalIndent(payload, "", "  ")
		if err != nil {
			return false, fmt.Errorf("marshal daily lock payload: %w", err)
		}
		if err := writeLockFileAtomically(cb.cfg.DailyLockPath, data); err != nil {
			return true, fmt.Errorf("write daily lock file: %w", err)
		}
		return true, nil
	}
	return false, nil
}

// TriggerEmergencyKillswitch records emergency lock file and executes process escalation.
func (cb *CircuitBreaker) TriggerEmergencyKillswitch(ctx context.Context, reason string, peak, current, ddPct float64) error {
	payload := EmergencyLockPayload{
		TimestampUTC:  time.Now().UTC().Format(time.RFC3339),
		TriggerReason: reason,
		PeakEquity:    peak,
		CurrentEquity: current,
		DrawdownPct:   ddPct,
	}
	data, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		log.Printf("[ERROR] Failed to marshal emergency killswitch lock payload: %v", err)
		return fmt.Errorf("marshal emergency lock payload: %w", err)
	}
	if err := writeLockFileAtomically(cb.cfg.KillswitchLockPath, data); err != nil {
		log.Printf("[ERROR] Failed to write emergency killswitch lock file: %v", err)
	}

	if cb.procMgr != nil {
		return cb.procMgr.TerminateProcess(ctx, reason)
	}
	return nil
}

// CheckDrawdown checks if current equity has drawn down >= 10.0% from peak equity.
func (cb *CircuitBreaker) CheckDrawdown(ctx context.Context, state *SystemState) (bool, error) {
	cb.mu.Lock()
	if cb.peakEquity <= 0.0 || state.EquityUSD > cb.peakEquity {
		cb.peakEquity = state.EquityUSD
	}
	peak := cb.peakEquity
	cb.mu.Unlock()

	ddPct := CalculateDrawdownPct(peak, state.EquityUSD)
	if ddPct >= cb.cfg.MaxDrawdownKillswitchPct {
		err := cb.TriggerEmergencyKillswitch(ctx, "drawdown_limit_exceeded", peak, state.EquityUSD, ddPct)
		return true, err
	}
	return false, nil
}

// parseTimestampUTC attempts standard RFC3339 and ISO-8601 layout parsing.
func parseTimestampUTC(raw string) (time.Time, error) {
	layouts := []string{
		time.RFC3339Nano,
		time.RFC3339,
		"2006-01-02T15:04:05",
		"2006-01-02 15:04:05",
	}
	for _, l := range layouts {
		if t, err := time.Parse(l, raw); err == nil {
			return t.UTC(), nil
		}
	}
	return time.Time{}, fmt.Errorf("unable to parse timestamp: %s", raw)
}

// CheckDeadman inspects heartbeat liveness when an active position is held.
func (cb *CircuitBreaker) CheckDeadman(ctx context.Context, nowUTC time.Time, state *SystemState) (bool, error) {
	if state.ActivePositionsCount <= 0 {
		return false, nil
	}

	lastUpdated, err := parseTimestampUTC(state.LastUpdatedUTC)
	if err != nil {
		return false, fmt.Errorf("deadman parse timestamp: %w", err)
	}

	elapsed := nowUTC.Sub(lastUpdated)
	if elapsed > cb.cfg.DeadmanTimeout {
		cb.mu.Lock()
		peak := cb.peakEquity
		cb.mu.Unlock()
		ddPct := CalculateDrawdownPct(peak, state.EquityUSD)

		err := cb.TriggerEmergencyKillswitch(ctx, "deadman_switch_timeout", peak, state.EquityUSD, ddPct)
		return true, err
	}

	return false, nil
}
