// Package main
// Module: watchdog.config
// Responsibility: Financial risk invariants and daemon runtime configuration.
// Owner: aeterna-risk
// Tier: A

package main

import (
	"time"
)

// Financial safety invariant constants (Non-Negotiable).
const (
	// RiskPerTradeLimitPct defines the maximum risk per single trade (0.5%).
	RiskPerTradeLimitPct = 0.005

	// RiskLimitEpsilon defines floating point tolerance threshold for 0.5% risk (0.0050001).
	RiskLimitEpsilon = 0.0050001

	// MaxDailyLossPct defines the soft-stop circuit breaker threshold (2.0%).
	MaxDailyLossPct = 0.02

	// MaxDrawdownKillswitchPct defines the hard emergency killswitch threshold (10.0%).
	MaxDrawdownKillswitchPct = 10.0

	// MaxConcurrentPositions defines the absolute maximum open positions permitted.
	MaxConcurrentPositions = 1

	// MaxDailyTrades defines the absolute maximum trades allowed per calendar day UTC.
	MaxDailyTrades = 5

	// DefaultDeadmanTimeout defines the maximum permissible silence while a position is open.
	DefaultDeadmanTimeout = 60 * time.Second

	// DefaultSigkillGracePeriod defines the grace duration between SIGTERM and SIGKILL.
	DefaultSigkillGracePeriod = 5 * time.Second

	// DefaultIPCBindAddr defines the private localhost interface for Python-Go IPC.
	DefaultIPCBindAddr = "127.0.0.1:20129"

	// DefaultDBPath defines the canonical SQLite WAL database file path.
	DefaultDBPath = "data/trading.db"

	// DefaultDailyLockPath defines physical lock file path for Daily Circuit Breaker soft stop.
	DefaultDailyLockPath = "data/DAILY_CIRCUIT_BREAKER.lock"
	// DefaultKillswitchLockPath defines physical lock file path for Hard Emergency Killswitch.
	DefaultKillswitchLockPath = "data/EMERGENCY_KILLSWITCH.lock"

	// DefaultPIDFilePath defines file path storing Python engine PID for process tracking.
	DefaultPIDFilePath = "data/python_engine.pid"

	// DefaultEmergencyLogPath defines dedicated log path for critical watchdog interventions.
	DefaultEmergencyLogPath = "logs/watchdog_emergency.log"
)

// Config encapsulates operational limits, timeouts, and file paths.
type Config struct {
	RiskPerTradeLimitPct     float64
	RiskLimitEpsilon         float64
	MaxDailyLossPct          float64
	MaxDrawdownKillswitchPct float64
	MaxConcurrentPositions   int
	MaxDailyTrades           int
	DeadmanTimeout           time.Duration
	SigkillGracePeriod       time.Duration
	IPCBindAddr              string
	DBPath                   string
	DailyLockPath            string
	KillswitchLockPath       string
	PIDFilePath              string
	EmergencyLogPath         string
	InitialDailyEquity       float64
	PeakEquity               float64
}

// DefaultConfig instantiates a Config populated with canonical invariants.
func DefaultConfig() *Config {
	return &Config{
		RiskPerTradeLimitPct:     RiskPerTradeLimitPct,
		RiskLimitEpsilon:         RiskLimitEpsilon,
		MaxDailyLossPct:          MaxDailyLossPct,
		MaxDrawdownKillswitchPct: MaxDrawdownKillswitchPct,
		MaxConcurrentPositions:   MaxConcurrentPositions,
		MaxDailyTrades:           MaxDailyTrades,
		DeadmanTimeout:           DefaultDeadmanTimeout,
		SigkillGracePeriod:       DefaultSigkillGracePeriod,
		IPCBindAddr:              DefaultIPCBindAddr,
		DBPath:                   DefaultDBPath,
		DailyLockPath:            DefaultDailyLockPath,
		KillswitchLockPath:       DefaultKillswitchLockPath,
		PIDFilePath:              DefaultPIDFilePath,
		EmergencyLogPath:         DefaultEmergencyLogPath,
		InitialDailyEquity:       0.0,
		PeakEquity:               0.0,
	}
}
