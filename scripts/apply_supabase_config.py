# ─────────────────────────────────────────────────────────────────────────────
# File: scripts/apply_supabase_config.py
# Purpose: Applies Supabase auth config (email templates, redirect URLs, Google
#          OAuth provider) via the Supabase Management API. Run this once after
#          project creation or whenever config changes. Keeps all Supabase
#          settings version-controlled instead of managed via dashboard.
# Language: Python
# Connects to: Supabase Management API (api.supabase.com)
# Inputs:  SUPABASE_PROJECT_REF, SUPABASE_MANAGEMENT_TOKEN, APP_SITE_URL env vars
#          APP_REDIRECT_URLS env var (optional, comma-separated)
#          GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET env vars (optional)
#          docs/supabase/email_templates/magic_link.html
# Outputs: Updates project auth config in-place
# ─────────────────────────────────────────────────────────────────────────────

import os
import sys
from pathlib import Path

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_REF = os.environ.get("SUPABASE_PROJECT_REF", "").strip()
MANAGEMENT_TOKEN = os.environ.get("SUPABASE_MANAGEMENT_TOKEN", "")
SITE_URL = os.environ.get("APP_SITE_URL", "").strip()
REDIRECT_URLS_RAW = os.environ.get("APP_REDIRECT_URLS", "").strip()
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()

if not PROJECT_REF:
    print("ERROR: SUPABASE_PROJECT_REF is not set.")
    sys.exit(1)
if not MANAGEMENT_TOKEN:
    print("ERROR: SUPABASE_MANAGEMENT_TOKEN is not set.")
    print("Get one at: https://supabase.com/dashboard/account/tokens")
    sys.exit(1)
if not SITE_URL:
    print("ERROR: APP_SITE_URL is not set.")
    sys.exit(1)

TEMPLATES_DIR = Path(__file__).parent.parent / "docs" / "supabase" / "email_templates"
API_BASE = "https://api.supabase.com/v1"

# ── Email templates ───────────────────────────────────────────────────────────

magic_link_html = (TEMPLATES_DIR / "magic_link.html").read_text()

# ── Redirect URLs ─────────────────────────────────────────────────────────────
# APP_REDIRECT_URLS is comma-separated. If omitted, default to site URL + local dev.

default_redirect_urls = [
    "http://localhost:5173/**",
    f"{SITE_URL.rstrip('/')}/**",
]
redirect_urls = [
    value.strip()
    for value in (REDIRECT_URLS_RAW.split(",") if REDIRECT_URLS_RAW else default_redirect_urls)
    if value.strip()
]

# ── Apply ─────────────────────────────────────────────────────────────────────

payload = {
    # Redirect URLs
    "site_url": SITE_URL,
    "uri_allow_list": ",".join(redirect_urls),
    # Magic link / OTP email template
    "mailer_templates_magic_link_content": magic_link_html,
}

# Google OAuth — only included if credentials are present in env.
# Credentials stored in GCP Secret Manager: google-oauth-client-id, google-oauth-client-secret.
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    payload["external_google_enabled"] = True
    payload["external_google_client_id"] = GOOGLE_CLIENT_ID
    payload["external_google_secret"] = GOOGLE_CLIENT_SECRET
    print("  Google OAuth: enabled")

headers = {
    "Authorization": f"Bearer {MANAGEMENT_TOKEN}",
    "Content-Type": "application/json",
}

print(f"Applying Supabase auth config to project: {PROJECT_REF}")

response = httpx.patch(
    f"{API_BASE}/projects/{PROJECT_REF}/config/auth",
    json=payload,
    headers=headers,
    timeout=15,
)

if response.status_code == 200:
    print("Done.")
else:
    print(f"ERROR {response.status_code}: {response.text}")
    sys.exit(1)
