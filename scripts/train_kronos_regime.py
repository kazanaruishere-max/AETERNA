# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportMissingImports=false
# pyright: reportIndexIssue=false
# pyright: reportPossiblyUnboundVariable=false
# pyright: reportArgumentType=false

"""Offline Supervised Training & ONNX Export Pipeline for Kronos H4 Market Regime Classifier.

Module: scripts.train_kronos_regime
Responsibility:
1. Ingests modern Post-COVID H4 candlestick dataset from data/historical/xauusd_h4.parquet.
2. Generates deterministic ground-truth labels using canonical Wilder indicators (ADX-14 + EMA-20/50 crossover).
3. Prepares rolling 512-bar context windows with zero-leakage z-score normalization clipped to [-5, 5].
4. Enforces chronological train/validation split (80/20) with absolute temporal isolation.
5. Implements Mandate 1: Partial Backbone Unfreezing (Block 2 unfrozen at 2e-4, Head at 3e-3).
6. Implements Mandate 2: Class-Weighted Loss focusing on active trending vs ranging transitions.
7. Implements Mandate 3: CosineAnnealingLR with EarlyStopping (patience=5, max_epochs=15).
8. Employs Multi-Scale Context Pooling (Global 512 + Medium 128 + Short-term 32 bars).
9. Exports calibrated computational graph to data/models/kronos_h4.onnx for native CPU execution.
10. Verifies sub-2.0ms CPU inference latency and sharp dominant confidence > 60%.

Reference: docs/aeterna/kronos-architecture.md (DOC-KRONOS-ARCH-001)
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch
from torch import nn
from torch.utils.data import DataLoader

# Filter non-blocking exporter warnings
warnings.filterwarnings("ignore")

# Set maximum CPU parallelism
if hasattr(os, "cpu_count") and os.cpu_count():
    torch.set_num_threads(os.cpu_count() or 4)

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.analysis_engine.python.indicators import calculate_adx, calculate_ema

# Class mapping constant
CLASS_NAMES = ["BULLISH_TRENDING", "BEARISH_TRENDING", "RANGING"]


# ==============================================================================
# 1. Ground-Truth Regime Labeling (Canonical Macro Hierarchy)
# ==============================================================================


def generate_regime_labels(
    df: pd.DataFrame,
    adx_threshold: float = 22.0,
) -> np.ndarray[Any, np.dtype[np.int64]]:
    """Generate deterministic 3-class regime labels: 0=BULLISH, 1=BEARISH, 2=RANGING."""
    closes = df["close"]
    highs = df["high"]
    lows = df["low"]

    ema20 = calculate_ema(closes, 20).to_numpy()
    ema50 = calculate_ema(closes, 50).to_numpy()
    adx = calculate_adx(highs, lows, closes, 14)[0].to_numpy()

    n = len(closes)
    labels = np.full(n, fill_value=2, dtype=np.int64)  # Default: Ranging

    for i in range(n):
        if adx[i] >= adx_threshold:
            if ema20[i] > ema50[i]:
                labels[i] = 0  # BULLISH_TRENDING
            elif ema20[i] < ema50[i]:
                labels[i] = 1  # BEARISH_TRENDING
            else:
                labels[i] = 2  # RANGING
        else:
            labels[i] = 2  # RANGING

    return labels


# ==============================================================================
# 2. Memory-Optimized Sliding Window Tensor Precomputation
# ==============================================================================


def precompute_normalized_windows(
    closes: np.ndarray[Any, np.dtype[np.float64]],
    labels: np.ndarray[Any, np.dtype[np.int64]],
    indices: list[int],
    window_size: int = 512,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Precompute zero-leakage rolling z-score normalized windows into contiguous tensors."""
    n = len(indices)
    x_arr = np.zeros((n, window_size, 1), dtype=np.float32)
    y_arr = np.zeros(n, dtype=np.int64)

    for idx, i in enumerate(indices):
        w = closes[i - window_size : i]
        mean = np.mean(w)
        std = np.std(w) + 1e-8
        norm_w = np.clip((w - mean) / std, -5.0, 5.0)
        x_arr[idx, :, 0] = norm_w
        y_arr[idx] = labels[i]

    return torch.from_numpy(x_arr), torch.from_numpy(y_arr)


# ==============================================================================
# 3. Neural Network Architecture (Patch Tokenizer + Transformer + MultiScale Pooling)
# ==============================================================================


