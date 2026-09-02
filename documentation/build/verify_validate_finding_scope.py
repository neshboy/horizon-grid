import asyncio, uuid, sys
sys.path.insert(0, "/app")
from app.core.db import new_session
from app.models.pentest import PentestAssessment, PentestFinding
from app.pentest import orchestrator as svc

ASSESSMENT_ID = uuid.UUID("a10d48a9-f359-4f2b-bb66-795d77b80ee1")
FINDING_ID = uuid.UUID("31d1fc92-0696-4ce8-957c-f66fc68825e4")

async def main():
    # Step 1: confirm current scope still legitimately covers the finding's target (127.0.0.1/32)
    async with new_session() as db:
        a = await db.get(PentestAssessment, ASSESSMENT_ID)
        print("BEFORE narrowing, scope_definition:", a.scope_definition)

    # Step 2: re-probe should currently SUCCEED (target still in scope) -- sanity baseline
    try:
        f = await svc.validate_finding(FINDING_ID, "recheck_service_banner", None, "qa-script@local")
        print("BASELINE validate_finding (still in scope) -> OK, status:", f.status.value, "confidence:", f.confidence.value)
    except Exception as e:
        print("BASELINE validate_finding raised unexpectedly:", type(e).__name__, e)

    # Step 3: directly narrow scope_definition at the DB layer (simulating an operator's scope
    # edit that removed this target -- this is exactly the pre-existing state the P0 gap
    # required; we bypass the HTTP update_scope endpoint here only because that endpoint has
    # its own separate, correct guard against editing a COMPLETED assessment's scope, which
    # would otherwise block us from ever reaching the narrowed state needed to test
    # validate_finding()'s OWN independent re-check).
    async with new_session() as db:
        a = await db.get(PentestAssessment, ASSESSMENT_ID)
        a.scope_definition = {"cidrs": ["10.0.0.0/24"]}  # no longer includes 127.0.0.1
        db.add(a)
        await db.commit()
    async with new_session() as db:
        a = await db.get(PentestAssessment, ASSESSMENT_ID)
        print("AFTER narrowing, scope_definition:", a.scope_definition)

    # Step 4: re-probe should now be REJECTED by validate_finding()'s own scope re-check
    try:
        f = await svc.validate_finding(FINDING_ID, "recheck_service_banner", None, "qa-script@local")
        print("POST-NARROW validate_finding -> UNEXPECTEDLY SUCCEEDED (BUG):", f.status.value)
    except svc.TargetOutOfScopeError as e:
        print("POST-NARROW validate_finding correctly REJECTED with TargetOutOfScopeError:", e)
    except Exception as e:
        print("POST-NARROW validate_finding raised a DIFFERENT exception:", type(e).__name__, e)

    # Step 5: restore original scope so the assessment's evidence stays consistent for screenshots
    async with new_session() as db:
        a = await db.get(PentestAssessment, ASSESSMENT_ID)
        a.scope_definition = {"cidrs": ["127.0.0.1/32"]}
        db.add(a)
        await db.commit()
    print("Restored scope_definition to {'cidrs': ['127.0.0.1/32']}")

asyncio.run(main())
