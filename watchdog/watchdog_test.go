// Package main
// Module: watchdog.watchdog_test
// Responsibility: Comprehensive deterministic unit tests, deadman switch verification, and safety invariants.
// Owner: aeterna-risk
// Tier: A

package main

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	_ "modernc.org/sqlite"
)

// mockProcessManager records termination calls for deterministic assertions.
type mockProcessManager struct {
	terminated   bool
	lastReason   string
	processAlive bool
}

func (m *mockProcessManager) TerminateProcess(ctx context.Context, reason string) error {
	m.terminated = true
	m.lastReason = reason
	return nil
}

func (m *mockProcessManager) IsProcessAlive(pid int) bool {
	return m.processAlive
}

func (m *mockProcessManager) ReadPID() (int, error) {
	return 12345, nil
}

// createTestDB establishes a temporary SQLite database initialized with system_state and trades.
func createTestDB(t *testing.T) (string, func()) {
	t.Helper()
	tmpDir, err := os.MkdirTemp("", "watchdog_test_*")
	if err != nil {
		t.Fatalf("failed to create temp dir: %v", err)
	}

	dbPath := filepath.Join(tmpDir, "test_trading.db")
	initDB, err := sql.Open("sqlite", dbPath)
	if err != nil {
		_ = os.RemoveAll(tmpDir)
		t.Fatalf("failed to open init db: %v", err)
	}

	ddl := `
	CREATE TABLE IF NOT EXISTS system_state (
		id INTEGER PRIMARY KEY CHECK (id = 1),
		state TEXT NOT NULL,
		current_spread REAL NOT NULL,
		spread_baseline REAL NOT NULL,
		spread_z_score REAL NOT NULL,
		active_positions_count INTEGER NOT NULL,
		equity_usd REAL NOT NULL,
		daily_pnl_usd REAL NOT NULL,
		trades_today_count INTEGER NOT NULL,
		last_news_event TEXT,
		last_updated_utc TEXT NOT NULL
	);
	CREATE TABLE IF NOT EXISTS trades (
		trade_id TEXT PRIMARY KEY,
		timestamp_entry_utc TEXT NOT NULL,
		timestamp_exit_utc TEXT,
		pnl_usd REAL
	);
	INSERT INTO system_state (
		id, state, current_spread, spread_baseline, spread_z_score,
		active_positions_count, equity_usd, daily_pnl_usd, trades_today_count,
		last_news_event, last_updated_utc
	) VALUES (1, 'NORMAL', 1.2, 1.2, 0.0, 0, 10000.0, 0.0, 0, NULL, '2026-11-01T12:00:00Z');
	`
	if _, err := initDB.Exec(ddl); err != nil {
		_ = initDB.Close()
		_ = os.RemoveAll(tmpDir)
		t.Fatalf("failed to exec schema ddl: %v", err)
	}
	_ = initDB.Close()

	cleanup := func() {
		_ = os.RemoveAll(tmpDir)
	}
	return dbPath, cleanup
}

func TestPreEntryMaxConcurrentReject(t *testing.T) {
	dbPath, cleanup := createTestDB(t)
	defer cleanup()

	initDB, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	_, _ = initDB.Exec("UPDATE system_state SET active_positions_count = 1 WHERE id = 1")
	_ = initDB.Close()

	roDB, err := OpenReadOnly(dbPath)
	if err != nil {
		t.Fatalf("open read-only db: %v", err)
	}
	defer roDB.Close()

	cfg := DefaultConfig()
	gate := NewRiskGate(cfg, roDB)

	req := &OrderRequest{
		Pair:          "XAUUSD",
		Direction:     "LONG",
		LotSize:       0.01,
		EntryPrice:    2650.0,
		SLPrice:       2645.0,
		AccountEquity: 10000.0,
	}

	resp, err := gate.ValidateOrder(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected validation error: %v", err)
	}
	if resp.Allowed {
		t.Fatalf("expected order to be rejected when active_positions_count >= 1")
	}
	if resp.Reason != "max_concurrent_exceeded" {
		t.Fatalf("expected reason 'max_concurrent_exceeded', got '%s'", resp.Reason)
	}
}

