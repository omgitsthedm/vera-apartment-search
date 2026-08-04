#!/usr/bin/env bash
# VERA setup — the four owner gates, one guided pass.
# Nothing here leaves your machine: the config files it writes are
# gitignored, and the GitHub secrets go straight to GitHub via gh.
# Skip any step by pressing Return at its first prompt.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="$ROOT/configs"
B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; D=$'\033[2m'; R=$'\033[0m'

echo
echo "${B}VERA setup${R} — four gates, ~15 minutes. Return skips any step."
echo

# ── 1. Gmail saved-search ingestion ────────────────────────────────
echo "${B}[1/4] The Gmail firehose${R} ${D}(biggest win)${R}"
# "Already configured" must mean "actually works", not "a file exists". A
# config holding a rejected password would otherwise cause this step to skip
# itself forever while the firehose stayed dead.
if [[ -f "$CFG/mail_ingest.json" ]] && ! grep -q "YOUR_\|PASTE" "$CFG/mail_ingest.json" \
   && python3 "$ROOT/scripts/ingest_mail_alerts.py" 2>/dev/null | grep -q '"status": "ok"'; then
  echo "  ${G}already configured and connecting${R} — skipping"
else
  if [[ -f "$CFG/mail_ingest.json" ]]; then
    echo "  ${Y}A config exists but Gmail is rejecting it — re-entering.${R}"
  fi
  echo "  First, in your browser (skip if done):"
  echo "   • Dedicated inbox: prefer ${B}vera.littlefightnyc@gmail.com${R} or the nearest available handle; recovery goes to hello@littlefightnyc.com"
  echo "   • StreetEasy + Zillow: save your searches, turn ${B}instant email alerts${R} on"
  echo "   • Google Account → Security → 2-Step Verification → ${B}App passwords${R} → create one"
  echo
  read -r -p "  Your Gmail address (Return to skip): " MAIL_ADDR
  if [[ -n "$MAIL_ADDR" ]]; then
    :
    read -r -s -p "  The 16-character app password (hidden): " MAIL_PW; echo
    MAIL_PW="${MAIL_PW// /}"
    # A Google app password is exactly 16 lowercase letters. Anything else is
    # almost always the account password typed by mistake, which fails IMAP
    # with a bare AUTHENTICATIONFAILED and no hint about why.
    while [[ ${#MAIL_PW} -ne 16 || ! "$MAIL_PW" =~ ^[a-zA-Z]{16}$ ]]; do
      echo "  ${Y}That is ${#MAIL_PW} characters. A Google app password is exactly 16 letters.${R}"
      echo "  ${D}If you typed your normal account password, that will not work — IMAP only"
      echo "  accepts an app password. Get one at myaccount.google.com/apppasswords"
      echo "  (it only appears once 2-Step Verification is on).${R}"
      read -r -s -p "  App password (hidden, or Return to skip this step): " MAIL_PW; echo
      MAIL_PW="${MAIL_PW// /}"
      [[ -z "$MAIL_PW" ]] && break
    done
    cat > "$CFG/mail_ingest.json" <<JSON
{
  "imap_host": "imap.gmail.com",
  "email": "$MAIL_ADDR",
  "app_password": "$MAIL_PW",
  "folder": "INBOX",
  "senders": ["notifications@streeteasy.com", "convo@zillow.com", "no-reply@mail.zillow.com"]
}
JSON
    chmod 600 "$CFG/mail_ingest.json"
    echo -n "  testing the connection… "
    if python3 "$ROOT/scripts/ingest_mail_alerts.py" 2>/dev/null | grep -q '"status": "ok"'; then
      echo "${G}connected${R}"
    else
      echo "${Y}could not read the inbox — check the address and app password${R}"
    fi
  fi
fi
echo

# ── 2. Reddit OAuth ────────────────────────────────────────────────
echo "${B}[2/4] Reddit API${R}"
if [[ -f "$CFG/reddit.json" ]] && ! grep -q "YOUR_\|PASTE" "$CFG/reddit.json"; then
  echo "  ${G}already configured${R} — skipping"
else
  echo "  reddit.com/prefs/apps → create app → type ${B}script${R}, redirect http://localhost:8080"
  read -r -p "  Client ID (under the app name; Return to skip): " RD_ID
  if [[ -n "$RD_ID" ]]; then
    read -r -s -p "  Client secret (hidden): " RD_SECRET; echo
    read -r -p "  Your reddit username: " RD_USER
    cat > "$CFG/reddit.json" <<JSON
{
  "client_id": "$RD_ID",
  "client_secret": "$RD_SECRET",
  "user_agent": "vera-littlefightnyc-apartment-watch/1.0 by ${RD_USER:-anonymous}"
}
JSON
    chmod 600 "$CFG/reddit.json"
    echo "  ${G}written${R} — the next sweep uses the authenticated API"
  fi
fi
echo

# ── 3. Cloud publish ───────────────────────────────────────────────
# This step used to demand a Netlify token, and the whole "the Mac can stay
# off" promise was stuck behind it. It is no longer needed: the nightly
# sweep publishes to the `feed` branch of the public repo, which
# raw.githubusercontent serves to browsers with CORS. Nothing to enter.
echo "${B}[3/4] Cloud publish${R} ${D}(lets the Mac stay off)${R}"
FEED_URL="https://raw.githubusercontent.com/omgitsthedm/vera-apartment-search/feed/meta.json"
if curl -sfL --max-time 15 "$FEED_URL" -o /tmp/vera_feed_meta.json 2>/dev/null; then
  echo "  ${G}publishing already — no token required${R}"
  python3 - <<'PY' 2>/dev/null || true
import json
m = json.load(open("/tmp/vera_feed_meta.json"))
print(f"  last cloud publish: {m.get('generated_at')} — {m.get('pool')} listings, {m.get('shortlist')} shortlisted")
PY
else
  echo "  ${Y}no cloud feed published yet${R} — it lands on the next nightly sweep (05:30 UTC)"
  echo "  ${D}or run it now: gh workflow run sanctioned-cloud-sweep.yml${R}"
fi
echo

# ── 4. Hugging Face ────────────────────────────────────────────────
echo "${B}[4/4] Hugging Face${R} ${D}(publishes the open datasets)${R}"
if command -v hf >/dev/null 2>&1; then
  if hf auth whoami >/dev/null 2>&1; then
    echo "  ${G}already logged in as $(hf auth whoami 2>/dev/null | head -1)${R}"
  else
    read -r -p "  Log in now? [y/N] " YN
    [[ "$YN" =~ ^[Yy] ]] && hf auth login
  fi
else
  echo "  ${Y}hf CLI not found — skipping${R}"
fi

echo
echo "${B}Done.${R} Anything you filled activates on the next sweep — nothing else to run."
echo "${D}Tell Claude \"setup done\" and it verifies each gate end to end.${R}"
echo
