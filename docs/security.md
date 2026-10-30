# Security Architecture & Operational Protocols (security.md)

Dokumen ini merupakan spesifikasi keamanan (*security posture*), manajemen kredensial, pengendalian akses, dan rencana tanggap darurat insiden (*incident response*) untuk sistem AI Trading XAUUSD. Dokumen ini dirancang dari nol untuk menjamin integritas aset finansial pada lingkungan desktop maupun cloud VPS.

---

## 1. Secrets & Credential Management

Sistem trading mengelola kredensial bernilai tinggi yang memberikan akses langsung ke eksekusi dana riil.

### 1.1 Inventaris Kredensial Sensitif
| Kredensial | Dampak Kebocoran | Tingkat Risiko |
| :--- | :--- | :---: |
| **Exness MT5 Master Password** | Eksekusi order unauthorized, penutupan paksa, kerugian finansial langsung | **CRITICAL** |
| **Exness MT5 Investor Password** | Pembacaan histori posisi, potensi kebocoran data strategi (read-only) | LOW |
| **Telegram Bot Token** | Pembajakan channel alert, manipulasi tombol kontrol darurat | **HIGH** |
| **OANDA v20 API Token** | Penyalahgunaan kuota API, manipulasi data scanning sentimen | MEDIUM |
| **Myfxbook Credentials** | Kerusakan reputasi publik, manipulasi publikasi rekam jejak | MEDIUM |

### 1.2 Kebijakan Penyimpanan & Isolasi (Zero-Plaintext Commit)
1. **Pola `.env` Git-Ignored**:
   - File `.env` yang memuat kredensial riil dilarang keras di-commit ke repositori Git.
   - Git repository hanya memuat file `.env.example` dengan nilai mock/dummy.
   - File `.gitignore` wajib memuat:
     ```gitignore
     .env
     .env.*
     !.env.example
     *.key
     *.pem
     *.db
     logs/
     ```
2. **Isolasi Multi-Agent Worktree**:
   - Direktori sub-agent Orca (`.worktrees/`) **tidak boleh mewarisi file `.env` produksi**.
   - Setiap agent pengembang hanya diberikan mock credentials dan diarahkan ke broker mock atau database SQLite pengujian terpisah.
3. **Runtime Credential Protection di Windows Desktop**:
   - Kredensial dibaca saat proses booting aplikasi ke memori kerja dan tidak pernah ditulis kembali ke disk dalam bentuk teks polos.
   - Di lingkungan Windows, integrasi opsi menggunakan **Windows Credential Manager (DPAPI)** untuk menyimpan kata sandi akun MT5 tanpa plain-text file.

---

## 2. Access Control & Keamanan Telegram Bot

Telegram bot berfungsi sebagai *control panel* dan jalur distribusi alert. Bot harus diproteksi dari pengambilalihan kendali (*bot hijacking*).

### 2.1 Autentikasi Ketat Berbasis Integer User ID
1. **Whitelist ID Keras**:
   - Backend bot **hanya memproses update** yang berasal dari `user_id` integer resmi milik Solo Operator (contoh: `TELEGRAM_ADMIN_ID=123456789`).
   - Dilarang mengandalkan username display (yang dapat diubah sewaktu-waktu) atau hanya mengandalkan privasi chat grup.
   - Setiap request dari `user_id` yang tidak terdaftar langsung di-drop tanpa respons (silent drop) dan dicatat sebagai *unauthorized access attempt*.

### 2.2 Proteksi Replay & Ephemeral Callback
- Tombol inline (*inline keyboard*) menghasilkan `callback_data` yang memuat UUID transaksi sekali pakai (*nonce*).
- Setiap token aksi inline memiliki batas kedaluwarsa (*Time-To-Live*) maksimal **60 detik**. Setelah 60 detik, token di memori invalid dan klik tombol diabaikan.

### 2.3 Konfirmasi Dua Langkah (Two-Step Confirmation)
Aksi berisiko destruktif atau pengubahan state sistem tidak boleh dieksekusi dengan satu kali klik:
1. **Emergency Stop (Killswitch)**
2. **Force Close All Open Positions**
3. **Manual State Override (`NORMAL` → `PAUSED`)**

