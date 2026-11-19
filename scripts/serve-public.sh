#!/usr/bin/env bash
# Expose StudentHub publicly via a Cloudflare quick tunnel.
#
#   scripts/serve-public.sh   start (URL printed and written to database/logs/url.txt)
#   Ctrl+C or kill <PID>      stop (PID in database/logs/serve.pid)
#
# Config: database/public.env. caffeinate prevents idle sleep. The URL changes on every restart.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=database/public.env
[ -f "$ENV_FILE" ] || { echo "Немає $ENV_FILE — див. README, розділ «Публічний доступ»" >&2; exit 1; }
command -v cloudflared >/dev/null || { echo "Встановіть cloudflared: brew install cloudflared" >&2; exit 1; }
set -a; source "$ENV_FILE"; set +a

LOGS=database/logs
mkdir -p "$LOGS"
rm -f "$LOGS/url.txt"
: > "$LOGS/tunnel.log"   # avoid picking up a stale URL
echo $$ > "$LOGS/serve.pid"

.venv/bin/python run.py >> "$LOGS/server.log" 2>&1 &
SERVER=$!
cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:${PORT:-8000}" >> "$LOGS/tunnel.log" 2>&1 &
TUNNEL=$!
caffeinate -i -w "$SERVER" &

cleanup() { kill "$SERVER" "$TUNNEL" 2>/dev/null || true; rm -f "$LOGS/serve.pid" "$LOGS/url.txt"; }
trap cleanup EXIT INT TERM

URL=""
for _ in $(seq 1 60); do
    URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGS/tunnel.log" | tail -1 || true)
    [ -n "$URL" ] && break
    kill -0 "$SERVER" 2>/dev/null || { echo "Сервер не запустився — див. $LOGS/server.log" >&2; exit 1; }
    sleep 1
done
[ -n "$URL" ] || { echo "Тунель не відкрився — див. $LOGS/tunnel.log" >&2; exit 1; }
echo "$URL" > "$LOGS/url.txt"
echo "StudentHub доступний за адресою: $URL"

# Exit when either the server or the tunnel dies
while kill -0 "$SERVER" 2>/dev/null && kill -0 "$TUNNEL" 2>/dev/null; do sleep 5; done
