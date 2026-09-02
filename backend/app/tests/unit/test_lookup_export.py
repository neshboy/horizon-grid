"""Unit tests for app.api.routes.lookup's server-rendered export formats.

Regression tests for a real gap found during a release audit: the frontend's
"Export PDF" and "Export CSV" buttons called POST /api/v1/lookup/{id}/export,
which did not exist anywhere in the backend -- every click 404'd. (JSON and
Markdown export are unaffected -- ExportMenu.tsx builds those entirely
client-side from data already in the browser, with no backend dependency.)

Uses lightweight fakes rather than a real DB-backed IOCLookup, since
_render_csv()/_render_pdf() only ever read plain attributes off the object
passed in -- a real ORM round-trip would test SQLAlchemy, not this code.

Also covers two later-found security regressions in the same export path
(BUG-022 CSV/formula injection, BUG-023 PDF markup injection/crash -- see
BUG_TRIAGE.md):
  - test_render_csv_neutralizes_formula_injection_payload
  - test_render_pdf_does_not_crash_on_malformed_markup_ioc_value
  - test_render_pdf_renders_wellformed_markup_as_literal_text_not_formatting
"""
import csv
import io
from types import SimpleNamespace

from app.api.routes.lookup import _csv_safe, _pdf_esc, _render_csv, _render_pdf
from app.models.lookup import Verdict


def _fake_provider_result(**overrides):
    defaults = dict(
        provider_id="nvd",
        provider_name="NIST NVD",
        category="vulnerability",
        status="ok",
        source_url="https://nvd.nist.gov/vuln/detail/CVE-2021-44228",
        error_message=None,
        latency_ms=250,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_lookup(final_assessment=None, provider_results=None):
    import datetime

    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000000",
        ioc_value="CVE-2021-44228",
        ioc_type="cve",
        final_verdict=Verdict.MALICIOUS,
        risk_score=90.0,
        confidence_score=95.0,
        created_at=datetime.datetime(2026, 8, 14, tzinfo=datetime.timezone.utc),
        provider_results=provider_results or [_fake_provider_result()],
        final_assessment=final_assessment
        or {
            "final_verdict": "malicious",
            "risk": {"overall_risk_score": 90.0, "confidence_score": 95.0},
            "executive_summary": "Critical remote code execution vulnerability.",
            "technical_summary": "Log4Shell.",
            "threat_assessment": "Actively exploited in the wild.",
            "verdict_rationale": "CVSS 10.0, confirmed exploited.",
            "supporting_evidence": ["NVD confirms CVSS 10.0 CRITICAL."],
            "mitre_mappings": [
                {"technique_id": "T1190", "technique_name": "Exploit Public-Facing Application", "tactic": "Initial Access", "rationale": "RCE via crafted input."}
            ],
            "recommended_actions": ["Patch to Log4j 2.17.1 or later."],
            "investigation_priorities": ["Check for indicators of compromise."],
            "incident_response_recommendations": ["Isolate affected hosts."],
            "detection_rules": [{"title": "Log4Shell JNDI", "format": "sigma", "rule": "detection:\n  selection:\n    message: '${jndi:'"}],
        },
    )


def test_render_csv_includes_metadata_and_provider_rows():
    lookup = _fake_lookup()
    csv_text = _render_csv(lookup)

    assert "CVE-2021-44228" in csv_text
    assert "final_verdict" in csv_text
    assert "malicious" in csv_text
    assert "nvd" in csv_text
    assert "NIST NVD" in csv_text


def test_render_csv_includes_platform_and_investigation_id():
    """Regression test for the branding pass: every export must be
    traceable back to which platform generated it and which investigation
    it came from, per the branding brief's own "every report should
    contain HORIZON GRID / Investigation ID" requirement."""
    lookup = _fake_lookup()
    csv_text = _render_csv(lookup)
    assert "platform,HORIZON GRID" in csv_text
    assert f"investigation_id,{lookup.id}" in csv_text


def test_render_csv_handles_no_provider_results():
    lookup = _fake_lookup(provider_results=[])
    csv_text = _render_csv(lookup)
    assert "CVE-2021-44228" in csv_text  # metadata section still renders


def test_render_pdf_produces_a_real_pdf():
    lookup = _fake_lookup()
    pdf_bytes = _render_pdf(lookup)

    assert pdf_bytes.startswith(b"%PDF"), "output must be a genuine PDF, not a stub/placeholder"
    assert len(pdf_bytes) > 500


def test_render_pdf_handles_missing_final_assessment_gracefully():
    """An investigation that hasn't finished yet (or failed before reaching
    a final assessment) must still produce a valid, non-crashing PDF -- not
    a 500 from a None.get() somewhere."""
    lookup = _fake_lookup(final_assessment=None)
    pdf_bytes = _render_pdf(lookup)

    assert pdf_bytes.startswith(b"%PDF")


