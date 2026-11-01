// Package main
// Module: watchdog.db
// Responsibility: SQLite WAL 100% pure read-only connection and isolation queries.
// Owner: aeterna-risk
// Tier: A

package main

import (
	"context"
	"database/sql"
	"fmt"
	"path/filepath"

	_ "modernc.org/sqlite"
)

// SystemState represents the singleton row in SQLite IPC system_state table.
type SystemState struct {
	ID                   int64          `json:"id"`
	State                string         `json:"state"`
	CurrentSpread        float64        `json:"current_spread"`
	SpreadBaseline       float64        `json:"spread_baseline"`
	SpreadZScore         float64        `json:"spread_z_score"`
	ActivePositionsCount int            `json:"active_positions_count"`
	EquityUSD            float64        `json:"equity_usd"`
	DailyPnLUSD          float64        `json:"daily_pnl_usd"`
	TradesTodayCount     int            `json:"trades_today_count"`
	LastNewsEvent        sql.NullString `json:"last_news_event"`
	LastUpdatedUTC       string         `json:"last_updated_utc"`
}

// DatabaseReader abstracts read-only access to SQLite for gate and monitors.
type DatabaseReader interface {
	GetSystemState(ctx context.Context) (*SystemState, error)
	GetOpenPositionsCount(ctx context.Context) (int, error)
	GetTradesCountToday(ctx context.Context, datePrefixUTC string) (int, error)
	GetDailyLossUSD(ctx context.Context, datePrefixUTC string) (float64, error)
	ExecWriteTest(ctx context.Context) error
	Close() error
}

// ReadOnlyDB wraps a pure read-only SQLite connection.
type ReadOnlyDB struct {
	db *sql.DB
}

// OpenReadOnly opens a SQLite connection strictly configured with query_only=true.
func OpenReadOnly(dbPath string) (*ReadOnlyDB, error) {
	cleanPath := filepath.ToSlash(filepath.Clean(dbPath))
	dsn := fmt.Sprintf("file:%s?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_pragma=query_only(true)", cleanPath)

	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("open sqlite read-only: %w", err)
	}

	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	db.SetConnMaxLifetime(0)

	if err := db.Ping(); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("ping sqlite read-only: %w", err)
	}

	return &ReadOnlyDB{db: db}, nil
}

// GetSystemState retrieves the single state row with ID = 1.
func (r *ReadOnlyDB) GetSystemState(ctx context.Context) (*SystemState, error) {
	query := `SELECT id, state, current_spread, spread_baseline, spread_z_score,
		active_positions_count, equity_usd, daily_pnl_usd, trades_today_count,
		last_news_event, last_updated_utc
		FROM system_state WHERE id = 1`

	row := r.db.QueryRowContext(ctx, query)
	var s SystemState
	err := row.Scan(
		&s.ID,
		&s.State,
		&s.CurrentSpread,
		&s.SpreadBaseline,
		&s.SpreadZScore,
		&s.ActivePositionsCount,
		&s.EquityUSD,
		&s.DailyPnLUSD,
		&s.TradesTodayCount,
		&s.LastNewsEvent,
		&s.LastUpdatedUTC,
	)
	if err != nil {
		return nil, fmt.Errorf("query system_state: %w", err)
	}
	return &s, nil
}

// GetOpenPositionsCount returns count of trades currently without an exit timestamp.
func (r *ReadOnlyDB) GetOpenPositionsCount(ctx context.Context) (int, error) {
	query := `SELECT COUNT(*) FROM trades WHERE timestamp_exit_utc IS NULL`
	var count int
	if err := r.db.QueryRowContext(ctx, query).Scan(&count); err != nil {
		return 0, fmt.Errorf("query open positions count: %w", err)
	}
	return count, nil
}

// GetTradesCountToday returns count of all trades entered on a given UTC date (YYYY-MM-DD).
func (r *ReadOnlyDB) GetTradesCountToday(ctx context.Context, datePrefixUTC string) (int, error) {
	query := `SELECT COUNT(*) FROM trades WHERE substr(timestamp_entry_utc, 1, 10) = ?`
	var count int
	if err := r.db.QueryRowContext(ctx, query, datePrefixUTC).Scan(&count); err != nil {
		return 0, fmt.Errorf("query trades count today: %w", err)
	}
	return count, nil
}

// GetDailyLossUSD calculates accumulated realized loss for trades closed on datePrefixUTC.
func (r *ReadOnlyDB) GetDailyLossUSD(ctx context.Context, datePrefixUTC string) (float64, error) {
	query := `SELECT COALESCE(SUM(CASE WHEN pnl_usd < 0 THEN ABS(pnl_usd) ELSE 0.0 END), 0.0)
		FROM trades
		WHERE timestamp_exit_utc IS NOT NULL
		  AND substr(timestamp_exit_utc, 1, 10) = ?`

	var loss float64
	if err := r.db.QueryRowContext(ctx, query, datePrefixUTC).Scan(&loss); err != nil {
		return 0.0, fmt.Errorf("query daily loss: %w", err)
	}
	return loss, nil
}

// ExecWriteTest attempts a write operation to verify strict read-only enforcement.
func (r *ReadOnlyDB) ExecWriteTest(ctx context.Context) error {
	query := `UPDATE system_state SET equity_usd = 99999.0 WHERE id = 1`
	_, err := r.db.ExecContext(ctx, query)
	return err
}

// Close gracefully releases the database connection handle.
func (r *ReadOnlyDB) Close() error {
	return r.db.Close()
}
