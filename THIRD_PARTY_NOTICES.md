# Third-Party Notices

This file lists third-party components and external results used by AETERNA Quant. AGPL-3.0 does not create a `NOTICE` requirement by itself, but several dependencies use Apache-2.0 and other licenses whose notices must be preserved. Full pinned inventories are in `uv.lock`, `engine/analysis_engine/rust/Cargo.lock`, and `engine/watchdog/go.sum`.

## Python Runtime and Development

| Component | Installed version | License metadata | Notes |
| :--- | :--- | :--- | :--- |
| `fredapi` | 0.5.2 | verify upstream package metadata | FRED series access only |
| `requests` | 2.34.2 | Apache-2.0 | HTTP client |
| `pydantic` | 2.14.1 | MIT | Schema validation |
| `PyYAML` | 6.0.3 | MIT | Config parsing |
| `pandas` | 3.1.0 | BSD-3-Clause | Data frames |
| `numpy` | 2.5.4 | BSD-3-Clause / 0BSD / MIT / Zlib / CC0-1.0 | Numeric core |
| `pyarrow` | 26.0.1 | Apache-2.0 | Parquet streaming |
| `onnxruntime` | 1.31.1 | MIT | CPU inference |
| `pytest` | 9.2.0 | MIT | Development |
| `pytest-asyncio` | 1.4.1 | Apache-2.0 | Development |
| `pyright` | 1.1.414 | MIT | Development |
| `maturin` | 1.16.0 | MIT OR Apache-2.0 | Development/build |
| `ruff` | 0.17.3 | MIT | Development |

## Rust

From `engine/analysis_engine/rust/Cargo.toml`: `pyo3`, `thiserror`, `serde`, `rand`, `rand_xoshiro`, and `chrono`. Most are MIT/Apache-2.0 dual-licensed; preserve each crate's license text from the pinned Cargo registry source in release archives.

## Go

From `engine/watchdog/go.mod`/`go.sum`: `modernc.org/sqlite` and transitive modules including `golang.org/x/sys`, `google/uuid`, and `hashicorp/golang-lru/v2`. Preserve the license text from each pinned module in release archives.

## External Services and Proprietary Prerequisites — Not Redistributed

- MetaTrader 5 terminal and Python bindings (broker EULA applies).
- Exness/OANDA/FRED APIs and data feeds (terms of service apply).
- Broker tick data, historical Parquet exports, and generated databases.
- Unlicensed or third-party ONNX model weights.

## Model and Data Provenance

No broker data, live database, logs, account reports, or unlicensed model weights are included in public source releases. If a future release includes a model artifact, it must be accompanied by `MODEL_CARD.md`, upstream license, checksum, and training-data provenance.

## Third-Party Results

Research references and external evidence are attributed, not adopted as performance claims. See `docs/aeterna/VERIFIED_TRACKRECORD.md` and `DISCLAIMER.md`.
