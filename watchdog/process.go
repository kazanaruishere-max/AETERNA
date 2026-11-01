// Package main
// Module: watchdog.process
// Responsibility: Process manager: PID tracking, stale PID protection, SIGTERM -> 5s grace period -> SIGKILL escalation.
// Owner: aeterna-risk
// Tier: A

package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// ProcessManager defines process tracking and termination lifecycle operations.
type ProcessManager interface {
	TerminateProcess(ctx context.Context, reason string) error
	IsProcessAlive(pid int) bool
	ReadPID() (int, error)
}

// OSProcessManager executes OS-level process management with escalation.
type OSProcessManager struct {
	pidFilePath      string
	emergencyLogPath string
	gracePeriod      time.Duration
}

// NewOSProcessManager creates a configured OSProcessManager.
func NewOSProcessManager(pidFilePath, emergencyLogPath string, gracePeriod time.Duration) *OSProcessManager {
	if gracePeriod <= 0 {
		gracePeriod = DefaultSigkillGracePeriod
	}
	return &OSProcessManager{
		pidFilePath:      pidFilePath,
		emergencyLogPath: emergencyLogPath,
		gracePeriod:      gracePeriod,
	}
}

// ReadPID reads and parses the process ID from the configured PID file.
func (m *OSProcessManager) ReadPID() (int, error) {
	data, err := os.ReadFile(m.pidFilePath)
	if err != nil {
		return 0, fmt.Errorf("read pid file %s: %w", m.pidFilePath, err)
	}
	raw := strings.TrimSpace(string(data))
	pid, err := strconv.Atoi(raw)
	if err != nil {
		return 0, fmt.Errorf("parse pid '%s': %w", raw, err)
	}
	if pid <= 0 {
		return 0, fmt.Errorf("invalid non-positive pid %d", pid)
	}
	return pid, nil
}

// IsProcessAlive checks whether the given PID is actively executing in the OS.
func (m *OSProcessManager) IsProcessAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	if runtime.GOOS == "windows" {
		cmd := exec.Command("tasklist", "/FI", fmt.Sprintf("PID eq %d", pid), "/NH")
		out, err := cmd.Output()
		if err != nil {
			return false
		}
		outStr := string(out)
		return len(outStr) > 0 && !strings.Contains(outStr, "No tasks are running")
	}
	p, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	return p.Signal(syscall.Signal(0)) == nil
}

// logEmergency writes a FATAL audit entry to standard error and emergency log file.
func (m *OSProcessManager) logEmergency(message string) {
	entry := fmt.Sprintf("[%s] [FATAL_EMERGENCY] %s\n", time.Now().UTC().Format(time.RFC3339), message)
	_, _ = fmt.Fprint(os.Stderr, entry)

	dir := filepath.Dir(m.emergencyLogPath)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		log.Printf("[ERROR] Failed to create emergency log directory: %v", err)
		return
	}

	f, err := os.OpenFile(m.emergencyLogPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		log.Printf("[ERROR] Failed to open emergency log file: %v", err)
		return
	}
	defer f.Close()
	_, _ = f.WriteString(entry)
}

// TerminateProcess executes graceful SIGTERM, awaits grace period, then escalates to SIGKILL.
func (m *OSProcessManager) TerminateProcess(ctx context.Context, reason string) error {
	pid, err := m.ReadPID()
	if err != nil {
		m.logEmergency(fmt.Sprintf("PID file unavailable (%v). Stale PID protection active, skipping signal dispatch.", err))
		return nil
	}

	if !m.IsProcessAlive(pid) {
		m.logEmergency(fmt.Sprintf("PID %d is not running in OS. Stale PID protection active, skipping signal dispatch.", pid))
		return nil
	}

	p, err := os.FindProcess(pid)
	if err != nil {
		m.logEmergency(fmt.Sprintf("Failed to acquire process handle for PID %d: %v", pid, err))
		return nil
	}

	m.logEmergency(fmt.Sprintf("Dispatching SIGTERM/Interrupt to PID %d. Reason: %s", pid, reason))
	_ = p.Signal(syscall.SIGTERM)
	_ = p.Signal(os.Interrupt)

	deadline := time.Now().Add(m.gracePeriod)
	for time.Now().Before(deadline) {
		if !m.IsProcessAlive(pid) {
			m.logEmergency(fmt.Sprintf("Process PID %d exited cleanly during grace period.", pid))
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}

	if m.IsProcessAlive(pid) {
		m.logEmergency(fmt.Sprintf("PID %d remained active after %v grace period. Escalating to SIGKILL.", pid, m.gracePeriod))
		if killErr := p.Kill(); killErr != nil {
			m.logEmergency(fmt.Sprintf("Failed to force kill PID %d: %v", pid, killErr))
			return killErr
		}
		m.logEmergency(fmt.Sprintf("Successfully executed SIGKILL on PID %d.", pid))
	}

	return nil
}
