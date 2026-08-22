# Roadmap and Conclusion

## What's Provisioned but Not Yet Wired Up

Two pieces of infrastructure already run in the Docker Compose stack with real configuration fields but no consuming code yet, confirmed directly against source: **Neo4j** (the `neo4j:5-community` container with the APOC plugin, plus `neo4j_uri`/`neo4j_user`/`neo4j_password` settings — no driver instantiation or Cypher code exists anywhere in the backend today; the correlation graph the product actually shows lives entirely in Postgres) and **OpenSearch** (the `opensearchproject/opensearch:2.17.0` container plus an `opensearch_url` setting — no indexing or query code exists against it today). Completing either is a bounded extension of infrastructure already provisioned, not a new subsystem. The full detail, including a diagram of today's actual wiring versus the provisioned-but-unconsumed pieces, lives in the Future Roadmap chapter of the Technical Documentation.

## What's Genuinely Open, Disclosed by the Project's Own QA Reports

This submission's Bug History and Testing Journey chapters carry forward, rather than hide, what the project's own most recent QA reports state as still open at the time they were written: no automated host-disk-space alerting or investigation-table retention job; a DNS-rebinding TOCTOU gap on the outbound SSRF check; no off-site backup copy; several P2–P4 findings from the adversarial red-team pass not yet independently re-verified a second time; and the most recent functional-test report explicitly marking its own verdict as interim, with roughly two-thirds of a planned 33-phase mission not yet run. None of this is softened in the narrative chapters — the project's engineering discipline throughout has been to disclose a gap the moment it's found, not to wait until it's closed to mention it.

## Where the Architecture Is Already Positioned to Grow

The registry pattern behind both the 18-provider IOC ecosystem and the 11-backend AI layer already normalizes heterogeneous sources behind one shared interface each (`BaseProvider`/`supports(ioc_type)`, and `call_claude_json()` respectively) — onboarding further providers or AI backends is proven, incremental work at this point, not a redesign. The same is true of the Security Assessment Toolkit's tool-adapter pattern and the deterministic scoring engine's versioned weight table, both built to be extended rather than rewritten.

## Conclusion

HORIZON GRID's central bet is that a threat-intelligence tool earns trust by showing its work: a deterministic score computed the same way every time, an AI that narrates a number it cannot override, a Provider Health page that reports Unknown rather than faking Healthy, and an Executive Dashboard where every tile is a real query result. That bet shaped the architecture from the scoring engine outward, and it shaped how this submission itself was written — every bug in the Bug History chapter is real, every open item in the Known Limitations sections is still open, and every screenshot in this package is a live capture of the running product, not a mockup.

The name and the tagline were chosen to describe exactly that outcome, not just to sound serious: **HORIZON GRID — Every Signal. One Operational Picture.**
