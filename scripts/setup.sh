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

# ── 3. Cloud publish secrets ───────────────────────────────────────
echo "${B}[3/4] Cloud publish${R} ${D}(lets the Mac stay off)${R}"
if command -v gh >/dev/null 2>&1 && gh secret list -R omgitsthedm/vera-apartment-search 2>/dev/null | grep -q NETLIFY_AUTH_TOKEN; then
  echo "  ${G}already set${R} — skipping"
elif command -v gh >/dev/null 2>&1; then
  echo "  Token: sign in as the Little Fight NYC Netlify Owner (hello@littlefightnyc.com) → User settings → Applications → New access token → description 'VERA cloud publish'"
  read -r -p "  Set the Netlify secrets now? [y/N] " YN
  if [[ "$YN" =~ ^[Yy] ]]; then
    gh secret set NETLIFY_AUTH_TOKEN -R omgitsthedm/vera-apartment-search
    echo "fcd6f741-d479-44f4-8ee1-51da2b321227" | gh secret set NETLIFY_SITE_ID -R omgitsthedm/vera-apartment-search
    echo "  ${G}secrets stored${R} — tell Claude \"secrets in\" to wire the publish job"
  fi
else
  echo "  ${Y}gh not found — skipping${R}"
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
