# Brand Identity

## Name and Tagline

**HORIZON GRID** — **"Every Signal. One Operational Picture."**

The name and tagline are meant to be read literally, not just atmospherically: "signal" is what a single provider or evidence item contributes; "grid" and "horizon" evoke a fixed reference frame that many independent signals get plotted onto; "one operational picture" is the actual product outcome — a correlated, scored, explainable view assembled from everything the platform collected, rather than a raw dump of provider responses.

## Logo Concept

The mark is wholly geometric and original: a horizon line with two open "signal" nodes converging on one filled "detection" node. It is a literal depiction of the tagline — multiple signals resolving into one picture — rather than a generic shield, seal, or insignia shape. It exists in three forms:

- **Full lockup** — the mark plus the "HORIZON GRID" wordmark, used on the login/register screens and the About page.
- **Compact lockup** — the mark plus "HG" set inside a corner-bracket badge frame, used in the persistent header on every authenticated page.
- **Favicon** — a three-primitive degraded form of the same mark, simplified to stay legible at 16px.

No part of the mark reuses or resembles any existing military insignia, government seal, NATO symbol, or real defense-contractor logo (Lockheed Martin or otherwise) — a constraint that was explicit in this pass's own brief and was checked directly against the final design.

## Color System

A CRT-phosphor teal-cyan is the primary color, chosen specifically to avoid the generic SaaS-dashboard blue most competing tools default to. It sits against a near-black "anodized steel panel" background with a warm off-white foreground — dark enough to read as an operational console, warm enough to avoid the colder, more generic near-black-and-electric-blue palette associated with stock "hacker" UI kits.

## Status Indicator Language

Every operational status in the product — provider health, system health, investigation state — is expressed through one shared six-state vocabulary: **OPERATIONAL, DEGRADED, WARNING, CRITICAL, OFFLINE, UNKNOWN**. Each state is encoded through a distinct hue, fill density, border style, *and* icon simultaneously, so the state is never carried by color alone. This same vocabulary is what Provider Health's four real status categories (Healthy/Degraded/Down/Unknown) map onto — mapped honestly (Healthy→Operational, Down→Offline) rather than inventing new states for data the backend doesn't actually report.

## Typography

- **IBM Plex Sans Condensed** — headings, the wordmark, section/panel labels.
- **IBM Plex Mono**, with tabular numerals — every raw technical value: IP addresses, hashes, timestamps, coordinates, counts, and scores.
- **Inter** (unchanged) — body copy, left untouched to avoid disturbing the product's existing dense data tables.

## Shape and Elevation

Outer containers (panels, cards) keep a softer corner radius; interactive and status elements (buttons, inputs, badges, chips) use a visibly sharper radius — a deliberate contrast meant to read as soft panels precisely containing exact controls. Cards are a flat fill bounded by a hairline border rather than drop-shadowed, so the interface reads as machined layers rather than a floating card stack.

## Navigation and Panels

The persistent header (`BrandHeader`) pairs the compact logo lockup with a live system-status indicator sourced from the real `GET /health/detailed` endpoint (polled every 60 seconds, never hardcoded), the global search bar, and the existing workspace navigation grouped by function (Command / Intelligence / Analysis / Operations / Administration). Section headers throughout the product (`CardTitle`) render as uppercase, letter-spaced, muted "instrument-panel" labels by default — an "operational readout" register applied once at the shared-component level so it took effect consistently everywhere without a per-page edit.

[FIGURE: about-page.png | The About page — the full mark lockup, live version and dependency status, and the platform/documentation summary.]

[FIGURE: ai-quickswitch-dropdown.png | The compact mark and status language reused in context — the AI backend selector on the home page, showing all eleven configured backends.]

## Why This Design Was Chosen

The identity had to satisfy two requirements that are easy to satisfy separately but hard to satisfy together: look like professional, mission-ready operational software, and be demonstrably original — no real insignia, seal, or defense-contractor mark anywhere in it, and no cyberpunk-movie neon-glow excess either. "Datum Signal" was the strongest of three independently generated candidate identities, chosen because its status language and shape language carry the "operational instrument" feeling structurally (through contrast, iconography, and a consistent status vocabulary) rather than through any single borrowed visual trope.
