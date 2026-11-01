// Package main
// Module: watchdog.server
// Responsibility: Localhost HTTP IPC Server 127.0.0.1:20129 for Python pre-entry handshake.
// Owner: aeterna-risk
// Tier: A

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"runtime/debug"
	"time"
)

// Server wraps the localhost HTTP IPC server instance.
type Server struct {
	cfg        *Config
	gate       *RiskGate
	httpServer *http.Server
}

// PanicRecoveryMiddleware captures panics and ensures zero silent crash for HTTP handlers.
func PanicRecoveryMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				log.Printf("[PANIC_RECOVERED] Watchdog HTTP handler recovered: %v\nStack:\n%s", rec, debug.Stack())
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(http.StatusInternalServerError)
				_ = json.NewEncoder(w).Encode(OrderResponse{
					Allowed: false,
					Reason:  "internal_server_panic",
				})
			}
		}()
		next.ServeHTTP(w, r)
	})
}

// NewServer configures routes and returns an initialized Server instance.
func NewServer(cfg *Config, gate *RiskGate) *Server {
	mux := http.NewServeMux()
	srv := &Server{
		cfg:  cfg,
		gate: gate,
	}

	mux.HandleFunc("POST /v1/validate_order", srv.handleValidateOrder)
	mux.HandleFunc("GET /v1/status", srv.handleStatus)

	srv.httpServer = &http.Server{
		Addr:              cfg.IPCBindAddr,
		Handler:           PanicRecoveryMiddleware(mux),
		ReadHeaderTimeout: 3 * time.Second,
		ReadTimeout:       5 * time.Second,
		WriteTimeout:      5 * time.Second,
		IdleTimeout:       30 * time.Second,
	}
	return srv
}

// handleValidateOrder processes pre-entry validation requests from Python.
func (s *Server) handleValidateOrder(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"allowed":false,"reason":"method_not_allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req OrderRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		_ = json.NewEncoder(w).Encode(OrderResponse{
			Allowed: false,
			Reason:  "invalid_json_payload",
		})
		return
	}

	resp, err := s.gate.ValidateOrder(r.Context(), &req)
	if err != nil {
		log.Printf("[WARN] Order validation encountered error: %v", err)
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(resp)
}

// handleStatus reports watchdog health and lock file states.
func (s *Server) handleStatus(w http.ResponseWriter, r *http.Request) {
	status := map[string]any{
		"service":           "aeterna-watchdog",
		"status":            "RUNNING",
		"timestamp_utc":     time.Now().UTC().Format(time.RFC3339),
		"daily_lock_active": fileExists(s.cfg.DailyLockPath),
		"killswitch_active": fileExists(s.cfg.KillswitchLockPath),
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(status)
}

// Start runs the HTTP listener on the configured bind address.
func (s *Server) Start() error {
	log.Printf("[INFO] Starting Watchdog HTTP IPC on %s", s.cfg.IPCBindAddr)
	if err := s.httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return fmt.Errorf("http listen and serve: %w", err)
	}
	return nil
}

// Shutdown gracefully terminates the HTTP listener.
func (s *Server) Shutdown(ctx context.Context) error {
	log.Printf("[INFO] Shutting down Watchdog HTTP IPC")
	return s.httpServer.Shutdown(ctx)
}
