# ─────────────────────────────────────────────────────────────────────────────
# File: scripts/apply_supabase_config.py
# Purpose: Applies Supabase auth config (email templates, redirect URLs) via
#          the Supabase Management API. Run this once after project creation
#          or whenever docs/supabase/ config changes. Keeps all Supabase
#          settings version-controlled instead of managed via dashboard.
# Language: Python
# Connects to: Supabase Management API (api.supabase.com)
# Inputs:  SUPABASE_PROJECT_REF, SUPABASE_MANAGEMENT_TOKEN env vars
#          docs/supabase/email_templates/magic_link.html
# Outputs: Updates project auth config in-place
# ─────────────────────────────────────────────────────────────────────────────

import os
import sys
from pathlib import Path

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_REF = os.environ.get("SUPABASE_PROJECT_REF", "lrqjfwvhcuguwdveryof")
MANAGEMENT_TOKEN = os.environ.get("SUPABASE_MANAGEMENT_TOKEN", "")

if not MANAGEMENT_TOKEN:
    print("ERROR: SUPABASE_MANAGEMENT_TOKEN is not set.")
    print("Get one at: https://supabase.com/dashboard/account/tokens")
    sys.exit(1)

TEMPLATES_DIR = Path(__file__).parent.parent / "docs" / "supabase" / "email_templates"
API_BASE = "https://api.supabase.com/v1"

# ── Email templates ───────────────────────────────────────────────────────────

magic_link_html = (TEMPLATES_DIR / "magic_link.html").read_text()

# ── Redirect URLs ─────────────────────────────────────────────────────────────
# Add new entries here as needed (e.g. staging domains).

SITE_URL = "https://ai-engineering-study-agent.vercel.app"
ADDITIONAL_REDIRECT_URLS = [
    "http://localhost:5173/**",
    "https://ai-engineering-study-agent.vercel.app/**",
]

# ── Apply ─────────────────────────────────────────────────────────────────────

payload = {
    # Redirect URLs
    "site_url": SITE_URL,
    "uri_allow_list": ",".join(ADDITIONAL_REDIRECT_URLS),
    # Magic link / OTP email template
    "mailer_templates_magic_link_content": magic_link_html,
}

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