# --- BUG-022: CSV/formula injection (CWE-1236) -------------------------------

FORMULA_PAYLOAD = "=1+1+cmd|calc!A1"


def test_csv_safe_prefixes_formula_trigger_chars_with_a_leading_apostrophe():
    """Direct unit test of the neutralization primitive itself: any string
    starting with '=', '+', '-', or '@' -- the four characters Excel/
    LibreOffice will interpret as the start of a live formula -- must come
    back with a literal leading apostrophe. Non-string / non-triggering
    values must pass through unchanged (numeric/enum columns are never
    attacker-controlled free text, and a stray apostrophe would corrupt
    them)."""
    for trigger in ("=", "+", "-", "@"):
        payload = f"{trigger}1+1+cmd|calc!A1"
        assert _csv_safe(payload) == "'" + payload

    assert _csv_safe("benign-value") == "benign-value"
    assert _csv_safe(42) == 42
    assert _csv_safe(None) is None


def test_render_csv_neutralizes_formula_injection_payload_in_ioc_value():
    """Regression test for BUG-022: an analyst-supplied free-text IOC value
    (malware_family/threat_actor/campaign IOC types accept arbitrary strings
    via ioc_type_hint) of '=1+1+cmd|calc!A1' used to be written verbatim into
    the CSV cell -- a classic CSV/formula-injection payload that Excel/
    LibreOffice execute as a live formula on open. After the fix, the cell's
    actual text must start with a literal apostrophe, and parsing the CSV
    back with the stdlib csv module (i.e. simulating how a spreadsheet app
    would read the file) must show the cell's raw text is no longer a bare
    formula string."""
    lookup = _fake_lookup()
    lookup.ioc_value = FORMULA_PAYLOAD
    csv_text = _render_csv(lookup)

    rows = list(csv.reader(io.StringIO(csv_text)))
    ioc_row = next(r for r in rows if r and r[0] == "ioc_value")
    cell = ioc_row[1]

    assert cell.startswith("'"), "cell must be neutralized with a leading apostrophe"
    assert cell == "'" + FORMULA_PAYLOAD
    # The literal, unescaped payload (what a formula-interpreting reader
    # would need to see at the very start of the cell to execute it) must
    # never be the raw cell value.
    assert cell != FORMULA_PAYLOAD


def test_render_csv_neutralizes_formula_injection_in_provider_fields():
    """BUG-022's fix must cover every free-text-capable CSV cell, not just
    ioc_value -- provider_name, source_url, and error_message are all
    plausible injection vectors too (see BUG_TRIAGE.md's fix description)."""
    lookup = _fake_lookup(
        provider_results=[
            _fake_provider_result(
                provider_name="@SUM(1+1)*cmd|' /C calc'!A0",
                source_url="=HYPERLINK(\"http://evil.test\")",
                error_message="-2+3+cmd|calc!A1",
            )
        ]
    )
    csv_text = _render_csv(lookup)
    rows = list(csv.reader(io.StringIO(csv_text)))
    provider_row = rows[-1]
    provider_name, source_url, error_message = provider_row[1], provider_row[4], provider_row[5]

    assert provider_name.startswith("'")
    assert source_url.startswith("'")
    assert error_message.startswith("'")


# --- BUG-023: PDF markup injection/crash -------------------------------------

MALFORMED_MARKUP_PAYLOAD = "<b>INJECTED</b> title & unclosed <tag AAAA"
WELLFORMED_INJECTION_PAYLOAD = '<font color="red" size="40">FAKE-VERDICT-INJECTED</font>'


def test_pdf_esc_escapes_markup_metacharacters():
    """Direct unit test of the escaping primitive: '<', '>', '&' must never
    reach reportlab's Paragraph() unescaped, since Paragraph parses its input
    as a small XML/HTML-like markup dialect rather than literal text."""
    assert _pdf_esc(MALFORMED_MARKUP_PAYLOAD) == "&lt;b&gt;INJECTED&lt;/b&gt; title &amp; unclosed &lt;tag AAAA"
    assert _pdf_esc(None) == ""
    assert _pdf_esc(42) == "42"


def test_render_pdf_does_not_crash_on_malformed_markup_ioc_value():
    """Regression test for BUG-023(a): an IOC value containing an unclosed/
    malformed tag used to make reportlab.platypus.paraparser raise an
    uncaught ValueError, producing a persistent HTTP 500 for that lookup's
    PDF export forever. After escaping, '<'/'>' can never reach the parser as
    tag delimiters, so this must now render a real, valid PDF."""
    lookup = _fake_lookup()
    lookup.ioc_value = MALFORMED_MARKUP_PAYLOAD

    pdf_bytes = _render_pdf(lookup)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


