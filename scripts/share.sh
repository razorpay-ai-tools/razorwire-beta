#!/usr/bin/env bash
#
# Put a local Razorwire on the public internet, for free, with no account.
#
#     bash scripts/share.sh
#
# Two Cloudflare quick tunnels — one to the API, one to the web app — then both
# servers, wired to each other's public URL. Prints the link to paste into Slack.
# Ctrl-C takes the whole thing down.
#
# Why this exists rather than a README section: a quick tunnel's hostname is random
# and changes every restart, and THREE settings depend on it (backend CORS, backend
# media URLs, and the frontend's API base). Doing that by hand once is fine; doing it
# every restart is where it gets typo'd and you spend an hour on a CORS error.
#
# Tunnels start BEFORE the servers on purpose: the backend needs the web app's public
# origin for CORS and the frontend needs the API's, so both URLs have to exist before
# either process does. cloudflared just returns 502 until its server comes up.
#
# Not a production host. The laptop must stay awake, and the URL dies with the process.
set -euo pipefail

cd "$(dirname "$0")/.."

for tool in cloudflared node; do
  command -v "$tool" >/dev/null || { echo "need $tool (brew install $tool)" >&2; exit 1; }
done
[ -x backend/.venv/bin/python ] || { echo "no backend/.venv — see README" >&2; exit 1; }

log_dir="$(mktemp -d)"
pids=()
cleanup() {
  [ ${#pids[@]} -gt 0 ] && kill "${pids[@]}" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# A quick tunnel announces its hostname on stderr a second or two after starting, so
# the URL has to be scraped rather than asked for. There is no --json for this.
start_tunnel() {
  local port="$1" log="$log_dir/tunnel-$1.log"
  cloudflared tunnel --url "http://127.0.0.1:$port" >"$log" 2>&1 &
  pids+=($!)
  for _ in $(seq 1 60); do
    local url
    url=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$log" 2>/dev/null | head -1)
    if [ -n "$url" ]; then echo "$url"; return 0; fi
    sleep 1
  done
  echo "tunnel for :$port never announced a URL; see $log" >&2
  return 1
}

echo "opening tunnels…"
api_url=$(start_tunnel 8000)
web_url=$(start_tunnel 3000)

# Shared secret, regenerated per run. It stops a crawler or a pasted link from
# spending LITELLM_API_KEY; it is NOT an identity gate, since it ships in the browser
# bundle. See TUNNEL_SECRET in backend/app/config.py.
secret=$(node -e 'console.log(require("crypto").randomBytes(24).toString("hex"))')

# Both origins stay allowed, so http://localhost:3000 keeps working while shared.
(
  cd backend
  WEB_ORIGIN="$web_url,http://localhost:3000" \
  PUBLIC_BASE_URL="$api_url" \
  TUNNEL_SECRET="$secret" \
    .venv/bin/python -m uvicorn app.main:app --port 8000
) &
pids+=($!)

# A PRODUCTION build, not `next dev`. Not a preference — `next dev` refuses to serve
# /_next/hmr and friends to any host but localhost ("Blocked cross-origin request to
# Next.js dev resource"), so over a tunnel the HTML arrives, the client JS never does,
# and the page sits on its server-rendered "Loading the feed…" forever. Nothing in the
# log looks wrong: every `GET /` is a 200.
#
# The build has to happen HERE, after the tunnels exist, because NEXT_PUBLIC_* values
# are inlined at build time and the API's hostname is not known before then. Costs
# ~30s per run and buys a viewer no HMR socket, no source maps and smaller chunks.
echo "building the web app against $api_url …"
NEXT_PUBLIC_API_URL="$api_url" \
NEXT_PUBLIC_API_SECRET="$secret" \
NEXT_PUBLIC_BACKEND_MODE=api \
  node_modules/.bin/next build >"$log_dir/build.log" 2>&1 \
  || { echo "next build failed; see $log_dir/build.log" >&2; exit 1; }

NEXT_PUBLIC_API_URL="$api_url" \
NEXT_PUBLIC_API_SECRET="$secret" \
  node_modules/.bin/next start -p 3000 >"$log_dir/web.log" 2>&1 &
pids+=($!)

# A quick tunnel's hostname is random per run, so under launchd — which restarts this
# unattended after a reboot or a crash — the public link changes with nobody watching
# the terminal that printed it. Last known URL goes somewhere fixed, so "what's the
# link right now" is answerable without digging through logs.
state_dir="$HOME/.razorwire"
mkdir -p "$state_dir"
cat >"$state_dir/urls.txt" <<EOF
web  $web_url
api  $api_url
logs $log_dir
EOF

cat <<EOF

  Share this in Slack:  $web_url

  api        $api_url
  logs       $log_dir
  current    $state_dir/urls.txt
  Ctrl-C     stops everything

  Anyone with the link is your DEV_AUTH_EMAIL user — this has no login of its own.
  Finished MP4s under /media are readable by URL without the secret.

EOF

wait
