# AETERNA Expansion Backlog

- `plan_id`: PLAN-AETERNA-EXPANSION-001
- `created_utc`: 2026-11-19
- `status`: CAPTURED
- `approval`: NOT_APPROVED_FOR_IMPLEMENTATION
- `scope`: ide jangka panjang, bukan task aktif, bukan izin publikasi, bukan izin order live
- `canonical_state`: `docs/aeterna/agent-state.md`

File ini hanya menampung ide agar tidak hilang. Tidak ada ide di sini yang boleh diimplementasikan tanpa task packet terpisah, research brief jika menyentuh klaim eksternal, dan keputusan operator.

## 1. Core Principle

AETERNA bukan sekadar quant research. Arah akhirnya adalah **proprietary algo trading dengan fondasi riset dan audit**, yang nanti bisa diperluas ke banyak instrumen.

Satu jalur inti tetap dipertahankan:

```text
ingestion -> normalization -> quality gate -> state machine -> regime
-> strategy -> risk gate -> observation journal -> audit -> publication/execution
```

Yang berubah antar-aset adalah **adapter**, bukan pipeline inti.

## 2. Plan A — Expert Advisor Khusus XAUUSD

### Idea

Menjual atau melisensikan Expert Advisor (EA) khusus XAUUSD sebagai produk perangkat lunak.

### Status

- `[IDEA]`
- `DEFERRED`
- `NEEDS_LEGAL_REVIEW`
- `NEEDS_PROPFIRM_TOS_REVIEW`
- `NEEDS_PRODUCTION_GATE`

### Constraints

1. Tidak boleh dijual sebagai “mesin profit”, “sinyal pasti”, atau klaim performa tanpa rekam jejak terverifikasi.
2. Tidak boleh menyertakan lot, equity, tiket, server, atau instruksi personal dalam materi publik.
3. Observability dan audit bukan pelindung hukum; itu hanya bukti kualitas.
4. Jika dipakai pada akun prop firm, ToS firma harus dibaca dan disimpan sebagai bukti.
5. Harus lulus dulu:
   - GATE-E2E-RUNTIME;
   - 50–100 sampel internal;
   - GATE-M4 dan GATE-M5;
   - pendapat penasihat hukum Indonesia untuk model penjualan.

### Possible Safe Form

- Lisensi software murni.
- Dokumentasi teknis dan audit trail.
- Tidak ada nasihat personal.
- Tidak ada imbalan berbasis hasil trading pengguna.

## 3. Plan B — Perluasan Multi-Asset

### Idea

Memperluas cabang AETERNA ke:

- forex pairs;
- commodities lain;
- saham AS, misalnya Nasdaq/QQQ dan instrumen sejenis;
- altcoin.

### Status

- `[IDEA]`
- `DEFERRED`
- `NEEDS_MARKET_ADAPTER_SPECS`
- `NEEDS_RESEARCH_BRIEF_PER_ASSET_CLASS`

### Core yang Tetap Sama

- state machine;
- risk gate;
- journal observasi;
- audit;
- output observasi struktural;
- zero LLM di jalur produksi.

### Adapter yang Perlu Ditambah

| Asset Class | Adapter yang dibutuhkan |
| :--- | :--- |
| XAUUSD | rollover Exness, spread emas, sesi London/NY, news impact emas |
| Forex pairs | swap/rollover, pip per pair, sesi regional, likuiditas per pair |
| Commodities | contract roll, seasonality, warehouse/supply news, tick size |
| Nasdaq/QQQ/saham | jam bursa, halts, earnings, corporate action, short borrow, margin |
| Altcoin | 24/7 session, funding rate, liquidation cascade, exchange outage, custody risk |

### Rule

Jangan mulai multi-asset sebelum XAUUSD solid. Multi-asset menambah complexity dan surface area bug.

## 4. Plan C — Software Intelligence Mandiri

### Idea

Membangun software tersendiri untuk melihat:

- berita global;
- makroekonomi;
- arah market;
- likuiditas;
- aktivitas market maker / “bandar market”;
- positioning;
- anomaly spread dan volume.

### Status

- `[IDEA]`
- `DEFERRED`
- `NEEDS_RESEARCH_BRIEF`
- `NEEDS_SOURCE_PROVENANCE`
- `ZERO_LLM_PROD_CONSTRAINT`

### Important Note

Istilah “bandar market” tidak boleh dipakai sebagai klaim naratif tanpa bukti. Harus diterjemahkan ke variabel terukur:

- order book imbalance;
- liquidity sweep yang terverifikasi;
- spread anomaly;
- volume footprint;
- funding/positioning;
- volatility regime;
- market maker quote behavior jika datanya tersedia.

Semua klaim harus punya source dan status bukti. Tanpa itu, ini hanya hipotesis.

### Product Form yang Sah

- dashboard observasi struktural;
- bias rezim;
- zona likuiditas;
- level invalidasi;
- kalender blackout;
- audit statistik;
- source provenance.

Dilarang:

- instruksi BUY/SELL imperatif;
- lot atau ekuitas publik;
- janji hasil;
- klaim performa tanpa rekam jejak;
- pengelolaan dana pihak lain tanpa struktur izin.

## 5. Funding & Commercial Model

### Current Intention

- Modal pribadi dan/atau akun prop firm tetap menjadi jalur utama.
- Monetisasi di masa depan bisa berupa:
  - lisensi EA;
  - software observability;
  - research dashboard;
  - produk audit data.

### Hard Boundary

Sinyal/EA/copy trading yang dibungkus observability dan audit **tidak otomatis aman secara hukum**. Substansi aktivitas tetap menentukan risiko:

- siapa yang pegang dana;
- siapa yang ambil keputusan;
- siapa yang menanggung rugi;
- apakah ada imbalan;
- apakah imbalan terkait hasil trading;
- apakah ada nasihat personal.

Wajib minta pendapat penasihat hukum Indonesia sebelum monetisasi pihak ketiga.

## 6. Sequencing

1. Selesaikan E2E hardening AETERNA XAUUSD.
2. Kumpulkan 50–100 sampel internal.
3. Luluskan GATE-M4 dan GATE-M5.
4. Tentukan positioning legal.
5. Baru evaluasi EA XAUUSD.
6. Baru adapter multi-asset.
7. Baru software intelligence mandiri.

## 7. Open Questions

1. Firma prop firm mana yang dipakai, dan apa ToS tertulisnya?
2. Yurisdiksi pengguna akhir: Indonesia saja atau lintas negara?
3. Apakah EA dijual sebagai software license atau layanan berlangganan?
4. Apakah ada imbalan yang terkait hasil trading pengguna?
5. Sumber berita dan makro apa yang boleh dipakai secara sah?
6. Apakah data order book/positioning tersedia untuk asset class target?
7. Siapa penasihat hukum yang akan menandatangani review?

## 8. Explicit Non-Authorization

File ini bukan task packet, bukan ADR final, bukan persetujuan produksi, dan bukan izin eksekusi. Semua ide di sini menunggu keputusan operator dan gate yang sesuai.
