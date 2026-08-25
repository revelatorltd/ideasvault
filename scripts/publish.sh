#!/usr/bin/env bash
# Publish one artifact:  ./scripts/publish.sh ~/Downloads/idea.html
set -euo pipefail
: "${VAULT_URL:?set VAULT_URL, e.g. https://ideas.example.com}"
: "${VAULT_TOKEN:?set VAULT_TOKEN}"
curl -fsS -X POST "$VAULT_URL/api/publish" \
  -H "Authorization: Bearer $VAULT_TOKEN" \
  -F "file=@$1;type=text/html" | python3 -m json.tool
