# Kronos Foundation Model Architecture & Fine-Tuning SOP

**Single Source of Truth (SSoT) — Quantitative AI Architecture Document**  
**Document ID**: `DOC-KRONOS-ARCH-001`  
**Classification**: Tier B (Quantitative Model & Feature Engineering)  
**Target Instrument**: XAUUSD (Spot Gold) — Primary Timeframe: H4  
**Runtime Environment**: CPU-Only ONNX Runtime (`CPUExecutionProvider`)  
**Reference Paper**: *Kronos: A Foundation Model for the Language of Financial Markets* ([arXiv:2508.02739](https://arxiv.org/abs/2508.02739), Tsinghua University, August 2025)  
**Upstream Repository**: [https://github.com/shiyu-coder/Kronos](https://github.com/shiyu-coder/Kronos)  

---

## 1. Executive Summary & Rationale

Within the AETERNA Quant Engine, the Kronos model serves strictly as an **H4 Macro Regime Filter** in Stage 3 of the end-to-end operational pipeline. It operates under a strict **Zero-LLM Live Execution Boundary**: while LLMs and sub-agents assist in offline development, runtime inference is 100% deterministic, native, and out-of-process from any generative chat model.

The foundation model is not tasked with predicting point price forecasts; rather, it estimates the probability distribution across three mutually exclusive market regimes:
1. `BULLISH_TRENDING`: Favors long setups; blocks short volatility breakouts.
2. `BEARISH_TRENDING`: Favors short setups; blocks long volatility breakouts.
3. `RANGING`: Neutral directional bias; enables adaptive mean-reversion strategies and tightens breakout filters.

---

## 2. Macro Structural Break: Post-COVID Data Mandate

### 2.1 The 2020 Structural Regime Shift
Historical financial econometrics demonstrate that global spot gold underwent a permanent **Structural Break** beginning in Q1 2020:
- **Macro Drivers**: Massive global quantitative easing, unprecedented expansion of central bank balance sheets, negative US real yields, and de-dollarization foreign reserve reallocation by emerging market central banks.
- **Liquidity & Spread Regimes**: Modern Electronic Communication Network (ECN) and broker order flow dynamics (including Exness tick frequency distributions) diverged drastically from the 2010–2019 era.

### 2.2 The Mandate
> **MANDATE**: Training and fine-tuning Kronos on pre-2020 gold data introduces severe regime contamination and negative transfer.  
> **Rule**: All historical data extraction, continued pre-training, and supervised fine-tuning MUST strictly enforce `start_date >= 2020-01-01`.

---

## 3. Core Kronos Architecture (arXiv:2508.02739 Specification)

### 3.1 Input Dimension & Preprocessing ($D=6$ OHLCVA)
The model consumes a multivariate matrix $\mathbf{x} \in \mathbb{R}^{T \times D}$ where context length $T = 512$ and feature dimension $D = 6$:
- $x_{t, 0}$: Open price
- $x_{t, 1}$: High price
- $x_{t, 2}$: Low price
- $x_{t, 3}$: Close price
- $x_{t, 4}$: Tick Volume (traded transactions per bar)
- $x_{t, 5}$: Amount / Turnover proxy ($\approx \text{Close} \times \text{Volume}$)

#### Zero-Leakage Normalization Protocol
1. **Window-Isolated Z-Score**:
   $$\tilde{x}_{t, d} = \frac{x_{t, d} - \mu_d}{\sigma_d + \epsilon}, \quad \mu_d = \frac{1}{T}\sum_{i=1}^T x_{i, d}, \quad \sigma_d = \sqrt{\frac{1}{T}\sum_{i=1}^T (x_{i, d} - \mu_d)^2}$$
   where $T=512$ and $\epsilon = 10^{-8}$. Global dataset scaling is strictly banned to prevent future lookahead leakage into historical bars.
2. **Outlier Clipping**:
   Normalized values are strictly clipped to the symmetric range $[-5.0, +5.0]$:
   $$\bar{x}_{t, d} = \max(-5.0, \min(5.0, \tilde{x}_{t, d}))$$

### 3.2 K-Line Tokenizer: Binary Spherical Quantization (BSQ)
Instead of continuous regression with high noise susceptibility, Kronos quantizes each multivariate candlestick into discrete tokens via Binary Spherical Quantization:
- **Latent Bit Width**: $k = 20$ bits.
- **Subtoken Factorization**: To prevent an intractable codebook vocabulary of $2^{20} \approx 1,048,576$ entries, the code is factorized into $n = 2$ subspaces:
  - **Coarse Subtoken ($b_t^c$)**: $k_c = 10$ bits $\implies$ Vocabulary size $= 2^{10} = 1024$.
  - **Fine Subtoken ($b_t^f$)**: $k_f = 10$ bits $\implies$ Vocabulary size $= 2^{10} = 1024$.
- **Tokenizer Autoencoder Architecture**:
  - Encoder: 3 Transformer layers ($d_{\text{model}} = 256$, $d_{\text{ff}} = 512$, 4 attention heads).
  - Decoder: 3 Transformer layers ($d_{\text{model}} = 256$, $d_{\text{ff}} = 512$, 4 attention heads).
  - Commitment loss weight $\beta = 0.05$, entropy scale $\zeta = 0.05$.

### 3.3 Backbone Transformer: `Kronos-small` Specification
AETERNA selects the `Kronos-small` variant as the optimal balance between high-capacity market representation and lightweight local CPU inference:

| Architectural Hyperparameter | Kronos-small Specification |
| :--- | :--- |
| **Total Parameters** | **24.7 Million** |
| **Transformer Layers** | 8 Decoder-Only causal layers |
| **Hidden Dimension ($d_{\text{model}}$)** | 512 |
| **Feed-Forward Dimension ($d_{\text{ff}}$)** | 1024 |
| **Attention Heads** | 8 |
| **Positional Encoding** | Rotary Position Embeddings (RoPE) |
| **Context Window ($T$)** | **Exactly 512 bars** (~3.5–4 months H4) |
| **Temporal Embeddings** | 5 dense embeddings: minute, hour, day-of-week, day-of-month, month |
| **Pre-training Objective** | Hierarchical Autoregressive Negative Log-Likelihood (Eq. 8) |

---

## 4. 3-Stage Transfer Learning Protocol for AETERNA

```
┌──────────────────────────────────────────────────────────────┐
│  Stage 1: Domain Adaptation (Continued Pre-training)        │
│  • Input: Post-COVID H4 XAUUSDm dataset (2020-01-01 -> Present)│
│  • Goal: Adapt token distributions to Exness gold volatility │
│  • Method: Self-supervised next-token NLL on coarse & fine  │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  Stage 2: Supervised Regime Classification Head             │
│  • Backbone: Frozen Kronos-small (24.7M parameters locked)   │
│  • Pooling: Multi-Head Attention Pooling across 512 tokens   │
│  • Head: MLP (512 -> 128 -> 3) with Softmax                  │
│  • Classes: BULLISH_TRENDING, BEARISH_TRENDING, RANGING      │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  Stage 3: Quantization & ONNX Export (Live Production)      │
│  • Target: CPUExecutionProvider (Zero-LLM Production Path)   │
│  • Precision: FP16 / INT8 Dynamic Quantization              │
│  • Footprint: File size <30 MB, RAM <50 MB, Latency <2.0 ms  │
└──────────────────────────────────────────────────────────────┘
```

### 4.1 Stage 1: Domain Adaptation (Continued Pre-training)
- **Objective**: Adapt the global pre-trained weights (which were trained primarily on equities and crypto) to the specific microstructural distribution of XAUUSD spot gold.
- **Learning Rate**: $1 \times 10^{-4}$ with linear warmup and cosine decay.
- **Regularization**: Dropout $0.10$, Weight Decay $0.01$.
- **Training Epochs**: 10–15 epochs on chunked Parquet dataset.

### 4.2 Stage 2: Supervised Regime Classification Head
- **Ground Truth Generation (Deterministic Labeling)**:
  - High-confidence Bullish Trend: ADX(14) $\ge 25.0$, EMA(20) $>$ EMA(50), Forward 20-bar return $> +1.5 \times \text{ATR}(14)$.
  - High-confidence Bearish Trend: ADX(14) $\ge 25.0$, EMA(20) $<$ EMA(50), Forward 20-bar return $< -1.5 \times \text{ATR}(14)$.
  - Ranging Regime: ADX(14) $< 20.0$, price oscillating within 2.0 standard deviations of 20-period SMA.
- **Training Strategy**: The 24.7M backbone parameters are completely frozen (`requires_grad = False`). Only the classification head (Multi-Head Attention Pooling + linear projection) is optimized.

### 4.3 Stage 3: Post-Training Quantization & Export
- The finalized PyTorch model is converted to ONNX via `torch.onnx.export`.
- Graph optimization and constant folding are applied.
- The output artifact is saved to: `data/models/kronos_h4.onnx`.
- `engine.models.kronos.inference.KronosH4RegimeEngine` detects this file and executes native CPU inference in under 2.0 milliseconds.

---

## 5. Quarterly Retraining Schedule (Alpha Decay Prevention SOP)

Financial market regimes and central bank policy cycles evolve continuously. Fixed machine learning parameters suffer from **Alpha Decay** if left uncalibrated over extended horizons.

### 5.1 The 90-Day Calibration Cycle
- **Retraining Frequency**: Exactly once every **3 months (Quarterly / ~90 calendar days)**.
- **Mathematical Rationale**: The context window of 512 H4 bars represents approximately 3.5 to 4 months of trading. A quarterly recalibration ensures that the training window advances synchronously with the lookback window, preventing historical parameter staleness.

### 5.2 Quarterly SOP Execution Checklist
1. **[T-7 Days] Trigger Extraction**:
   - Run `scripts/extract_historical_data.py --start-date 2020-01-01 --output data/historical/xauusd_h4.parquet`.
   - Verify that data contains zero gaps or flat zero rates.
2. **[T-5 Days] Run Stage 1 & Stage 2 Training**:
   - Execute `uv run python scripts/train_kronos_regime.py`.
   - Validate validation loss and F1-score across all three regimes (Target F1 $\ge 0.75$).
3. **[T-3 Days] Walk-Forward & Characterization Audit**:
   - Run backtest runner with new candidate model: `uv run pytest tests/ -v`.
   - Verify that deterministic golden test invariants remain 100% compliant.
4. **[T-1 Day] Model Promotion & Artifact Swap**:
   - Back up existing model: `data/models/kronos_h4.onnx.bak`.
   - Deploy new candidate: `data/models/kronos_h4.onnx`.
   - Update `model_registry` table in `trading.db` via SQL transaction.
5. **[T+0 Day] Live Verification**:
   - Execute `.\aeterna.ps1 -check` to confirm live inference handshake passes with zero latency warnings.

---

## 6. Runtime Safety & Fallback Guarantees

In strict adherence to the universal system invariants:
1. **Fallback Heuristic**: If `data/models/kronos_h4.onnx` is missing or unreadable, `KronosH4RegimeEngine` automatically engages its deterministic momentum-slope heuristic (`_evaluate_benchmark_momentum`). The live trading loop **NEVER CRASHES**.
2. **Fail-Fast Temporal Gate**: Any context input sequence violating $\max(X) < y$ raises a strict `ValueError` and writes to `blocked_signals`.
3. **Single Responsibility**: The model only classifies regimes. It has zero authority to submit broker orders, bypass the Go Risk Watchdog, or modify position sizing.
