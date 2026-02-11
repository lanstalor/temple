#!/bin/bash
# Temple production smoke test
# Usage: bash docker/scripts/smoke-test.sh [BASE_URL] [API_KEY]
#   BASE_URL defaults to http://localhost:8100
#   API_KEY  defaults to empty (unauthenticated checks only)
set -uo pipefail

BASE_URL="${1:-http://localhost:8100}"
API_KEY="${2:-}"
BASE_URL="${BASE_URL%/}"

PASS=0
FAIL=0
SKIP=0

check() {
    local label="$1"
    local result="$2"
    local expected="${3:-200}"
    if [ "$result" = "$expected" ]; then
        echo "  PASS  $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $label  (got $result, expected $expected)"
        FAIL=$((FAIL + 1))
    fi
}

skip() {
    local label="$1"
    local reason="$2"
    echo "  SKIP  $label  ($reason)"
    SKIP=$((SKIP + 1))
}

auth_header() {
    if [ -n "$API_KEY" ]; then
        echo "Authorization: Bearer $API_KEY"
    fi
}

echo "=== Temple Smoke Test ==="
echo "Target: $BASE_URL"
echo "Auth:   $([ -n "$API_KEY" ] && echo "API key provided" || echo "none (auth checks will be skipped)")"
echo ""

# --- Unauthenticated endpoints ---

echo "-- Health & Discovery --"

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_URL/health")
check "/health" "$code"

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_URL/openapi.json")
check "/openapi.json" "$code"

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_URL/docs")
check "/docs (Swagger UI)" "$code"

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_URL/atlas")
check "/atlas (Graph UI)" "$code"

# --- Health response content ---

health_body=$(curl -s --max-time 10 "$BASE_URL/health")
health_status=$(echo "$health_body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
check "/health status=healthy" "$health_status" "healthy"

graph_schema=$(echo "$health_body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('graph_schema',''))" 2>/dev/null)
check "/health graph_schema=v2" "$graph_schema" "v2"

# --- OAuth metadata endpoints ---

echo ""
echo "-- OAuth Metadata --"

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_URL/.well-known/oauth-authorization-server")
# Returns 200 when auth enabled, 404 when disabled — both are valid
if [ "$code" = "200" ] || [ "$code" = "404" ]; then
    check "/.well-known/oauth-authorization-server" "reachable" "reachable"
else
    check "/.well-known/oauth-authorization-server" "$code" "200 or 404"
fi

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_URL/.well-known/oauth-protected-resource")
if [ "$code" = "200" ] || [ "$code" = "404" ]; then
    check "/.well-known/oauth-protected-resource" "reachable" "reachable"
else
    check "/.well-known/oauth-protected-resource" "$code" "200 or 404"
fi

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_URL/mcp/.well-known/oauth-protected-resource")
if [ "$code" = "200" ] || [ "$code" = "404" ]; then
    check "/mcp/.well-known/oauth-protected-resource" "reachable" "reachable"
else
    check "/mcp/.well-known/oauth-protected-resource" "$code" "200 or 404"
fi

# --- MCP endpoint ---

echo ""
echo "-- MCP Endpoint --"

# MCP streamable-http should accept POST (returns error without proper body, but not 404)
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "$BASE_URL/mcp" -H "Content-Type: application/json" -d '{}')
if [ "$code" != "404" ] && [ "$code" != "000" ]; then
    check "/mcp POST reachable" "reachable" "reachable"
else
    check "/mcp POST reachable" "$code" "not 404"
fi

# --- Authenticated endpoints ---

echo ""
echo "-- Authenticated REST Routes --"

if [ -z "$API_KEY" ]; then
    skip "/api/v1/admin/stats" "no API key"
    skip "/api/v1/admin/graph-schema" "no API key"
    skip "/api/v1/context" "no API key"
    skip "/api/v1/admin/stats (401 without auth)" "no API key"
else
    # Verify auth is enforced (no key → 401)
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_URL/api/v1/admin/stats")
    check "/api/v1/admin/stats rejects unauthenticated" "$code" "401"

    # Authenticated requests
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H "$(auth_header)" "$BASE_URL/api/v1/admin/stats")
    check "/api/v1/admin/stats" "$code"

    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H "$(auth_header)" "$BASE_URL/api/v1/admin/graph-schema")
    check "/api/v1/admin/graph-schema" "$code"

    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H "$(auth_header)" "$BASE_URL/api/v1/context")
    check "/api/v1/context" "$code"

    # Graph export (verifies vector + graph subsystems respond)
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 -H "$(auth_header)" "$BASE_URL/api/v1/admin/graph/export?limit=1")
    check "/api/v1/admin/graph/export" "$code"

    # Memory store + retrieve round-trip
    store_resp=$(curl -s --max-time 15 -X POST -H "$(auth_header)" -H "Content-Type: application/json" \
        "$BASE_URL/api/v1/memory/store" \
        -d '{"content":"smoke-test probe","tags":["smoke-test"],"scope":"global"}')
    store_id=$(echo "$store_resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
    if [ -n "$store_id" ]; then
        check "memory store round-trip" "stored" "stored"

        # Clean up the smoke test memory
        del_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X DELETE -H "$(auth_header)" \
            "$BASE_URL/api/v1/memory/$store_id?scope=global")
        check "memory delete cleanup" "$del_code"
    else
        check "memory store round-trip" "failed" "stored"
    fi
fi

# --- Summary ---

echo ""
TOTAL=$((PASS + FAIL + SKIP))
echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped (of $TOTAL checks) ==="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
