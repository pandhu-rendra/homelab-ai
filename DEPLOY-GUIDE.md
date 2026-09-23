# Panduan Deploy HomeLab AI ke VPS

Panduan ini menjelaskan cara upload & distribusi HomeLab AI lewat VPS pribadi,
mirip kayak openrouter / claude code — user cukup jalanin satu curl command.

---

## Daftar Isi

- [1. Persiapan VPS](#1-persiapan-vps)
- [2. Build Release](#2-build-release)
- [3. Upload ke VPS](#3-upload-ke-vps)
- [4. Konfigurasi Nginx + SSL](#4-konfigurasi-nginx--ssl)
- [5. Test Installasi](#5-test-instalasi)
- [6. Update Versi Baru](#6-update-versi-baru)
- [7. Troubleshooting](#7-troubleshooting)

---

## 1. Persiapan VPS

### Launch without changing the caller directory

The project launchers run HomeLab AI from the project directory while
preserving the directory of the shell that started them:

```text
Windows CMD/Clink:  call D:\project\homelab-ai\run-homelab-ai.bat
Linux/macOS:       ./run-homelab-ai.sh
```

On Linux/macOS, make the launcher executable once with `chmod +x
run-homelab-ai.sh`. The CMD aliases in `cmd_profile.bat` use `pushd/popd` for
the same behavior.

### Local AI skills

Skills are instruction bundles, separate from Python plugins. Put a skill in
the repository-local `skills/<skill-name>/` directory with one of these files:

```text
SKILL.md
skill.md
CLAUDE.md
GEMINI.md
GPT.md
AGENTS.md
```

`SKILL.md` is recommended for portability. Optional YAML frontmatter can
declare `name`, `description`, `keywords`, or `triggers`:

```markdown
---
name: Python Review
description: Review and refactor Python code
keywords: python, lint, refactor, test
---

Prefer small, tested changes and report validation evidence.
```

The same Markdown skill is injected into the prompt for Claude, Gemini, GPT,
and OpenAI-compatible providers. Use `/skill list` to inspect project and user
skills. Skills are selected by explicit name or matching metadata, so unrelated
instructions are not sent on every request.

### Portable AI plugins

Plugins support two separate layers: optional executable Python hooks and a
provider-neutral Markdown manifest. Put project plugins in
`plugins/<plugin-name>/`:

```text
plugins/
└── weather-plugin/
    ├── plugin.py       # optional HomeLab AI / Pluggy hooks
    └── PLUGIN.md       # portable instructions for Claude, Gemini, GPT, etc.
```

`PLUGIN.md` may use the same frontmatter fields as skills:
`name`, `description`, `keywords`, and `triggers`. The Markdown manifest is
injected only when its name or metadata matches the user request. The model
receives instructions, never executable Python. Use `/plugin list` to see
whether a plugin has a `portable` manifest.

### Spesifikasi minimal

| Resource | Minimal |
|----------|---------|
| CPU | 1 core |
| RAM | 1 GB |
| Storage | 10 GB |
| OS | Ubuntu 22.04 / Debian 12 |

### Install nginx

```bash
sudo apt update
sudo apt install nginx -y
sudo systemctl enable nginx
sudo systemctl start nginx
```

### Domain

Domain **altivon.my.id** harus diarahkan (pointing) ke IP VPS:

| Record | Type | Value |
|--------|------|-------|
| `@` | A | `<IP_VPS_LO>` |
| `www` | CNAME | `altivon.my.id` |

Tunggu 5-30 menit sampe DNS propagation.

### Firewall

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 22/tcp
sudo ufw enable
```

---

## 2. Build Release

Jalankan dari folder project di **komputer lo** (bukan VPS):

```bash
cd ~/.homelab-ai
./scripts/build-release.sh
```

### Output yang dihasilkan

```
releases/homelab-ai-v2.1.0.tar.gz.enc    ← tarbal terenkripsi (upload ke VPS)
dist/install.sh                            ← installer dengan key udah di-embed
```

**PENTING:** `dist/install.sh` udah otomatis berisi key dekripsi yang cocok sama
tarball-nya. Jadi 2 file ini HARUS di-upload bareng.

### Custom version

```bash
./scripts/build-release.sh v2.0.0
```

---

## 3. Upload ke VPS

Buat folder di VPS:

```bash
ssh user@altivon.my.id
sudo mkdir -p /var/www/html/releases
sudo chown -R $USER:$USER /var/www/html
exit
```

Upload file:

```bash
# Upload tarbal
scp releases/homelab-ai-v2.1.0.tar.gz.enc user@altivon.my.id:/var/www/html/releases/homelab-ai.tar.gz.enc

# Upload installer
scp dist/install.sh user@altivon.my.id:/var/www/html/install.sh
```

### Struktur folder di VPS setelah upload

```
/var/www/html/
├── install.sh                       ← https://altivon.my.id/install.sh
└── releases/
    └── homelab-ai.tar.gz.enc        ← https://altivon.my.id/releases/homelab-ai.tar.gz.enc
```

### Ganti URL kalo pake path berbeda

Kalo file-nya ada di subfolder atau domain beda, tinggal ganti env `RELEASE_URL`
waktu install:

```bash
curl -fsSL https://domainkamu.com/path/install.sh | sh -s -- --url https://domainkamu.com/path/release.tar.gz.enc
```

Atau biar lebih gampil, edit aja langsung file `dist/install.sh` sebelum upload.
Ubah bagian `RELEASE_URL` di line 12.

---

## 4. Konfigurasi Nginx + SSL

### 4.1. Nginx config

Bikin file `/etc/nginx/sites-available/homelab`:

```nginx
server {
    listen 80;
    server_name altivon.my.id www.altivon.my.id;

    root /var/www/html;

    location / {
        try_files $uri $uri/ =404;
        add_header Content-Type text/plain;
    }

    location /releases/ {
        alias /var/www/html/releases/;
        add_header Content-Disposition 'attachment; filename="homelab-ai.tar.gz.enc"';
    }
}
```

Aktifin:

```bash
sudo ln -s /etc/nginx/sites-available/homelab /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 4.2. SSL pakai Let's Encrypt

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d altivon.my.id -d www.altivon.my.id
```

Pilih opsi **2** (redirect HTTP ke HTTPS). Config nginx lo otomatis ke-update.

### 4.3. Config final (setelah SSL)

Ini contoh config final `/etc/nginx/sites-available/homelab`:

```nginx
server {
    listen 443 ssl;
    server_name altivon.my.id www.altivon.my.id;

    ssl_certificate /etc/letsencrypt/live/altivon.my.id/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/altivon.my.id/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    root /var/www/html;

    location / {
        try_files $uri $uri/ =404;
    }

    location /releases/ {
        alias /var/www/html/releases/;
        add_header Content-Disposition 'attachment';
    }
}

server {
    listen 80;
    server_name altivon.my.id www.altivon.my.id;
    return 301 https://$server_name$request_uri;
}
```

### 4.4. Test akses

Dari browser atau terminal:

```bash
curl -I https://altivon.my.id/install.sh
```

Harusnya balik `200 OK`.

---

## 5. Test Instalasi

### Coding safety controls

The local TUI supports bounded, verifiable coding requests:

```text
/code fix D:\path\to\index.html
/dry-run redesign D:\path\to\index.html and style.css
```

Successful overwrites create an adjacent `.bak` backup. Edit reports include
before/after SHA-256 prefixes and lightweight source checks for Python,
JavaScript, CSS, HTML, and local asset references. Press `Esc` to cancel an
active request. Runtime limits are configured in `.env`:

```env
HOMELAB_LLM_TIMEOUT=30
HOMELAB_MAX_ATTEMPTS=20
HOMELAB_MAX_PROVIDER_ATTEMPTS=2
HOMELAB_MAX_CONTEXT_CHARS=24000
HOMELAB_MAX_TOTAL_TOKENS=12000
```

The application keeps a hard safety cap even when a legacy `.env` contains a
zero attempt value.

### Cara install (dari komputer manapun)

```bash
curl -fsSL https://altivon.my.id/install.sh | sh
```

Atau pake branch/versi kustom:

```bash
curl -fsSL https://altivon.my.id/install.sh | sh -s -- --dir ~/homelab
```

### Yang terjadi selama instalasi

```
  HomeLab AI Installer
  ─────────────────────────────────────────
  ✓ Python 3.14.5
  ✓ openssl
  ✓ curl
  ✓ uv
  ➜ Downloading HomeLab AI...
  ✓ Downloaded (12.3 MB)
  ➜ Decrypting...
  ✓ Decrypted
  ✓ Extracted to /home/user/.homelab-ai
  ➜ Compiling bytecode...
  ✓ Source protected (compiled to .pyc)
  ➜ Creating virtual environment (uv)...
  ✓ Virtual environment created
  ➜ Installing dependencies (uv)...
  ✓ Dependencies installed
  ✓ Launcher created: /home/user/.local/bin/homelab
  ✓ Added /home/user/.local/bin to PATH (/home/user/.bashrc)

  ─────────────────────────────────────────
  HomeLab AI installed successfully!
  ─────────────────────────────────────────

  Run: homelab
  First step: Edit /home/user/.homelab-ai/.env
```

### Cek hasil

```bash
homelab --help
```

Harusnya muncul bantuan command Homelab AI.

### Kalo `homelab` command not found

Reload shell:

```bash
source ~/.bashrc
```

Atau restart terminal.

---

## 6. Update Versi Baru

### Step by step tiap rilis baru

1. Di komputer lo:

```bash
cd ~/.homelab-ai
git pull                                ← update source code
./scripts/build-release.sh v2.1.1       ← build versi baru
```

2. Upload ke VPS:

```bash
scp releases/homelab-ai-v2.1.1.tar.gz.enc user@altivon.my.id:/var/www/html/releases/homelab-ai.tar.gz.enc
scp dist/install.sh user@altivon.my.id:/var/www/html/install.sh
```

**Catatan:** nama file di VPS tetap `homelab-ai.tar.gz.enc` biar URL-nya gak
berubah. Kalo ada user lama yang udah install, mereka tinggal install ulang
pake command yang sama persis.

### Live check versi dari server

```bash
curl -s https://altivon.my.id/install.sh | head -5
```

---

## 7. Troubleshooting

### 7.1. `curl: (6) Could not resolve host`

DNS belum propagate atau domain salah pointing. Cek:

```bash
dig altivon.my.id
```

### 7.2. `curl: (7) Failed to connect`

Firewall blocking port 443, atau nginx belum jalan. Cek:

```bash
sudo ufw status
sudo systemctl status nginx
```

### 7.3. `openssl: error: bad decrypt`

Key di `install.sh` gak cocok sama tarball. Solusi:

1. Re-run `./scripts/build-release.sh` (bikin ulang tarball + key baru)
2. Upload ulang kedua file

Atau kalo user punya key lain, bisa pake flag `--key`:

```bash
curl -fsSL https://altivon.my.id/install.sh | sh -s -- --key <key_benar>
```

### 7.4. `Python >= 3.10 required`

VPS atau komputer user pake Python tua. Install Python 3.10+:

```bash
# Ubuntu/Debian
sudo apt install python3 python3-pip python3-venv -y

# macOS
brew install python@3.11
```

### 7.5. `homelab: command not found` setelah install

PATH `~/.local/bin` belum di-load. Jalankan:

```bash
source ~/.bashrc
```

Atau tambahin manual:

```bash
export PATH="$PATH:$HOME/.local/bin"
```

Kalo pake fish shell:

```bash
fish_add_path ~/.local/bin
```

---

## Referensi

| Item | URL |
|------|-----|
| Installer | `https://altivon.my.id/install.sh` |
| Release file | `https://altivon.my.id/releases/homelab-ai.tar.gz.enc` |
| GitHub source | `https://github.com/pandhu-rendra/homelab-ai` |
| Certbot (SSL) | `https://certbot.eff.org/` |
