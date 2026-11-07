#!/usr/bin/env bash
# Check a running deployment (cloud or local) without changing anything.
# Usage: scripts/check_deploy.sh <api-url> [ui-url]
set -u
API="${1:?usage: check_deploy.sh <api-url> [ui-url]}"
UI="${2:-}"
fail=0
check() { # description, expected, actual
  if [ "$2" = "$3" ]; then echo "ok    $1"; else echo "FAIL  $1 (expected $2, got $3)"; fail=1; fi
}
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@"; }

check "api /health" 200 "$(code "$API/health")"
check "api /queue" 200 "$(code "$API/queue")"
case "$API" in
  https://*)
    # In the cloud a write without the demo token must be refused (403, or 503 if no token is set).
    got="$(code -X POST "$API/kill_switch" -H 'content-type: application/json' -d '{"on":false,"actor":"check"}')"
    if [ "$got" = 403 ] || [ "$got" = 503 ]; then echo "ok    write without a token is refused ($got)"; else echo "FAIL  write without a token returned $got"; fail=1; fi
    echo "ok    api uses HTTPS"
    ;;
  *) echo "note  local api: write check skipped (no token needed locally)" ;;
esac
echo "source: $(curl -s --max-time 10 "$API/health")"
if [ -n "$UI" ]; then
  check "ui /" 200 "$(code "$UI/")"
  check "ui forwards /api/health" 200 "$(code "$UI/api/health")"
fi
exit $fail
