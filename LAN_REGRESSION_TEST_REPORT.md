# IOC Intelligence Platform — LAN Deployment Regression Test Report

**Test date:** 2026-08-14
**Tester:** Automated QA pass (Claude Code)
**Scope:** Confirm the LAN-deployment change set (see `LAN_DEPLOYMENT_QA_REPORT.md`) introduced no regressions to existing functionality, security boundaries, or data integrity.

---

## 1. Automated test suite

```
159 passed in 1.47s
```
Full backend unit suite (`app/tests/unit`), run inside the live `app-backend-1` container against the real database, post network-change and post credential fix. No failures, no skips.

## 2. Security boundaries — unchanged or strengthened, not weakened

| Boundary | Result |
|---|---|
| Auth (JWT) | Not touched by any LAN change; CORS relaxation only widens which *origins* the browser is allowed to call from — the actual authorization check is unchanged and independent of origin. |
| API keys / provider credentials | Never sent to the browser; `encrypted_credentials` stays server-side, decrypted only in-process. Verified 8/8 rows with real stored credentials decrypt correctly post-change. |
| Database exposure | Postgres, Redis, Neo4j, OpenSearch remain bound to `127.0.0.1` only — confirmed unchanged by this work; LAN accessibility applies only to the frontend/backend ports (3000/8000). |
| CORS | Went from a single static localhost origin to a private-network-range regex — confirmed it still rejects arbitrary public origins (`evil.example.com` → no `Access-Control-Allow-Origin` header) while now correctly accepting private-network origins that were previously (incorrectly, for this feature) rejected. |
| Firewall | New rule is additive and minimally scoped (Private profile, 2 specific TCP ports); no existing rule was modified or broadened. |

## 3. Functional regression

- Backend `/health`: `{"status":"ok",...}`
- Frontend root: HTTP 200
- `/network-info`: returns correct, current values (`detected_lan_ip`, `frontend_port`, `backend_port`) — new endpoint, additive, no existing endpoint's behavior changed.
- All 8 application containers (`postgres`, `redis`, `neo4j`, `opensearch`, `backend`, `frontend`, `celery_worker`, `celery_beat`) started and reached healthy/running state via the real `docker-compose.yml` + `docker-compose.prod.yml` + the real `.env`.
- Data integrity across an uninstall("keep data")→reconfigure→network-change→Docker-restart cycle: exact row-count match against the pre-uninstall snapshot (1 user, 1 case, 20 `ioc_lookups`, 21 `provider_runtime_configs`).
- Credential round-trip: all provider/AI credentials that were ever actually configured (8 of 21 rows) decrypt to plausible plaintext; the other 13 rows are legitimately never-configured (empty ciphertext by design, not a decryption failure).

## 4. Known-good-before-this-pass items not re-verified live this session

The following were verified in an earlier verification pass within this engagement (see `LAN_DEPLOYMENT_QA_REPORT.md` §2) and are not expected to have regressed, since no related code changed between passes, but were not re-screenshotted/re-curled live in this specific session:

- Live SSE-streamed IOC investigation over a real LAN IP in the browser.
- The `NetworkAccessPanel` UI rendering in an actual authenticated browser session (this session had no admin credentials on hand to log in with; the panel's data source, `/network-info`, was freshly re-verified via `curl` instead — see above).

## 5. Incident during this pass (fixed, not a regression in the LAN feature itself)

A Postgres password / persisted-`.env` divergence — caused by an earlier, unrelated manual database fix in a prior debugging session never having been written back to `.env` — surfaced when containers were recreated after the network move. This was not caused by, and does not indicate a defect in, any of the LAN-deployment code (`Get-LanIpAddress`, `Write-PlatformEnvFile`, `New-AppFirewallRule`, or the CORS/`, /network-info` changes) — none of that code touches database credentials. Fixed with explicit user approval; verified clean afterward (§1–§3 above all ran after this fix).

## 6. Conclusion

No regressions found. The LAN-deployment change set is additive (new endpoint, new UI tab, new PowerShell functions, a widened-but-still-scoped CORS policy, an additive firewall rule) and every existing security boundary and data path checked out unchanged. The one real bug hit during this pass was pre-existing operational drift, not a regression introduced by this work, and is now resolved.
