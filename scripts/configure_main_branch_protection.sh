#!/usr/bin/env bash
set -euo pipefail

apply=false
repo=""
for argument in "$@"; do
  case "$argument" in
    --apply) apply=true ;;
    *)
      if [[ -n "$repo" ]]; then
        echo "Usage: $0 [owner/repo] [--apply]" >&2
        exit 1
      fi
      repo="$argument"
      ;;
  esac
done

if [[ -z "$repo" ]]; then
  repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
fi

if [[ -z "$repo" ]]; then
  echo "Usage: $0 [owner/repo] [--apply]" >&2
  exit 1
fi

proposed="$(mktemp)"
current="$(mktemp)"
trap 'rm -f "$proposed" "$current"' EXIT

python3 - "$proposed" <<'PY'
import json
import sys

payload = {
    "required_status_checks": {
        "strict": True,
        "contexts": ["CI required", "Live eval required"],
    },
    "enforce_admins": True,
    "required_pull_request_reviews": None,
    "restrictions": None,
    "required_linear_history": False,
    "allow_force_pushes": False,
    "allow_deletions": False,
    "block_creations": False,
    "required_conversation_resolution": False,
    "lock_branch": False,
    "allow_fork_syncing": True,
}
with open(sys.argv[1], "w", encoding="utf-8") as output:
    json.dump(payload, output, indent=2)
    output.write("\n")
PY

if gh api -H "Accept: application/vnd.github+json" "/repos/$repo/branches/main/protection" > "$current" 2>/dev/null; then
  echo "Current protection summary:"
  python3 - "$current" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
checks = data.get("required_status_checks") or {}
contexts = checks.get("contexts") or [check.get("context") for check in checks.get("checks") or []]
print({"strict": checks.get("strict"), "contexts": contexts, "enforce_admins": (data.get("enforce_admins") or {}).get("enabled")})
PY
else
  echo "Current protection could not be read; the proposed payload is still shown below."
fi

echo "Proposed protection payload for $repo:"
cat "$proposed"

if [[ "$apply" != true ]]; then
  echo "Dry run only. Re-run with --apply after reviewing the payload."
  exit 0
fi

gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "/repos/$repo/branches/main/protection" \
  --input "$proposed"