*Prosedur Alur*:
```
[User Klik: "EMERGENCY STOP"] 
       │
       ▼
[Bot Kirim Pesan Peringatan Bahaya + Tombol Baru: "KONFIRMASI EKSEKUSI (Batas 15 Detik)"]
       │
       ├─► [User Klik Tombol Konfirmasi] ──► Eksekusi Killswitch + Catat Audit Log
       └─► [Timeout > 15 detik / Batal] ──► Batalkan Perintah Otomatis
```

### 2.4 Rate Limiting Perintah
- Batas maksimal 1 request per detik per user untuk mencegah banjir pesan (*flooding*) yang dapat mengacaukan polling state machine.

---

## 3. Logging Hygiene & Privasi Data

File log teknis rawan membocorkan kredensial atau detail finansial jika tidak difilter dengan disiplin.

### 3.1 Masking & Sanitasi Otomatis
1. **Log Sanitization Filter**:
   - Seluruh pipeline logging (Python `logging` formatter & Go log handler) wajib dilewatkan melalui regex filter untuk memotong (*redact*) pola sensitif:
     ```python
     # Contoh regex sanitasi otomatis sebelum penulisan log
     patterns = [
         (r'(password=)[^\s&]+', r'\1[REDACTED]'),
         (r'(token=)[^\s&]+', r'\1[REDACTED]'),
         (r'(\b\d{6,10}\b)', r'[ACCOUNT_ID_MASKED]') # Masking nomor akun MT5
     ]
     ```
2. **Zero Plaintext Traceback**:
   - Saat terjadi exception/error pada koneksi MetaTrader 5, pesan error yang memuat connection string dilarang ditulis mentah ke log publik.

### 3.2 Pemisahan Stream Log (Log Stream Separation)
- **Stream 1 — Audit Log Bisnis**: Tabel database SQLite (`trades`, `blocked_signals`). Menyimpan data transaksi, spread, pnl, dan keputusan filter. Memiliki integritas tinggi dan wajib dibackup.
- **Stream 2 — Technical Debug Log**: File lokal (`logs/engine_debug.log`). Menyimpan jejak eksekusi, polling heartbeat, dan konektivitas jaringan.
- **Log Rotation**: Ukuran maksimal file log teknis adalah 10 MB dengan rotasi maksimal 5 file arsip (menggunakan `RotatingFileHandler`).

### 3.3 Proteksi Izin File (Windows ACL)
- Direktori `logs/` dan file database `trading.db` dikonfigurasi dengan izin akses Windows ACL (`icacls`) yang hanya mengizinkan akun pengguna Windows aktif (*Current User Only*):
  ```powershell
  icacls "trading.db" /inheritance:r /grant:r "$($env:USERNAME):(F)"
  ```

---

## 4. Rencana Tanggap Darurat Kebocoran Kredensial (Incident Response Plan)

Jika terdeteksi kebocoran kredensial (misalnya: token tidak sengaja ter-push ke GitHub publik, komputer terinfeksi malware, atau terdeteksi anomali order di broker):

```
T+0 Menit: Deteksi Kebocoran
  │
  ├─► Fase 1: Containment (< 2 Menit) ──► Isolasi & Pemutusan Jalur
  │
  ├─► Fase 2: Revocation & Reset ───────► Cabut Kredensial Lama & Terbitkan Baru
  │
  ├─► Fase 3: Forensic & Audit ─────────► Verifikasi Integritas Saldo & Posisi
  │
  └─► Fase 4: Recovery & Post-Mortem ───► Pembersihan Repositori & Re-keying
```

### Fase 1: Containment Segera (< 2 Menit)
1. **Amankan Posisi Broker**:
   - Buka aplikasi **Exness Trade** di smartphone (jalur resmi darurat).
   - Periksa posisi terbuka; lakukan penutupan darurat (*Close All*) jika terdapat anomali transaksi liar.
2. **Matikan Engine Lokal**:
   - Hentikan proses Python dan Go watchdog melalui PowerShell:
     ```powershell
     Stop-Process -Name "python", "watchdog" -Force
     ```
