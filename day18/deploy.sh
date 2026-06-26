#!/usr/bin/env bash
set -euo pipefail

# ── MCP Weather Scheduler — deploy script for Ubuntu ────────────────────
# Run as root (or with sudo):  sudo ./deploy.sh
# Idempotent — safe to re-run.
# ─────────────────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }

# ── 1. Prerequisites ────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root (use sudo)."
    exit 1
fi

if ! grep -qi ubuntu /etc/os-release 2>/dev/null; then
    err "This script is designed for Ubuntu."
    exit 1
fi

log "Updating package list..."
apt-get update -qq

log "Installing system dependencies..."
apt-get install -y -qq python3 python3-venv python3-pip curl nginx coreutils

# ── 2. Configuration ────────────────────────────────────────────────
APP_DIR="/opt/weather_scheduler"
APP_USER="weathersched"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_IP="${SERVER_IP:-178.253.39.45}"

if ! id -u "$APP_USER" &>/dev/null; then
    log "Creating system user '$APP_USER'..."
    useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
fi

log "Creating application directory..."
mkdir -p "$APP_DIR"

log "Copying source files..."
cp "$SCRIPT_DIR"/server.py         "$APP_DIR/"
cp "$SCRIPT_DIR"/handlers.py       "$APP_DIR/"
cp "$SCRIPT_DIR"/scheduler.py      "$APP_DIR/"
cp "$SCRIPT_DIR"/storage.py        "$APP_DIR/"
cp "$SCRIPT_DIR"/weather_client.py "$APP_DIR/"
cp "$SCRIPT_DIR"/requirements.txt  "$APP_DIR/"

# Создаём директории для кэша и экспортов
mkdir -p "$APP_DIR/cache/results" "$APP_DIR/exports"

# ── 3. Environment (.env) ───────────────────────────────────────────
if [[ ! -f "$APP_DIR/.env" ]]; then
    log "Creating .env file..."

    MCP_WEATHER_HOST="${MCP_WEATHER_HOST:-localhost}"
    MCP_WEATHER_PORT="${MCP_WEATHER_PORT:-9001}"
    MCP_AUTH_KEY="${MCP_AUTH_KEY:-}"
    MCP_SCHEDULER_PORT="${MCP_SCHEDULER_PORT:-9002}"
    DATA_RETENTION_HOURS="${DATA_RETENTION_HOURS:-24}"

    cat > "$APP_DIR/.env" <<ENVEOF
MCP_WEATHER_HOST=${MCP_WEATHER_HOST}
MCP_WEATHER_PORT=${MCP_WEATHER_PORT}
MCP_AUTH_KEY=${MCP_AUTH_KEY}
MCP_SCHEDULER_PORT=${MCP_SCHEDULER_PORT}
DATA_RETENTION_HOURS=${DATA_RETENTION_HOURS}
WEATHER_CLIENT_TIMEOUT=${WEATHER_CLIENT_TIMEOUT:-30}
ENVEOF
    chmod 600 "$APP_DIR/.env"
else
    log ".env already exists, skipping..."
    set -a; source "$APP_DIR/.env"; set +a
fi

# ── 4. Python venv ──────────────────────────────────────────────────
if [[ ! -d "$APP_DIR/venv" ]]; then
    log "Creating Python virtual environment..."
    python3 -m venv "$APP_DIR/venv"
fi

log "Installing Python dependencies..."
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# ── 5. Filesystem permissions ───────────────────────────────────────
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

# ── 6. systemd service ──────────────────────────────────────────────
SERVICE_FILE="/etc/systemd/system/weather-scheduler.service"
log "Writing systemd service: $SERVICE_FILE"

cat > "$SERVICE_FILE" <<SYSTEMD
[Unit]
Description=MCP Weather Scheduler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/venv/bin/uvicorn server:app --host 127.0.0.1 --port ${MCP_SCHEDULER_PORT:-9002}
Restart=always
RestartSec=5

# Hardening
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=${APP_DIR}
ReadOnlyPaths=/usr/bin /usr/lib /usr/share
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictRealtime=yes
RestrictNamespaces=yes
MemoryDenyWriteExecute=no
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM

[Install]
WantedBy=multi-user.target
SYSTEMD

systemctl daemon-reload
systemctl enable weather-scheduler

# ── 7. Nginx ─────────────────────────────────────────────────────────
if [[ -z "${DOMAIN:-}" ]]; then
    read -rp "Domain name (e.g. weather.example.com; leave empty to skip HTTPS): " DOMAIN
fi

if [[ -n "$DOMAIN" ]]; then
    log "Configuring nginx reverse proxy for $DOMAIN..."

    NGINX_CONF="/etc/nginx/sites-available/${DOMAIN}-scheduler.conf"

    cat > "$NGINX_CONF" <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://127.0.0.1:9002;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
NGINX

    ln -sf "$NGINX_CONF" "/etc/nginx/sites-enabled/${DOMAIN}-scheduler.conf"
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl reload nginx

else
    warn "No domain provided. Skipping HTTPS setup."
    NGINX_CONF="/etc/nginx/sites-available/weather-scheduler.conf"
    cat > "$NGINX_CONF" <<NGINX
server {
    listen 80;
    listen [::]:80;

    location / {
        proxy_pass http://127.0.0.1:9002;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
NGINX
    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/weather-scheduler.conf
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl reload nginx
fi

# ── 8. Start service ────────────────────────────────────────────────
log "Starting MCP Weather Scheduler..."
systemctl restart weather-scheduler

sleep 2

# ── 9. Health check ─────────────────────────────────────────────────
log "Running health check..."
MAX_TRIES=10; TRY=0
while [[ $TRY -lt $MAX_TRIES ]]; do
    if curl -sf http://127.0.0.1:9002/health >/dev/null 2>&1; then
        log "Server is healthy."
        break
    fi
    TRY=$((TRY + 1))
    sleep 1
done

if [[ $TRY -ge $MAX_TRIES ]]; then
    err "Server did not become healthy after ${MAX_TRIES}s."
    journalctl -u weather-scheduler --no-pager -n 20
    exit 1
fi

# ── 10. Summary ─────────────────────────────────────────────────────
echo ""
echo "  ┌─────────────────────────────────────────────────────────┐"
echo "  │      MCP Weather Scheduler — Deployed Successfully      │"
echo "  ├─────────────────────────────────────────────────────────┤"
echo "  │  Service:    systemctl status weather-scheduler         │"
echo "  │  Logs:       journalctl -u weather-scheduler -f         │"
echo "  │  Health:     http://127.0.0.1:9002/health               │"
if [[ -n "${DOMAIN:-}" ]]; then
echo "  │  URL:        https://${DOMAIN}/                         │"
else
echo "  │  URL:        http://${SERVER_IP}:9002/                  │"
fi
echo "  └─────────────────────────────────────────────────────────┘"
echo ""
