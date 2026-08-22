# Design Evolution

## Where the UI Started

Through the earliest hardening phases (the adversarial audit, the AI provider expansion, the port-scanner cancellation work, and the mission-critical reliability pass — all documented in the Development Journey chapter), the product's UI was functional but generic: a bare search bar and a `WorkspaceNav` top-nav pair repeated at the top of every page, default-case headings, drop-shadowed cards, and a color palette close to the generic SaaS blue most dashboard tools default to. The product name and tagline were barely visible anywhere in the running application — a real gap once the underlying product (17 providers at the time, 11 AI backends, a deterministic scoring engine, an Executive Dashboard, a Provider Health page) had become substantial enough to deserve a real visual identity.

## The Branding Pass (v0.2.4)

The last development phase before this submission was a dedicated, presentation-only branding and UI/UX pass, scoped deliberately not to touch backend logic, database schema, authentication, IOC processing, AI provider logic, provider API logic, port-scanner logic, or admin permissions — verified by a full backend regression run (383 passed, 39 skipped, zero regressions) and a clean frontend typecheck both before and after the change.

Three independent visual-identity proposals were generated and judged against each other before implementation began, rather than committing to the first idea that looked reasonable — the same "generate several candidates, synthesize the strongest one" discipline used elsewhere in this project's engineering process. The proposal that won, internally named **"Datum Signal,"** is documented in full in the Brand Identity chapter.

## Design Philosophy

The brief for this pass was explicit about the tone to hit and the tone to avoid: the product needed to read as **military-inspired, rugged, operational, mission-ready, precise, technical, and high-trust** — the seriousness of professional aerospace/defense operational software — without literally copying any real defense contractor, military organization, or government agency's branding, insignia, seal, or trademark, and without sliding into a "cyberpunk movie interface" of neon glow and fake-terminal effects. Every element of the final identity was built to satisfy that brief with an *original* mark, palette, and status language rather than borrowed or generic ones.

## What Changed, Concretely

- **Color.** A CRT-phosphor teal-cyan primary color was chosen specifically to move away from generic-SaaS blue, paired with a warm off-white foreground against a near-black "anodized steel panel" background.
- **Status language.** A six-state operational vocabulary (OPERATIONAL / DEGRADED / WARNING / CRITICAL / OFFLINE / UNKNOWN) was introduced where every state pairs a distinct hue, fill density, border style, *and* icon — deliberately never color alone, so the product remains legible to a colorblind viewer or on a grayscale printout.
- **Shape language.** A "radius-contrast" rule: outer panels and cards keep a softer corner radius, while every interactive or status element (buttons, inputs, badges, chips) tightens to a sharper radius — soft containers visibly holding precise controls, read as an "operational instrument" without relying on any single color choice to sell that feeling.
- **Elevation.** Drop-shadowed cards were replaced app-wide with a flat fill bounded by a hairline border, so panels read as machined layers rather than floating the way a generic Bootstrap-style dashboard does.
- **Typography.** A three-typeface system: IBM Plex Sans Condensed for headings, the wordmark, and section labels; IBM Plex Mono — with tabular numerals — for every raw technical value (hashes, IPs, timestamps, scores); body text left untouched to avoid any risk to the existing dense data tables.
- **Iconography and mark.** An original, wholly geometric logo (a horizon line with two open "signal" nodes converging on one filled "detection" node) that literally depicts the tagline rather than just looking generically tactical, with no insignia, seal, shield, or existing company/military symbol of any kind.

## Where It Landed

The identity was applied first to the shared components that appear everywhere (the header, cards, buttons, inputs, badges) so it took effect consistently across every page from one set of edits, then rolled out page-by-page to the ten pages sharing that header/nav, and finally into every exported report format (PDF, CSV, Markdown), each of which now carries the platform name, a generation timestamp, and an Investigation ID. The result is documented with real, live screenshots throughout this submission rather than mockups.

[FIGURE: 15-login.png | The login screen — the mark, wordmark, tagline, and the subtle grid-and-horizon-line background introduced in the branding pass.]
