#!/bin/bash
# Reproduces the reported "API key test" bug using the REAL key already
# configured in the running container's own environment -- the value is
# read via docker exec into a shell variable and never typed, echoed, or
# logged by this script.
set -u

TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"final-admin@example.com","password":"FinalTestPass123!"}' \
  | node -e "process.stdin.on('data', d => console.log(JSON.parse(d).access_token))")
echo "Token acquired: ${#TOKEN} chars"

VT_KEY=$(docker exec app-backend-1 printenv VIRUSTOTAL_API_KEY)

echo "=== Test A: VirusTotal, REAL already-configured key (from container env) ==="
curl -s -X POST http://localhost:8000/api/v1/providers/virustotal/test \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"credentials\":{\"api_key\":\"$VT_KEY\"}}"
echo ""

echo "=== Test B: VirusTotal, empty key ==="
curl -s -X POST http://localhost:8000/api/v1/providers/virustotal/test \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"credentials":{"api_key":""}}'
echo ""

echo "=== Test C: VirusTotal, deliberately invalid key ==="
curl -s -X POST http://localhost:8000/api/v1/providers/virustotal/test \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"credentials":{"api_key":"totally-invalid-key-12345"}}'
echo ""

echo "=== Test D: nonexistent provider id (checks handler-not-found path) ==="
curl -s -X POST http://localhost:8000/api/v1/providers/groq/test \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"credentials":{"api_key":"test"}}'
echo ""

echo "=== Test E: malformed request body (missing credentials key) ==="
curl -s -w "\nHTTP_STATUS:%{http_code}\n" -X POST http://localhost:8000/api/v1/providers/virustotal/test \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{}'
echo ""

unset VT_KEY TOKEN