def test_render_pdf_does_not_crash_on_malformed_markup_in_ai_text_fields():
    """Same crash mode as above, but via an AI-generated FinalAssessment
    field (executive_summary) rather than the IOC value itself -- the
    fix must cover every interpolation site, not just the title line."""
    lookup = _fake_lookup(
        final_assessment={
            "final_verdict": "malicious",
            "risk": {"overall_risk_score": 90.0, "confidence_score": 95.0},
            "executive_summary": MALFORMED_MARKUP_PAYLOAD,
            "technical_summary": "",
            "threat_assessment": "",
            "verdict_rationale": "",
            "supporting_evidence": [MALFORMED_MARKUP_PAYLOAD],
            "mitre_mappings": [],
            "recommended_actions": [],
            "investigation_priorities": [],
            "incident_response_recommendations": [],
            "detection_rules": [],
        }
    )

    pdf_bytes = _render_pdf(lookup)

    assert pdf_bytes.startswith(b"%PDF")


def test_render_pdf_renders_wellformed_markup_as_literal_text_not_formatting():
    """Regression test for BUG-023(b): a well-formed tag like
    '<font color="red" size="40">FAKE-VERDICT-INJECTED</font>' used to be
    accepted by reportlab as real markup and rendered as actual red, size-40
    formatting -- letting a free-text IOC value or AI-generated field inject
    spoofed content into an otherwise official-looking exported report.

    The full generated PDF's content stream is FlateDecode-compressed by
    reportlab (confirmed: raw text is not byte-searchable in the output), so
    this asserts the actual mechanism the fix relies on directly: feeding
    _pdf_esc()'s output (exactly what _render_pdf() now does at every
    interpolation site) into a real reportlab Paragraph and reading back
    .getPlainText(). If the payload were still live markup, getPlainText()
    would strip the <font> tag and return only 'FAKE-VERDICT-INJECTED'. With
    the fix, the escaped '&lt;'/'&gt;' entities decode back to literal '<'/
    '>' characters for on-page display, so the tag text itself is rendered
    as visible characters, and getPlainText() round-trips the exact original
    string.
    """
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph

    styles = getSampleStyleSheet()

    live_markup = Paragraph(WELLFORMED_INJECTION_PAYLOAD, styles["BodyText"])
    assert live_markup.getPlainText() == "FAKE-VERDICT-INJECTED", (
        "sanity check: unescaped, reportlab really does apply this as live formatting"
    )

    escaped = Paragraph(_pdf_esc(WELLFORMED_INJECTION_PAYLOAD), styles["BodyText"])
    assert escaped.getPlainText() == WELLFORMED_INJECTION_PAYLOAD, (
        "escaped text must round-trip byte-for-byte as literal visible text, "
        "proving the tag was never applied as live formatting"
    )

    # And the full pipeline (this exact payload as an AI-generated field)
    # must still produce a valid, non-crashing PDF.
    lookup = _fake_lookup(
        final_assessment={
            "final_verdict": "malicious",
            "risk": {"overall_risk_score": 90.0, "confidence_score": 95.0},
            "executive_summary": WELLFORMED_INJECTION_PAYLOAD,
            "technical_summary": "",
            "threat_assessment": "",
            "verdict_rationale": "",
            "supporting_evidence": [],
            "mitre_mappings": [],
            "recommended_actions": [],
            "investigation_priorities": [],
            "incident_response_recommendations": [],
            "detection_rules": [],
        }
    )
    pdf_bytes = _render_pdf(lookup)
    assert pdf_bytes.startswith(b"%PDF")


# --- Real bug found live during overnight QA: hardcoded section titles
# (e.g. "MITRE ATT&CK Mappings") were never passed through _pdf_esc() the
# way every dynamic value in this file already is -- the literal '&'
# rendered corrupted as "MITRE ATT&CK; Mappings" in every PDF export that
# included MITRE mappings, since ReportLab's Paragraph() parses its input
# as mini-XML and a bare '&' isn't a valid entity start. Reproduced live
# against the real reportlab install, and directly against the real
# generated PDF text (byte-identical whether downloaded via the API or the
# real browser's ExportMenu). ---


def test_render_pdf_escapes_the_mitre_section_title_correctly(monkeypatch):
    from reportlab.platypus import Paragraph as _real_paragraph

    seen_titles = []

    def _recording_paragraph(text, *args, **kwargs):
        seen_titles.append(text)
        return _real_paragraph(text, *args, **kwargs)

    monkeypatch.setattr("reportlab.platypus.Paragraph", _recording_paragraph)

    lookup = _fake_lookup()  # default fixture already has one real mitre_mappings entry
    pdf_bytes = _render_pdf(lookup)

    assert pdf_bytes.startswith(b"%PDF")
    assert "MITRE ATT&amp;CK Mappings" in seen_titles, (
        "the section title must be escaped ('&' -> '&amp;') before reaching Paragraph(), "
        "the same way every dynamic value in this file already is"
    )
    assert "MITRE ATT&CK Mappings" not in seen_titles, "the raw, unescaped title must never reach Paragraph()"