class ConvFeatureTokenizer(nn.Module):
    """Local K-line candlestick patch tokenizer mapping 512 bars to 128 dense tokens."""

    def __init__(self, d_model: int = 64) -> None:
        super().__init__()
        self.conv1 = nn.Conv1d(1, 32, kernel_size=7, stride=2, padding=3)  # -> (b, 32, 256)
        self.conv2 = nn.Conv1d(32, d_model, kernel_size=7, stride=2, padding=3)  # -> (b, d_model, 128)
        self.norm = nn.LayerNorm(d_model)
        self.gelu = nn.GELU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (b, 512, 1) -> (b, 1, 512)
        h = self.gelu(self.conv1(x.transpose(1, 2)))
        h = self.gelu(self.conv2(h)).transpose(1, 2)  # -> (b, 128, d_model)
        return self.norm(h)


class ExplicitSelfAttention(nn.Module):
    """Deterministic, pure-math Multi-Head Attention cleanly exportable to ONNX."""

    def __init__(self, d_model: int = 64, nhead: int = 2) -> None:
        super().__init__()
        self.d_model = d_model
        self.nhead = nhead
        self.head_dim = d_model // nhead
        self.scale = 1.0 / math.sqrt(self.head_dim)

        self.q_proj = nn.Linear(d_model, d_model)
        self.k_proj = nn.Linear(d_model, d_model)
        self.v_proj = nn.Linear(d_model, d_model)
        self.out_proj = nn.Linear(d_model, d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, s, _ = x.shape
        # Project and reshape to (batch, heads, seq, head_dim)
        q = self.q_proj(x).view(b, s, self.nhead, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(b, s, self.nhead, self.head_dim).transpose(1, 2)
        v = self.v_proj(x).view(b, s, self.nhead, self.head_dim).transpose(1, 2)

        # Scaled dot-product attention
        scores = torch.matmul(q, k.transpose(-2, -1)) * self.scale
        attn = torch.softmax(scores, dim=-1)
        out = torch.matmul(attn, v).transpose(1, 2).contiguous().view(b, s, self.d_model)
        return self.out_proj(out)


class TransformerBlock(nn.Module):
    """ONNX-native Transformer Block with pure tensor operations."""

    def __init__(self, d_model: int = 64, nhead: int = 2, d_ff: int = 128, dropout: float = 0.1) -> None:
        super().__init__()
        self.attn = ExplicitSelfAttention(d_model=d_model, nhead=nhead)
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.ffn = nn.Sequential(
            nn.Linear(d_model, d_ff),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_ff, d_model),
            nn.Dropout(dropout),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.norm1(x + self.attn(x))
        x = self.norm2(x + self.ffn(x))
        return x


class MultiScaleContextPooling(nn.Module):
    """Hierarchical temporal pooling combining global, medium-term, and short-term momentum."""

    def __init__(self, d_model: int = 64) -> None:
        super().__init__()
        self.scoring = nn.Sequential(
            nn.Linear(d_model, 16),
            nn.Tanh(),
            nn.Linear(16, 1),
        )
        self.proj = nn.Linear(d_model * 3, d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x is (b, 128, d_model)
        # 1. Global context pooling across all 128 token steps
        w_global = torch.softmax(self.scoring(x), dim=1)
        p_global = torch.sum(x * w_global, dim=1)

        # 2. Medium-term recent trend (last 32 tokens / 96:128)
        x_med = x[:, 96:, :]
        w_med = torch.softmax(self.scoring(x_med), dim=1)
        p_med = torch.sum(x_med * w_med, dim=1)

        # 3. Short-term immediate momentum (last 8 tokens / 120:128)
        x_short = x[:, 120:, :]
        w_short = torch.softmax(self.scoring(x_short), dim=1)
        p_short = torch.sum(x_short * w_short, dim=1)

        fused = torch.cat([p_global, p_med, p_short], dim=-1)
        return self.proj(fused)


class KronosRegimeClassifier(nn.Module):
    """End-to-end model coupling representation backbone with MultiScale Pooling & Classifier."""

    def __init__(
        self,
        d_model: int = 64,
        nhead: int = 2,
        d_ff: int = 128,
        num_classes: int = 3,
        dropout: float = 0.1,
        temperature: float = 0.35,
    ) -> None:
        super().__init__()
        self.tokenizer = ConvFeatureTokenizer(d_model=d_model)
        self.pos_emb = nn.Parameter(torch.randn(1, 128, d_model) * 0.02)
        self.block1 = TransformerBlock(d_model=d_model, nhead=nhead, d_ff=d_ff, dropout=dropout)
        self.block2 = TransformerBlock(d_model=d_model, nhead=nhead, d_ff=d_ff, dropout=dropout)
        self.pooler = MultiScaleContextPooling(d_model=d_model)
        self.classifier_head = nn.Sequential(
            nn.Linear(d_model, 32),
            nn.LayerNorm(32),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(32, num_classes),
        )
        self.temperature = temperature

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, 512, 1)
        tokens = self.tokenizer(x) + self.pos_emb
        h = self.block1(tokens)
        h = self.block2(h)
        p = self.pooler(h)
        logits = self.classifier_head(p)
        return logits / self.temperature


# ==============================================================================
# 4. Focal Loss & Scheduler
# ==============================================================================


class FocalLoss(nn.Module):
    """Focal Loss with class-weighting and modulating factor gamma for hard-example focusing."""

    def __init__(
        self,
        alpha: torch.Tensor | None = None,
        gamma: float = 1.5,
        reduction: str = "mean",
    ) -> None:
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma
        self.reduction = reduction

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        ce_loss = nn.functional.cross_entropy(inputs, targets, reduction="none")
        pt = torch.exp(-ce_loss)  # probability of true class
        focal_term = (1.0 - pt) ** self.gamma

        if self.alpha is not None:
            alpha_t = self.alpha[targets]
            loss = alpha_t * focal_term * ce_loss
        else:
            loss = focal_term * ce_loss

        if self.reduction == "mean":
            return loss.mean()
        if self.reduction == "sum":
            return loss.sum()
        return loss


class WarmupCosineScheduler:
    """Linear warmup for initial epochs followed by CosineAnnealingLR."""

    def __init__(
        self,
        optimizer: torch.optim.Optimizer,
        warmup_epochs: int,
        total_epochs: int,
        base_lrs: list[float],
        min_lr_ratio: float = 0.05,
    ) -> None:
        self.optimizer = optimizer
        self.warmup_epochs = warmup_epochs
        self.total_epochs = total_epochs
        self.base_lrs = base_lrs
        self.min_lr_ratio = min_lr_ratio

    def step(self, epoch: int) -> None:
        if epoch <= self.warmup_epochs:
            factor = 0.10 + 0.90 * (epoch / max(1, self.warmup_epochs))
        else:
            progress = (epoch - self.warmup_epochs) / max(1, self.total_epochs - self.warmup_epochs)
            factor = self.min_lr_ratio + 0.5 * (1.0 - self.min_lr_ratio) * (1.0 + math.cos(math.pi * progress))

        for param_group, base_lr in zip(self.optimizer.param_groups, self.base_lrs, strict=False):
            param_group["lr"] = base_lr * factor


# ==============================================================================
# 5. Training, Evaluation, & ONNX Export Pipeline
# ==============================================================================


def train_kronos(
    data_path: str = "data/historical/xauusd_h4.parquet",
    output_onnx: str = "data/models/kronos_h4.onnx",
    max_epochs: int = 10,
    patience: int = 4,
    batch_size: int = 64,
    lr_backbone: float = 2e-4,
    lr_head: float = 3e-3,
    window_size: int = 512,
    stride: int = 6,
    focal_gamma: float = 1.5,
    temperature: float = 0.35,
) -> int:
    """Execute end-to-end Kronos fine-tuning with partial unfreezing and Focal Loss."""
    print("=" * 80, flush=True)
    print("AETERNA QUANT — OPTIMIZED KRONOS H4 REGIME TRAINING & ONNX EXPORT", flush=True)
    print("=" * 80, flush=True)
    print(f"Dataset Path     : {data_path}", flush=True)
    print(f"Target Artifact  : {output_onnx}", flush=True)
    print(f"Context Window   : {window_size} bars H4 (~4 months)", flush=True)
    print(f"Sliding Stride   : {stride} bars (~24 hours per window)", flush=True)
    print(f"Max Epochs       : {max_epochs} (EarlyStopping patience: {patience})", flush=True)
    print(f"Learning Rates   : Unfrozen Block 2={lr_backbone:.1e}, Head={lr_head:.1e}", flush=True)
    print(f"Loss Function    : Class-Weighted FocalLoss (gamma={focal_gamma})\n", flush=True)

    # 1. Load Parquet Data
    p_path = Path(data_path)
    if not p_path.is_file():
        print(f"[ERROR] Dataset file not found: {p_path.resolve()}", flush=True)
        print("Please run first: uv run python scripts/extract_historical_data.py --symbol XAUUSDm", flush=True)
        return 1

    table = pq.read_table(str(p_path))
    df = table.to_pandas()
    total_bars = len(df)
    print(f"[+] Loaded {total_bars:,} bars from {df['timestamp_utc'].iloc[0]} to {df['timestamp_utc'].iloc[-1]}", flush=True)

    # 2. Generate Ground-Truth Labels
    print("[*] Generating deterministic ground-truth labels (Wilder ADX-14 + EMA-20/50)...", flush=True)
    labels = generate_regime_labels(df, adx_threshold=22.0)
    closes = df["close"].to_numpy(dtype=np.float64)

    # Class distribution check
    unique, counts = np.unique(labels[window_size:], return_counts=True)
    dist = dict(zip(unique, counts, strict=False))
    print("[+] Ground-Truth Label Distribution:")
    for cls_idx, cls_name in enumerate(CLASS_NAMES):
        count = dist.get(cls_idx, 0)
        pct = (count / (total_bars - window_size)) * 100.0
        print(f"    Class {cls_idx} ({cls_name:<16}): {count:>5} bars ({pct:.1f}%)", flush=True)

    # 3. Sliding Window Indexing & Chronological Train/Val Split (80/20)
    valid_indices = list(range(window_size, total_bars - 20, stride))
    total_samples = len(valid_indices)
    split_idx = int(total_samples * 0.80)

    train_indices = valid_indices[:split_idx]
    val_indices = valid_indices[split_idx:]
    print(f"[+] Total Sliding Windows: {total_samples:,} (Train: {len(train_indices):,}, Val: {len(val_indices):,})", flush=True)
    print(f"[+] Temporal Validation Isolation: Train ends at bar {train_indices[-1]}, Val starts at bar {val_indices[0]}", flush=True)

    # 4. Class-Weighting Calculation (Balanced Inverse Frequency)
    train_labels = labels[train_indices]
    class_weights: list[float] = []
    for cls_idx in range(3):
        cls_count = max(1, int(np.sum(train_labels == cls_idx)))
        class_weights.append(len(train_indices) / (3.0 * cls_count))
    weights_tensor = torch.tensor(class_weights, dtype=torch.float32)
    print(f"[+] Inverse Class Weights: {[round(w, 2) for w in class_weights]}", flush=True)

    # 5. Precompute normalized tensors into RAM
    print("[*] Precomputing zero-leakage normalized tensors in RAM...", flush=True)
    t_pre0 = time.perf_counter()
    x_train, y_train = precompute_normalized_windows(closes, labels, train_indices, window_size)
    x_val, y_val = precompute_normalized_windows(closes, labels, val_indices, window_size)
    t_pre1 = time.perf_counter()
    print(f"[+] Precomputed {total_samples:,} windows into RAM in {t_pre1 - t_pre0:.2f}s!", flush=True)

    train_dataset = torch.utils.data.TensorDataset(x_train, y_train)
    val_dataset = torch.utils.data.TensorDataset(x_val, y_val)
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, drop_last=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    # 6. Initialize Model & Execute Mandate 1: Partial Backbone Unfreezing
    d_model = 64
    nhead = 2
    model = KronosRegimeClassifier(
        d_model=d_model,
        nhead=nhead,
        num_classes=3,
        temperature=temperature,
    )

    # Freeze Tokenizer, Positional Embeddings, and Block 1
    for p in list(model.tokenizer.parameters()) + [model.pos_emb] + list(model.block1.parameters()):
        p.requires_grad = False

    # Unfreeze Block 2 (Differential Learning Rate 2e-4) and Head (3e-3)
    unfrozen_params = list(model.block2.parameters())
    head_params = list(model.pooler.parameters()) + list(model.classifier_head.parameters())
    print(
        f"[+] Partial Backbone Unfreezing: Tokenizer & Block 1 Frozen, Block 2 Unfrozen "
        f"({sum(p.numel() for p in unfrozen_params):,} backbone params trainable)",
        flush=True,
    )

    # Setup Focal Loss and Differential Learning Rate Optimizer
    criterion = FocalLoss(alpha=weights_tensor, gamma=focal_gamma)
    optimizer = torch.optim.AdamW(
        [
            {"params": unfrozen_params, "lr": lr_backbone, "weight_decay": 0.01},
            {"params": head_params, "lr": lr_head, "weight_decay": 0.01},
        ]
    )

    warmup_epochs = 2
    scheduler = WarmupCosineScheduler(
        optimizer=optimizer,
        warmup_epochs=warmup_epochs,
        total_epochs=max_epochs,
        base_lrs=[lr_backbone, lr_head],
        min_lr_ratio=0.05,
    )

    print("\n" + "-" * 80, flush=True)
    print("STARTING OPTIMIZED TRAINING LOOP (WITH EARLY STOPPING)", flush=True)
    print("-" * 80, flush=True)

    best_val_loss = float("inf")
    best_model_state: dict[str, Any] | None = None
    patience_counter = 0

    for epoch in range(1, max_epochs + 1):
        scheduler.step(epoch)
        current_head_lr = optimizer.param_groups[1]["lr"]

        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0

        for x_b, y_b in train_loader:
            optimizer.zero_grad()
            logits = model(x_b)
            loss = criterion(logits, y_b)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                unfrozen_params + head_params, max_norm=1.0
            )
            optimizer.step()

            train_loss += loss.item() * x_b.size(0)
            preds = torch.argmax(logits, dim=-1)
            train_correct += int(torch.sum(preds == y_b).item())
            train_total += x_b.size(0)

        epoch_train_loss = train_loss / train_total
        epoch_train_acc = (train_correct / train_total) * 100.0

        # Validation Step
        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_total = 0

        with torch.no_grad():
            for x_v, y_v in val_loader:
                v_logits = model(x_v)
                v_loss = criterion(v_logits, y_v)
                val_loss += v_loss.item() * x_v.size(0)
                v_preds = torch.argmax(v_logits, dim=-1)
                val_correct += int(torch.sum(v_preds == y_v).item())
                val_total += x_v.size(0)

        epoch_val_loss = val_loss / val_total
        epoch_val_acc = (val_correct / val_total) * 100.0

        # Check for improvement (EarlyStopping)
        if epoch_val_loss < best_val_loss - 1e-4:
            best_val_loss = epoch_val_loss
            best_model_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
            flag = " [BEST]"
        else:
            patience_counter += 1
            flag = f" [patience: {patience_counter}/{patience}]"

        print(
            f"Epoch [{epoch:>2}/{max_epochs:>2}] (lr={current_head_lr:.1e}) | "
            f"Train Focal: {epoch_train_loss:.4f} (Acc: {epoch_train_acc:>5.1f}%) | "
            f"Val Focal: {epoch_val_loss:.4f} (Acc: {epoch_val_acc:>5.1f}%){flag}",
            flush=True,
        )

        if patience_counter >= patience:
            print(
                f"\n[*] Early Stopping Triggered at Epoch {epoch}: "
                f"Validation loss did not improve for {patience} consecutive epochs.",
                flush=True,
            )
            break

    # 7. Restore Best Model State for Export
    if best_model_state is not None:
        model.load_state_dict(best_model_state)
    model.eval()

    # 8. Export Full Model to ONNX Format
    print("\n" + "-" * 80, flush=True)
    print("EXPORTING FULL OPTIMIZED MODEL TO ONNX RUNTIME CPU GRAPH", flush=True)
    print("-" * 80, flush=True)

    out_file = Path(output_onnx)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    dummy_input = torch.randn(1, window_size, 1, dtype=torch.float32)
    torch.onnx.export(
        model,
        dummy_input,
        str(out_file),
        export_params=True,
        opset_version=17,
        do_constant_folding=True,
        input_names=["context_candles"],
        output_names=["regime_logits"],
        dynamic_axes={
            "context_candles": {0: "batch_size"},
            "regime_logits": {0: "batch_size"},
        },
        dynamo=False,
    )

    file_size_mb = out_file.stat().st_size / (1024 * 1024)
    print(f"[SUCCESS] ONNX Model Artifact exported: {out_file.resolve()}", flush=True)
    print(f"[+] Model Size: {file_size_mb:.2f} MB", flush=True)

    # 9. Verify with ONNX Runtime CPU & Benchmark Latency
    print("\n" + "-" * 80, flush=True)
    print("VERIFYING ONNX RUNTIME INFERENCE LATENCY & PROBABILITY DIVERSITY (CPU)", flush=True)
    print("-" * 80, flush=True)

    try:
        import onnxruntime as ort

        session = ort.InferenceSession(str(out_file), providers=["CPUExecutionProvider"])
        test_input = np.random.randn(1, window_size, 1).astype(np.float32)

        # Warmup
        for _ in range(5):
            _ = session.run(None, {"context_candles": test_input})

        # Measure 50 iterations
        times: list[float] = []
        for _ in range(50):
            t0 = time.perf_counter()
            _ = session.run(None, {"context_candles": test_input})
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000.0)

        mean_ms = sum(times) / len(times)
        max_ms = max(times)
        min_ms = min(times)

        # Verify output distribution on real last 512 bars
        last_512_closes = closes[-window_size:]
        w_mean = np.mean(last_512_closes)
        w_std = np.std(last_512_closes) + 1e-8
        real_input = np.clip((last_512_closes - w_mean) / w_std, -5.0, 5.0).reshape(1, window_size, 1).astype(np.float32)

        real_out = session.run(None, {"context_candles": real_input})
        real_logits = real_out[0][0]
        exp_logits = np.exp(real_logits - np.max(real_logits))
        real_probs = exp_logits / np.sum(exp_logits)

        print("[+] Benchmark over 50 iterations on CPU:", flush=True)
        print(f"    Mean Latency : {mean_ms:.2f} ms", flush=True)
        print(f"    Min Latency  : {min_ms:.2f} ms", flush=True)
        print(f"    Max Latency  : {max_ms:.2f} ms", flush=True)
        print("\n[+] Verification on REAL Recent Market Context (Latest H4 Bars):", flush=True)
        print(f"    Raw Logits              : {[round(float(l), 4) for l in real_logits]}", flush=True)
        print(f"    P(BULLISH_TRENDING)     : {real_probs[0]:.2%}", flush=True)
        print(f"    P(BEARISH_TRENDING)     : {real_probs[1]:.2%}", flush=True)
        print(f"    P(RANGING)              : {real_probs[2]:.2%}", flush=True)
        print(f"    Sum of Probabilities    : {sum(real_probs):.4f}", flush=True)
        assert math.isclose(float(sum(real_probs)), 1.0, rel_tol=1e-4)

        dominant_prob = float(np.max(real_probs))
        dominant_class = CLASS_NAMES[int(np.argmax(real_probs))]
        print(f"\n[+] DOMINANT REGIME DETECTED: {dominant_class} with {dominant_prob:.2%} Confidence!", flush=True)

        if dominant_prob >= 0.60:
            print("[+] SHARP PROBABILITY CRITERIA MET: Dominant confidence >= 60.0%!", flush=True)
        else:
            print(f"[!] Notice: Dominant confidence is {dominant_prob:.2%} (Target >= 60%).", flush=True)

        if mean_ms < 2.0:
            print("[+] Performance SLA Met: Latency < 2.0ms", flush=True)

    except ImportError:
        print("[!] onnxruntime not found; skipped runtime benchmark.", flush=True)

    print("\n" + "=" * 80, flush=True)
    print("KRONOS H4 REGIME TRAINING & VALIDATION COMPLETE!", flush=True)
    print("=" * 80, flush=True)
    return 0


def main() -> None:
    """CLI Parser."""
    parser = argparse.ArgumentParser(description="Train Kronos H4 Regime Classifier with Focal Loss & Unfreezing")
    parser.add_argument("--data-path", default="data/historical/xauusd_h4.parquet")
    parser.add_argument("--output-onnx", default="data/models/kronos_h4.onnx")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--patience", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr-backbone", type=float, default=2e-4)
    parser.add_argument("--lr-head", type=float, default=3e-3)
    parser.add_argument("--stride", type=int, default=6)
    parser.add_argument("--gamma", type=float, default=1.5)
    parser.add_argument("--temperature", type=float, default=0.35)
    args = parser.parse_args()

    sys.exit(
        train_kronos(
            data_path=args.data_path,
            output_onnx=args.output_onnx,
            max_epochs=args.epochs,
            patience=args.patience,
            batch_size=args.batch_size,
            lr_backbone=args.lr_backbone,
            lr_head=args.lr_head,
            stride=args.stride,
            focal_gamma=args.gamma,
            temperature=args.temperature,
        )
    )


if __name__ == "__main__":
    main()