3. **Cabut Akses Telegram Bot**:
   - Buka chat `@BotFather` di Telegram, kirim `/revoke` untuk mematikan bot token seketika.

### Fase 2: Revocation & Password Reset
1. **Ubah Kata Sandi MT5 Exness**:
   - Masuk ke Personal Area Exness melalui browser aman/ponsel.
   - Ubah *Trading Password* (Master Password) akun MT5 seketika. Ini otomatis memutuskan seluruh sesi terminal yang sedang terhubung.
2. **Regenerate API Keys**:
   - Terbitkan ulang OANDA v20 API Token di portal developer OANDA.
   - Terbitkan token Telegram Bot baru via `@BotFather`.
   - Ganti kata sandi master Myfxbook.

### Fase 3: Forensic & Audit
1. Unduh histori transaksi akun MT5 lengkap untuk memeriksa apakah ada transaksi asing yang dieksekusi oleh pihak ketiga.
2. Periksa commit history Git menggunakan perintah pencarian:
   ```powershell
   git log -S "PolaKredensialBocor" --source --all
   ```

### Fase 4: Recovery & Hardening
1. Jika kredensial terlanjur ter-push ke remote Git:
   - Gunakan `git-filter-repo` atau BFG Repo-Cleaner untuk menghapus file dari seluruh histori git branch.
   - Lakukan force-push bersih ke remote repository.
2. Perbarui file `.env` lokal dengan kredensial baru.
3. Jalankan unit test verifikasi gate sebelum menghidupkan kembali service.

---

## 5. Pertimbangan Keamanan Jaringan & Deployment VPS

Meskipun saat ini sistem beroperasi di laptop lokal, arsitektur disiapkan agar kebal (*hardened*) saat migrasi ke Cloud VPS Windows.

### 5.1 Arsitektur Outbound-Only (Zero Open Inbound Port)
Sistem dirancang sepenuhnya berbasis **koneksi keluar (outbound connection)**:
- MT5 berkomunikasi via outbound TCP port 443/1950 ke server cluster Exness.
- OANDA v20 berkomunikasi via outbound HTTPS (port 443).
- Telegram bot menggunakan metode **Long Polling** (outbound HTTPS ke `api.telegram.org`), bukan Webhook publik.
- **Konsekuensi Keamanan Positif**: Komputer host/VPS **TIDAK MEMERLUKAN port inbound publik yang terbuka**. Seluruh port masuk (*inbound*) pada Windows Firewall wajib berstatus **BLOCK**.

### 5.2 Hardening Komputer Laptop Lokal
1. **Nonaktifkan Remote Desktop**: Pastikan fitur RDP (*Remote Desktop Protocol*) Windows 11 berstatus non-aktif.
2. **Firewall Default**: Windows Defender Firewall wajib aktif pada profil Private dan Public dengan aturan: *Inbound connections that do not match a rule are blocked*.
3. **Pemisahan Akun**: Dilarang menjalankan bot di bawah akun Windows Administrator utama jika memungkinkan; gunakan standar user privileges.

### 5.3 Hardening Cloud VPS Windows (Persiapan Masa Depan)
Saat sistem dipindahkan ke Windows Server VPS di masa mendatang:
1. **RDP Hardening**:
   - Ubah port standar RDP `3389` ke custom high-port acak (misal `49152–65535`).
   - Wajibkan *Network Level Authentication (NLA)*.
   - Batasi akses IP RDP: Pasang firewall rule yang **hanya mengizinkan koneksi RDP dari IP statis rumah atau IP VPN privat**.
2. **Mesh VPN Tunneling**:
   - Disarankan mengakses VPS via jaringan mesh privat seperti **Tailscale** atau **WireGuard**, dan memblokir port RDP publik secara total dari internet bebas.
3. **Jadwal Maintenance OS Terkontrol**:
   - Windows Server Update otomatis dimatikan selama jam trading aktif (12:00 – 24:00 WIB).
   - Maintenance OS dan reboot terjadwal hanya dialokasikan pada hari Sabtu/Minggu saat pasar emas tutup.