func TestPreEntryMaxDailyTradesReject(t *testing.T) {
	dbPath, cleanup := createTestDB(t)
	defer cleanup()

	initDB, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	_, _ = initDB.Exec("UPDATE system_state SET trades_today_count = 5 WHERE id = 1")
	_ = initDB.Close()

	roDB, err := OpenReadOnly(dbPath)
	if err != nil {
		t.Fatalf("open read-only db: %v", err)
	}
	defer roDB.Close()

	cfg := DefaultConfig()
	gate := NewRiskGate(cfg, roDB)

	req := &OrderRequest{
		Pair:          "XAUUSD",
		Direction:     "LONG",
		LotSize:       0.01,
		EntryPrice:    2650.0,
		SLPrice:       2645.0,
		AccountEquity: 10000.0,
	}

	resp, err := gate.ValidateOrder(context.Background(), req)
	if err != nil {
		t.Fatalf("unexpected validation error: %v", err)
	}
	if resp.Allowed {
		t.Fatalf("expected order to be rejected when trades_today_count >= 5")
	}
	if resp.Reason != "max_daily_trades_exceeded" {
		t.Fatalf("expected reason 'max_daily_trades_exceeded', got '%s'", resp.Reason)
	}
}

func TestPreEntryBankruptcyReject(t *testing.T) {
	dbPath, cleanup := createTestDB(t)
	defer cleanup()

	roDB, err := OpenReadOnly(dbPath)
	if err != nil {
		t.Fatalf("open read-only db: %v", err)
	}
	defer roDB.Close()

	cfg := DefaultConfig()
	gate := NewRiskGate(cfg, roDB)

	reqZero := &OrderRequest{
		Pair:          "XAUUSD",
		Direction:     "LONG",
		LotSize:       0.01,
		EntryPrice:    2650.0,
		SLPrice:       2645.0,
		AccountEquity: 0.0,
	}
	respZero, err := gate.ValidateOrder(context.Background(), reqZero)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if respZero.Allowed || respZero.Reason != "account_bankrupt" {
		t.Fatalf("expected bankrupt rejection for equity 0.0, got: %+v", respZero)
	}

	reqNeg := &OrderRequest{
		Pair:          "XAUUSD",
		Direction:     "LONG",
		LotSize:       0.01,
		EntryPrice:    2650.0,
		SLPrice:       2645.0,
		AccountEquity: -50.0,
	}
	respNeg, err := gate.ValidateOrder(context.Background(), reqNeg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if respNeg.Allowed || respNeg.Reason != "account_bankrupt" {
		t.Fatalf("expected bankrupt rejection for negative equity, got: %+v", respNeg)
	}
}

func TestPreEntryRiskExceededReject(t *testing.T) {
	dbPath, cleanup := createTestDB(t)
	defer cleanup()

	roDB, err := OpenReadOnly(dbPath)
	if err != nil {
		t.Fatalf("open read-only db: %v", err)
	}
	defer roDB.Close()

	cfg := DefaultConfig()
	gate := NewRiskGate(cfg, roDB)

	// Boundary 0.50%: diff 5.0 * 0.10 * 100 = 50.0 USD on 10,000 equity = 0.0050 (0.50%) -> PASS
	passReq := &OrderRequest{
		Pair:          "XAUUSD",
		Direction:     "LONG",
		LotSize:       0.10,
		EntryPrice:    2650.0,
		SLPrice:       2645.0,
		AccountEquity: 10000.0,
	}
	passResp, err := gate.ValidateOrder(context.Background(), passReq)
	if err != nil {
		t.Fatalf("unexpected error on valid risk: %v", err)
	}
	if !passResp.Allowed {
		t.Fatalf("expected 0.50%% risk to pass, got rejected: %s", passResp.Reason)
	}

	// Boundary 0.51%: diff 5.1 * 0.10 * 100 = 51.0 USD on 10,000 equity = 0.0051 (0.51%) -> REJECT
	failReq := &OrderRequest{
		Pair:          "XAUUSD",
		Direction:     "LONG",
		LotSize:       0.10,
		EntryPrice:    2650.0,
		SLPrice:       2644.9,
		AccountEquity: 10000.0,
	}
	failResp, err := gate.ValidateOrder(context.Background(), failReq)
	if err != nil {
		t.Fatalf("unexpected error on excessive risk: %v", err)
	}
	if failResp.Allowed {
		t.Fatalf("expected 0.51%% risk to be rejected")
	}
	if failResp.Reason != "risk_limit_exceeded" {
		t.Fatalf("expected reason 'risk_limit_exceeded', got '%s'", failResp.Reason)
	}
}

func TestCircuitBreakerDailyLossSoftStop(t *testing.T) {
	dbPath, cleanup := createTestDB(t)
	defer cleanup()

	tmpDir, err := os.MkdirTemp("", "lock_test_*")
	if err != nil {
		t.Fatalf("mkdir temp: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	cfg := DefaultConfig()
	cfg.DailyLockPath = filepath.Join(tmpDir, "DAILY_CIRCUIT_BREAKER.lock")
	cfg.InitialDailyEquity = 10000.0

	roDB, err := OpenReadOnly(dbPath)
	if err != nil {
		t.Fatalf("open ro db: %v", err)
	}
	defer roDB.Close()

	cb := NewCircuitBreaker(cfg, roDB, nil)

	// Daily loss: -200 USD on 10,000 equity = 2.0% -> Triggers Soft Stop
	state := &SystemState{
		EquityUSD:   9800.0,
		DailyPnLUSD: -200.0,
	}

	triggered, err := cb.CheckDailyLoss(context.Background(), state)
	if err != nil {
		t.Fatalf("unexpected error checking daily loss: %v", err)
	}
	if !triggered {
		t.Fatalf("expected daily loss >= 2.0%% to trigger circuit breaker")
	}
	if !fileExists(cfg.DailyLockPath) {
		t.Fatalf("expected daily lock file %s to be created", cfg.DailyLockPath)
	}
}

func TestHardDrawdownKillswitchDivByZeroSafe(t *testing.T) {
	// Peak <= 0.0 must return 0.0% without division-by-zero or panic
	dd1 := CalculateDrawdownPct(0.0, 1000.0)
	if dd1 != 0.0 {
		t.Fatalf("expected 0.0 for peak 0.0, got %f", dd1)
	}

	dd2 := CalculateDrawdownPct(-500.0, 1000.0)
	if dd2 != 0.0 {
		t.Fatalf("expected 0.0 for negative peak, got %f", dd2)
	}

	dd3 := CalculateDrawdownPct(10000.0, 10500.0)
	if dd3 != 0.0 {
		t.Fatalf("expected 0.0 when equity > peak, got %f", dd3)
	}

	dd4 := CalculateDrawdownPct(10000.0, 9000.0)
	if math.Abs(dd4-10.0) > 1e-6 {
		t.Fatalf("expected 10.0%% drawdown, got %f", dd4)
	}
}

func TestHardDrawdownKillswitchTrigger(t *testing.T) {
	dbPath, cleanup := createTestDB(t)
	defer cleanup()

	tmpDir, err := os.MkdirTemp("", "lock_test_*")
	if err != nil {
		t.Fatalf("mkdir temp: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	cfg := DefaultConfig()
	cfg.KillswitchLockPath = filepath.Join(tmpDir, "EMERGENCY_KILLSWITCH.lock")
	cfg.PeakEquity = 10000.0

	roDB, err := OpenReadOnly(dbPath)
	if err != nil {
		t.Fatalf("open ro db: %v", err)
	}
	defer roDB.Close()

	procMock := &mockProcessManager{}
	cb := NewCircuitBreaker(cfg, roDB, procMock)

	// Drawdown: 10,000 -> 8,900 = 11.0% >= 10.0%
	state := &SystemState{
		EquityUSD: 8900.0,
	}

	triggered, err := cb.CheckDrawdown(context.Background(), state)
	if err != nil {
		t.Fatalf("unexpected error checking drawdown: %v", err)
	}
	if !triggered {
		t.Fatalf("expected drawdown >= 10.0%% to trigger killswitch")
	}
	if !fileExists(cfg.KillswitchLockPath) {
		t.Fatalf("expected killswitch lock file %s to be created", cfg.KillswitchLockPath)
	}
	if !procMock.terminated {
		t.Fatalf("expected ProcessManager.TerminateProcess to be called")
	}
}

func TestDeadmanSwitchWithActivePosition(t *testing.T) {
	dbPath, cleanup := createTestDB(t)
	defer cleanup()

	tmpDir, err := os.MkdirTemp("", "lock_test_*")
	if err != nil {
		t.Fatalf("mkdir temp: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	cfg := DefaultConfig()
	cfg.KillswitchLockPath = filepath.Join(tmpDir, "EMERGENCY_KILLSWITCH.lock")
	cfg.DeadmanTimeout = 60 * time.Second
	cfg.PeakEquity = 10000.0

	roDB, err := OpenReadOnly(dbPath)
	if err != nil {
		t.Fatalf("open ro db: %v", err)
	}
	defer roDB.Close()

	procMock := &mockProcessManager{}
	cb := NewCircuitBreaker(cfg, roDB, procMock)

	now := time.Now().UTC()
	// Last updated 65 seconds ago with 1 active position
	state := &SystemState{
		ActivePositionsCount: 1,
		EquityUSD:            10000.0,
		LastUpdatedUTC:       now.Add(-65 * time.Second).Format(time.RFC3339),
	}

	triggered, err := cb.CheckDeadman(context.Background(), now, state)
	if err != nil {
		t.Fatalf("unexpected error checking deadman: %v", err)
	}
	if !triggered {
		t.Fatalf("expected deadman switch to trigger when active_positions_count > 0 and elapsed > 60s")
	}
	if !procMock.terminated || procMock.lastReason != "deadman_switch_timeout" {
		t.Fatalf("expected termination with reason 'deadman_switch_timeout', got '%s'", procMock.lastReason)
	}
}

func TestDeadmanSwitchWithoutActivePosition(t *testing.T) {
	dbPath, cleanup := createTestDB(t)
	defer cleanup()

	cfg := DefaultConfig()
	cfg.DeadmanTimeout = 60 * time.Second

	roDB, err := OpenReadOnly(dbPath)
	if err != nil {
		t.Fatalf("open ro db: %v", err)
	}
	defer roDB.Close()

	procMock := &mockProcessManager{}
	cb := NewCircuitBreaker(cfg, roDB, procMock)

	now := time.Now().UTC()
	// Silence > 60s, BUT active_positions_count is 0
	state := &SystemState{
		ActivePositionsCount: 0,
		EquityUSD:            10000.0,
		LastUpdatedUTC:       now.Add(-120 * time.Second).Format(time.RFC3339),
	}

	triggered, err := cb.CheckDeadman(context.Background(), now, state)
	if err != nil {
		t.Fatalf("unexpected error checking deadman: %v", err)
	}
	if triggered {
		t.Fatalf("deadman switch must NOT trigger when active_positions_count == 0")
	}
	if procMock.terminated {
		t.Fatalf("ProcessManager.TerminateProcess should NOT be called when no positions active")
	}
}

func TestStalePIDProtection(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "pid_test_*")
	if err != nil {
		t.Fatalf("mkdir temp: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	pidPath := filepath.Join(tmpDir, "python_engine.pid")
	logPath := filepath.Join(tmpDir, "emergency.log")

	// Write non-existent stale PID
	if err := os.WriteFile(pidPath, []byte("999999"), 0o644); err != nil {
		t.Fatalf("write pid file: %v", err)
	}

	mgr := NewOSProcessManager(pidPath, logPath, 50*time.Millisecond)
	err = mgr.TerminateProcess(context.Background(), "test_stale_pid")
	if err != nil {
		t.Fatalf("expected stale PID to safely return nil, got: %v", err)
	}

	// Verify emergency log recorded safe handling
	logData, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("expected emergency log to exist: %v", err)
	}
	if !strings.Contains(string(logData), "Stale PID protection active") {
		t.Fatalf("expected log to indicate stale PID protection, got: %s", string(logData))
	}
}

func TestProcessTerminationSIGKILLEscalation(t *testing.T) {
	tmpDir, err := os.MkdirTemp("", "escalation_test_*")
	if err != nil {
		t.Fatalf("mkdir temp: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	var cmd *exec.Cmd
	if runtime.GOOS == "windows" {
		cmd = exec.Command("powershell", "-NoProfile", "-Command", "Start-Sleep -Seconds 30")
	} else {
		cmd = exec.Command("sleep", "30")
	}
	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start mock child process: %v", err)
	}
	pid := cmd.Process.Pid

	pidPath := filepath.Join(tmpDir, "python_engine.pid")
	logPath := filepath.Join(tmpDir, "emergency.log")
	if err := os.WriteFile(pidPath, []byte(fmt.Sprintf("%d", pid)), 0o644); err != nil {
		t.Fatalf("write pid file: %v", err)
	}

	mgr := NewOSProcessManager(pidPath, logPath, 100*time.Millisecond)
	if !mgr.IsProcessAlive(pid) {
		t.Fatalf("mock process should be alive before termination")
	}

	err = mgr.TerminateProcess(context.Background(), "test_escalation")
	if err != nil {
		t.Fatalf("terminate process error: %v", err)
	}

	time.Sleep(300 * time.Millisecond)
	if mgr.IsProcessAlive(pid) {
		t.Fatalf("expected process PID %d to be dead after SIGKILL escalation", pid)
	}
}

func TestSQLitePureReadOnlyIsolation(t *testing.T) {
	dbPath, cleanup := createTestDB(t)
	defer cleanup()

	roDB, err := OpenReadOnly(dbPath)
	if err != nil {
		t.Fatalf("open read-only db: %v", err)
	}
	defer roDB.Close()

	// Normal read query must succeed
	state, err := roDB.GetSystemState(context.Background())
	if err != nil {
		t.Fatalf("read query failed: %v", err)
	}
	if state.State != "NORMAL" {
		t.Fatalf("expected state NORMAL, got %s", state.State)
	}

	// Attempting write query must be strictly rejected by SQLite query_only=true
	writeErr := roDB.ExecWriteTest(context.Background())
	if writeErr == nil {
		t.Fatalf("expected write query to be rejected with read-only error, but it succeeded!")
	}
	if !strings.Contains(strings.ToLower(writeErr.Error()), "readonly") {
		t.Fatalf("expected error to contain 'readonly', got: %v", writeErr)
	}
}

func TestPanicRecoveryMiddleware(t *testing.T) {
	panicHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		panic("deliberate test panic for recovery verification")
	})

	wrapped := PanicRecoveryMiddleware(panicHandler)
	req := httptest.NewRequest(http.MethodGet, "/v1/test_panic", nil)
	rec := httptest.NewRecorder()

	// Should not crash the process
	wrapped.ServeHTTP(rec, req)

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("expected status 500 on panic, got %d", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "internal_server_panic") {
		t.Fatalf("expected body to contain 'internal_server_panic', got: %s", rec.Body.String())
	}
}
