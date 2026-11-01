"""AETERNA Quant — 5-Pillar Ecosystem Safety & Invariant Verifier.

Extreme Auditor: Memvalidasi integritas ekosistem sebelum kode diizinkan berstatus MERGE_READY.
Menolak keras:
1. Pelanggaran konstanta risiko keuangan (risk > 0.5%, daily loss > 2.0%, DD > 10.0%)
2. Import LLM / cloud AI di jalur engine produksi (Zero-LLM violation)
3. Gangguan proses/port 9router (port 20128)
4. Penyamaran error finansial/Monte Carlo (return 0.0 / None / is_nan silent fallback)
5. Kegagalan linter, strict typecheck, dan unit tests (Python, Rust, Go)

Usage:
  uv run python scripts/verify_ecosystem.py           # Full multi-stack audit
  uv run python scripts/verify_ecosystem.py --safety   # Invariant & Safety audit only
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent

# ============================================================================
# Hard Invariants Configuration
# ============================================================================

FORBIDDEN_PROD_IMPORTS: tuple[tuple[str, str], ...] = (
    ("openai", "Cloud AI provider di jalur engine produksi"),
    ("anthropic", "Cloud AI provider di jalur engine produksi"),
    ("langchain", "LLM framework di jalur engine produksi"),
)

FORBIDDEN_CONVERSATIONAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bAutoModelForCausalLM\b", "Conversational causal LLM di jalur produksi"),
    (r"\bAutoModelForSeq2SeqLM\b", "Conversational seq2seq LLM di jalur produksi"),
    (r"\bpipeline\s*\(\s*['\"](?:text-generation|conversational|chat)", "Generative text pipeline di jalur produksi"),
)

DO_NOT_KILL_TARGETS: tuple[str, ...] = ("20128", "9router")


class AuditCheck(NamedTuple):
    pillar: str
    name: str
    passed: bool
    details: str


def scan_fail_fast_financial_math(engine_dir: Path) -> list[str]:
    """Scan engine Rust and Python code for disguised silent failures (0.0 / None).

    Enforces Fail-Fast Fault-Out: Financial math, margin, and Monte Carlo must
    propagate hard errors (Result::Err or Exception), never swallow via dummy fallback.
    """
    violations: list[str] = []

    for root, dirs, files in os.walk(engine_dir):
        # Prune heavy build and cache directories
        dirs[:] = [d for d in dirs if d not in ("target", "__pycache__", ".git")]
        for file in files:
            if not file.endswith((".py", ".rs")):
                continue

            fp = Path(root) / file
            rel_path = fp.relative_to(WORKSPACE_ROOT)
            lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()

            for i, line in enumerate(lines):
                clean = line.strip()

                # 1. Direct one-line Err(_) => 0.0 or None
                if re.search(r"Err\([^)]*\)\s*=>\s*(?:0(?:\.0)?|None)\b", clean):
                    violations.append(f"{rel_path}:{i+1} Result::Err dipaksa return 0.0/None: '{clean}'")

                # 2. Python one-line except: return 0.0 or pass
                if re.search(r"\bexcept\b.*:\s*(?:pass|return\s+(?:0(?:\.0)?|None))\b", clean):
                    violations.append(f"{rel_path}:{i+1} Exception ditelan jadi pass/0.0/None: '{clean}'")

                # 3. Sliding multi-line window (lookahead 4 lines for disguised blocks)
                if re.search(r"\b(?:except\b|if\s+.*(?:is_nan|isnan)|Err\s*\()", clean):
                    window = " ".join(l.strip() for l in lines[i : min(len(lines), i + 4)])

                    if re.search(r"(?:is_nan|isnan)\b.*(?:return\s+(?:0(?:\.0)?|None)|=>\s*(?:0(?:\.0)?|None))", window):
                        violations.append(f"{rel_path}:{i+1} Deteksi NaN disamarkan jadi 0.0/None: '{window}'")
                    elif re.search(r"\bexcept\b.*(?:\bpass\b|return\s+(?:0(?:\.0)?|None)\b)", window):
                        violations.append(f"{rel_path}:{i+1} Blok except menyembunyikan error finansial: '{window}'")
                    elif re.search(r"Err\s*\([^)]*\)\s*=>\s*\{[^}]*\b(?:0(?:\.0)?|None)\s*;?\s*\}", window):
                        violations.append(f"{rel_path}:{i+1} Match block Err dipaksa return 0.0/None: '{window}'")

    return violations


def scan_production_invariants() -> list[AuditCheck]:
    """Scan engine/ and instruments/ for architectural & safety violations."""
    checks: list[AuditCheck] = []
    engine_dir = WORKSPACE_ROOT / "engine"
    params_file = WORKSPACE_ROOT / "instruments" / "xauusd" / "config" / "parameters.yaml"

    # 0. Fail-Fast Fault-Out (Anti-Silent Swallowing) Scan
    fail_fast_violations = scan_fail_fast_financial_math(engine_dir)
    checks.append(
        AuditCheck(
            pillar="Pilar 2: Financial Safety",
            name="Fail-Fast Fault-Out (No 0.0/None Swallowing)",
            passed=len(fail_fast_violations) == 0,
            details="Clean (Zero silent fallbacks; errors fail-fast)"
            if not fail_fast_violations
            else "; ".join(fail_fast_violations[:3]),
        )
    )

    # 1. Zero-LLM Production Invariant Scan
    llm_violations: list[str] = []
    for py_file in engine_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        for pkg, reason in FORBIDDEN_PROD_IMPORTS:
            if re.search(rf"\bimport\s+{pkg}\b|\bfrom\s+{pkg}\b", content):
                llm_violations.append(f"{py_file.name}: {reason}")
        for pattern, reason in FORBIDDEN_CONVERSATIONAL_PATTERNS:
            if re.search(pattern, content):
                llm_violations.append(f"{py_file.name}: {reason}")

    checks.append(
        AuditCheck(
            pillar="Pilar 3: Runtime Safety",
            name="Zero-LLM Production Boundary",
            passed=len(llm_violations) == 0,
            details="Clean (Zero external LLMs in engine)" if not llm_violations else "; ".join(llm_violations),
        )
    )

    # 2. Do Not Kill 9router (Port 20128) Protection Scan
    kill_violations: list[str] = []
    scan_files = list(engine_dir.rglob("*.py")) + list((WORKSPACE_ROOT / "scripts").rglob("*.py"))
    for code_file in scan_files:
        content = code_file.read_text(encoding="utf-8", errors="ignore")
        if (
            any(term in content for term in DO_NOT_KILL_TARGETS)
            and ("Stop-Process" in content or "kill" in content.lower())
            and code_file.name != "verify_ecosystem.py"
        ):
            kill_violations.append(f"{code_file.name}: Potensi kill command pada proses 9router (port 20128)")

    checks.append(
        AuditCheck(
            pillar="Pilar 3: Runtime Safety",
            name="9router (Port 20128) Immunity",
            passed=len(kill_violations) == 0,
            details="Clean (Zero 9router termination commands)" if not kill_violations else "; ".join(kill_violations),
        )
    )

    # 3. Parameters YAML Drift Check (Strict Fail-Fast on missing keys)
    param_violations: list[str] = []
    if not params_file.exists():
        param_violations.append(f"File konfigurasi tidak ditemukan: {params_file.relative_to(WORKSPACE_ROOT)}")
    else:
        text = params_file.read_text(encoding="utf-8")
        m_risk = re.search(r"risk_per_trade_pct:\s*([\d.]+)", text)
        m_loss = re.search(r"max_daily_loss_pct:\s*([\d.]+)", text)
        m_dd = re.search(r"max_drawdown_killswitch_pct:\s*([\d.]+)", text)

        # Enforce presence: Missing keys MUST fail hard, not silently pass
        if m_risk is None:
            param_violations.append("Key wajib 'risk_per_trade_pct' tidak ditemukan di parameters.yaml")
        elif float(m_risk.group(1)) > 0.5:
            param_violations.append(f"risk_per_trade_pct ({m_risk.group(1)}%) > 0.5% (invariant violation)")

        if m_loss is None:
            param_violations.append("Key wajib 'max_daily_loss_pct' tidak ditemukan di parameters.yaml")
        elif float(m_loss.group(1)) > 2.0:
            param_violations.append(f"max_daily_loss_pct ({m_loss.group(1)}%) > 2.0% (invariant violation)")

        if m_dd is None:
            param_violations.append("Key wajib 'max_drawdown_killswitch_pct' tidak ditemukan di parameters.yaml")
        elif float(m_dd.group(1)) > 10.0:
            param_violations.append(f"max_drawdown_killswitch_pct ({m_dd.group(1)}%) > 10.0% (invariant violation)")

    checks.append(
        AuditCheck(
            pillar="Pilar 2: Financial Safety",
            name="Numerical Invariants Conformance",
            passed=len(param_violations) == 0,
            details="Parameters locked at invariant thresholds" if not param_violations else "; ".join(param_violations),
        )
    )

    return checks


def run_command(cmd: list[str], cwd: Path = WORKSPACE_ROOT) -> tuple[bool, str]:
    """Execute a shell command and return status and output."""
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        return (res.returncode == 0, (res.stdout + res.stderr).strip())
    except (subprocess.SubprocessError, OSError) as e:
        return (False, str(e))


def run_full_suite() -> list[AuditCheck]:
    """Execute multi-stack testing and linting suite."""
    checks = scan_production_invariants()

    # Python Lint & Typecheck
    ok_ruff, out_ruff = run_command(["uv", "run", "ruff", "check", "."])
    checks.append(
        AuditCheck("Pilar 1: Test Authenticity", "Python Ruff Lint", ok_ruff, "Clean" if ok_ruff else out_ruff[:120])
    )

    ok_pyright, out_pyright = run_command(["uv", "run", "pyright"])
    checks.append(
        AuditCheck("Pilar 1: Test Authenticity", "Python Pyright Strict", ok_pyright, "0 errors" if ok_pyright else out_pyright[:120])
    )

    # Python Unit Tests
    ok_pytest, out_pytest = run_command(["uv", "run", "pytest", "tests/", "-v"])
    checks.append(
        AuditCheck("Pilar 1: Test Authenticity", "Python Unit & Golden Tests", ok_pytest, "Passed" if ok_pytest else out_pytest[:120])
    )

    # Rust Checks (if crate exists)
    rust_dir = WORKSPACE_ROOT / "engine" / "analysis_engine" / "rust"
    if (rust_dir / "Cargo.toml").exists():
        ok_clippy, out_clippy = run_command(
            ["uv", "run", "cargo", "clippy", "--all-targets", "--", "-D", "warnings"], cwd=rust_dir
        )
        checks.append(
            AuditCheck("Pilar 3: Runtime Safety", "Rust Clippy", ok_clippy, "Clean" if ok_clippy else out_clippy[:120])
        )

        ok_cargo_test, out_cargo = run_command(["uv", "run", "cargo", "test", "--all"], cwd=rust_dir)
        checks.append(
            AuditCheck(
                "Pilar 2: Financial Safety",
                "Rust Backtest Simulation Tests",
                ok_cargo_test,
                "Passed" if ok_cargo_test else out_cargo[:120],
            )
        )

    # Go Checks (if go.mod exists and packages are present)
    go_watchdog_dir = WORKSPACE_ROOT / "engine" / "watchdog"
    if (go_watchdog_dir / "go.mod").exists():
        ok_vet, out_vet = run_command(["go", "vet", "./..."], cwd=go_watchdog_dir)
        checks.append(AuditCheck("Pilar 3: Runtime Safety", "Go Vet", ok_vet, "Clean" if ok_vet else out_vet[:120]))
    elif (WORKSPACE_ROOT / "go.mod").exists():
        # Check if any .go files exist before invoking go vet
        go_files = list((WORKSPACE_ROOT / "engine").rglob("*.go"))
        if go_files:
            ok_vet, out_vet = run_command(["go", "vet", "./..."])
            checks.append(AuditCheck("Pilar 3: Runtime Safety", "Go Vet", ok_vet, "Clean" if ok_vet else out_vet[:120]))
        else:
            checks.append(
                AuditCheck(
                    "Pilar 3: Runtime Safety",
                    "Go Vet",
                    True,
                    "Skipped (No .go files in engine/ yet; baseline module valid)",
                )
            )

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Aeterna Ecosystem Safety Auditor")
    parser.add_argument("--safety", action="store_true", help="Run invariant and safety scan only")
    args = parser.parse_args()

    print("================================================================================")
    print("AETERNA QUANT — 5-PILLAR ECOSYSTEM SAFETY AUDIT")
    print("================================================================================")

    results = scan_production_invariants() if args.safety else run_full_suite()

    all_passed = True
    print(f"{'PILAR':<30} | {'PEMERIKSAAN':<38} | {'STATUS'}")
    print("-" * 80)
    for r in results:
        status_str = "PASS" if r.passed else "FAIL"
        if not r.passed:
            all_passed = False
        print(f"{r.pillar:<30} | {r.name:<38} | {status_str}")
        if not r.passed:
            print(f"  [!] Detail: {r.details}")

    print("================================================================================")
    if all_passed:
        print("VERDICT: ECOSYSTEM SAFE (Lolos Seluruh Pemeriksaan)")
        return 0
    else:
        print("VERDICT: REJECTED (Pelanggaran Invariant / Kegagalan Pengujian Terdeteksi)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
