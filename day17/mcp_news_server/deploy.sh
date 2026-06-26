#!/usr/bin/env bash
set -euo pipefail

# ── MCP News Server — deploy script for Ubuntu ──────────────────────
# Run as root (or with sudo):  sudo ./deploy.sh
# Idempotent — safe to re-run. Re-running regenerates systemd/nginx config
# but preserves .env and venv.
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
apt-get install -y -qq python3 python3-venv python3-pip curl nginx \
    certbot python3-certbot-nginx coreutils

# ── 2. Configuration ────────────────────────────────────────────────
APP_DIR="/opt/mcp_news_server"
APP_USER="mcpnews"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! id -u "$APP_USER" &>/dev/null; then
    log "Creating system user '$APP_USER'..."
    useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
fi

log "Creating application directory..."
mkdir -p "$APP_DIR"

log "Copying source files..."
cp "$SCRIPT_DIR"/server.py     "$APP_DIR/"
cp "$SCRIPT_DIR"/handlers.py   "$APP_DIR/"
cp "$SCRIPT_DIR"/news_api.py   "$APP_DIR/"
cp "$SCRIPT_DIR"/cache.py      "$APP_DIR/"
cp "$SCRIPT_DIR"/requirements.txt "$APP_DIR/"

# ── 3. Environment (.env) ───────────────────────────────────────────
if [[ ! -f "$APP_DIR/.env" ]]; then
    log "Creating .env file..."

    if [[ -z "${NEWS_API_KEY:-}" ]]; then
        read -rsp "Enter NEWS_API_KEY (from https://newsapi.org): " NEWS_API_KEY
        echo ""
    fi
    if [[ -z "$NEWS_API_KEY" ]]; then
        err "NEWS_API_KEY is required."
        exit 1
    fi

    MCP_AUTH_KEY="${MCP_AUTH_KEY:-$(openssl rand -hex 24)}"

    cat > "$APP_DIR/.env" <<ENVEOF
NEWS_API_KEY=${NEWS_API_KEY}
MCP_AUTH_KEY=${MCP_AUTH_KEY}
ENVEOF
    chmod 600 "$APP_DIR/.env"
else
    log ".env already exists, skipping..."
    # Re-source MCP_AUTH_KEY for display
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
SERVICE_FILE="/etc/systemd/system/mcp-news-server.service"
log "Writing systemd service: $SERVICE_FILE"

cat > "$SERVICE_FILE" <<SYSTEMD
[Unit]
Description=MCP News Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/venv/bin/uvicorn server:app --host 127.0.0.1 --port 9000
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
systemctl enable mcp-news-server

# ── 7. Domain setup ─────────────────────────────────────────────────
# Rate-limit zone must be in http context, not server
cat > /etc/nginx/conf.d/mcp-rate-limit.conf <<'RLIMIT'
limit_req_zone $binary_remote_addr zone=mcp:10m rate=30r/m;
RLIMIT

if [[ -z "${DOMAIN:-}" ]]; then
    read -rp "Domain name (e.g. news.example.com; leave empty to skip HTTPS): " DOMAIN
fi

if [[ -n "$DOMAIN" ]]; then
    log "Configuring nginx reverse proxy for $DOMAIN..."

    NGINX_CONF="/etc/nginx/sites-available/${DOMAIN}.conf"

    cat > "$NGINX_CONF" <<NGINX
# HTTP → HTTPS redirect
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

# HTTPS reverse proxy
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Rate limit
    limit_req_status 429;

    location / {
        limit_req zone=mcp burst=10 nodelay;
        proxy_pass http://127.0.0.1:9000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-API-Key \$http_x_api_key;
        proxy_read_timeout 60s;
    }
}
NGINX

    ln -sf "$NGINX_CONF" "/etc/nginx/sites-enabled/${DOMAIN}.conf"

    # Remove default if present
    rm -f /etc/nginx/sites-enabled/default

    nginx -t && systemctl reload nginx

    # Certbot
    if [[ ! -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
        log "Obtaining Let's Encrypt certificate for $DOMAIN..."
        certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
            --email "admin@${DOMAIN}" --redirect
    else
        log "Certificate already exists for $DOMAIN, skipping certbot."
    fi

    log "Testing certificate auto-renewal..."
    certbot renew --dry-run --quiet

else
    # No domain — direct HTTP
    warn "No domain provided. Skipping HTTPS setup."
    warn "The server will be accessible over HTTP only (port 80 via nginx)."
    warn "Ensure MCP_AUTH_KEY is shared with clients."

    # Simple nginx on port 80 → 9000
    NGINX_CONF="/etc/nginx/sites-available/mcp-news.conf"
    cat > "$NGINX_CONF" <<NGINX
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    limit_req_status 429;

    location / {
        limit_req zone=mcp burst=10 nodelay;
        proxy_pass http://127.0.0.1:9000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-API-Key \$http_x_api_key;
        proxy_read_timeout 60s;
    }
}
NGINX
    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/mcp-news.conf
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl reload nginx
fi

# ── 8. Start service ────────────────────────────────────────────────
log "Starting MCP News Server..."
systemctl restart mcp-news-server

sleep 2

# ── 9. Health check ─────────────────────────────────────────────────
log "Running health check..."
MAX_TRIES=10; TRY=0
while [[ $TRY -lt $MAX_TRIES ]]; do
    if curl -sf http://127.0.0.1:9000/health >/dev/null 2>&1; then
        log "Server is healthy."
        break
    fi
    TRY=$((TRY + 1))
    sleep 1
done

if [[ $TRY -ge $MAX_TRIES ]]; then
    err "Server did not become healthy after ${MAX_TRIES}s."
    journalctl -u mcp-news-server --no-pager -n 20
    exit 1
fi

# ── 10. Summary ─────────────────────────────────────────────────────
echo ""
echo "  ┌─────────────────────────────────────────────────────────┐"
echo "  │          MCP News Server — Deployed Successfully        │"
echo "  ├─────────────────────────────────────────────────────────┤"
echo "  │  Service:    systemctl status mcp-news-server           │"
echo "  │  Logs:       journalctl -u mcp-news-server -f           │"
echo "  │  Health:     http://127.0.0.1:9000/health               │"
echo "  ├─────────────────────────────────────────────────────────┤"
if [[ -n "${MCP_AUTH_KEY:-}" ]]; then
echo "  │  API Key:    ${MCP_AUTH_KEY}                            │"
fi
if [[ -n "${DOMAIN:-}" ]]; then
echo "  │  URL:        https://${DOMAIN}/                         │"
else
echo "  │  URL:        http://85.139.69.186:9000/                 │"
fi
echo "  ├─────────────────────────────────────────────────────────┤"
echo "  │  Client config (mcp_config.json):                       │"
if [[ -n "${DOMAIN:-}" ]]; then
echo "  │  {"server_url": "https://${DOMAIN}/",                   │"
echo "  │   "transport": "streamable_http",                       │"
echo "  │   "env": {"HEADERS": {                                 │"
echo "  │     "X-API-Key": "${MCP_AUTH_KEY:-}"                    │"
echo "  │   }}}                                                  │"
else
echo "  │  {"server_url": "http://85.139.69.186:9000/",          │"
echo "  │   "transport": "streamable_http"}                      │"
echo "  │   (auth via X-API-Key header separately)                │"
fi
echo "  └─────────────────────────────────────────────────────────┘"
echo ""
