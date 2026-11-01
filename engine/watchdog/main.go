// Package main
// Module: watchdog.main
// Responsibility: Entrypoint: graceful shutdown, background ticker monitor, panic-free goroutines.
// Owner: aeterna-risk
// Tier: A

package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"runtime/debug"
	"syscall"
	"time"
)

// runMonitorTick performs a single 1 Hz monitoring evaluation of system state.
func runMonitorTick(ctx context.Context, cb *CircuitBreaker, db DatabaseReader) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("[PANIC_RECOVERED] Monitor tick recovered: %v\nStack:\n%s", r, debug.Stack())
		}
	}()

	state, err := db.GetSystemState(ctx)
	if err != nil {
		log.Printf("[WARN] Monitor tick failed to read system_state: %v", err)
		return
	}

	if _, err := cb.CheckDailyLoss(ctx, state); err != nil {
		log.Printf("[ERROR] Daily loss check failed: %v", err)
	}

	if _, err := cb.CheckDrawdown(ctx, state); err != nil {
		log.Printf("[ERROR] Drawdown check failed: %v", err)
	}

	if _, err := cb.CheckDeadman(ctx, time.Now().UTC(), state); err != nil {
		log.Printf("[ERROR] Deadman check failed: %v", err)
	}
}

// startMonitorLoop runs the background 1 Hz ticker loop panic-free until context cancel.
func startMonitorLoop(ctx context.Context, cb *CircuitBreaker, db DatabaseReader) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("[PANIC_RECOVERED] Watchdog monitor loop recovered: %v\nStack:\n%s", r, debug.Stack())
		}
	}()

	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Printf("[INFO] Monitor ticker stopped via context cancellation.")
			return
		case <-ticker.C:
			runMonitorTick(ctx, cb, db)
		}
	}
}

func main() {
	cfg := DefaultConfig()
	flag.StringVar(&cfg.IPCBindAddr, "bind", cfg.IPCBindAddr, "IPC bind address (localhost only)")
	flag.StringVar(&cfg.DBPath, "db", cfg.DBPath, "SQLite database file path")
	flag.StringVar(&cfg.PIDFilePath, "pid-file", cfg.PIDFilePath, "Python engine PID file path")
	flag.Parse()

	log.Printf("[INFO] Initializing AETERNA Risk Watchdog Daemon (Go 1.22)...")

	db, err := OpenReadOnly(cfg.DBPath)
	if err != nil {
		log.Fatalf("[FATAL] Failed to open SQLite read-only connection: %v", err)
	}
	defer db.Close()

	procMgr := NewOSProcessManager(cfg.PIDFilePath, cfg.EmergencyLogPath, cfg.SigkillGracePeriod)
	gate := NewRiskGate(cfg, db)
	cb := NewCircuitBreaker(cfg, db, procMgr)
	srv := NewServer(cfg, gate)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go func() {
		defer func() {
			if r := recover(); r != nil {
				log.Printf("[PANIC_RECOVERED] HTTP Server runner recovered: %v\nStack:\n%s", r, debug.Stack())
			}
		}()
		if err := srv.Start(); err != nil {
			log.Printf("[ERROR] HTTP Server stopped: %v", err)
		}
	}()

	go startMonitorLoop(ctx, cb, db)

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	sig := <-sigChan
	log.Printf("[INFO] Received signal %v, commencing graceful shutdown...", sig)
	cancel()

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer shutdownCancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("[WARN] HTTP Server graceful shutdown error: %v", err)
	}
	log.Printf("[INFO] AETERNA Watchdog Daemon terminated cleanly.")
}
