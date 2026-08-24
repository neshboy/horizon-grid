// Mirrors backend/app/providers/base.py ProviderResult.to_dict() and
// backend/app/ai/schemas.py -- keep these in sync when either side changes.

export type ProviderStatus =
  | "ok"
  | "error"
  | "timeout"
  | "rate_limited"
  | "not_configured"
  | "unsupported_ioc"
  | "no_data"
  | "disabled";

export interface ProviderResult {
  provider_id: string;
  provider_name: string;
  category: string;
  status: ProviderStatus;
  ioc_value: string;
  ioc_type: string;
  data: Record<string, unknown>;
  source_url?: string | null;
  error_message?: string | null;
  latency_ms?: number | null;
  fetched_at: number;
  from_cache: boolean;
}

export interface ProviderSummary {
  provider_id: string;
  what_it_knows: string;
  reputation: string;
  detection_status: string;
  threat_level: "none" | "low" | "medium" | "high" | "critical" | string;
  confidence: "low" | "medium" | "high" | string;
  interesting_findings: string[];
  relationships: string[];
  unique_observations: string[];
  caveats?: string | null;
}

export interface MitreMapping {
  technique_id: string;
  technique_name: string;
  tactic: string;
  kill_chain_stage?: string | null;
  rationale: string;
  grounded: boolean;
}

export interface DetectionRule {
  format: string;
  title: string;
  rule: string;
}

export interface RiskAssessment {
  overall_risk_score: number;
  confidence_score: number;
  severity: string;
  reputation: string;
  malicious_probability: number;
  analyst_confidence: string;
}

export interface FinalAssessment {
  ioc_value: string;
  ioc_type: string;
  executive_summary: string;
  technical_summary: string;
  threat_assessment: string;
  supporting_evidence: string[];
  agreeing_providers: string[];
  disagreeing_providers: string[];
  relationships_summary: string;
  mitre_mappings: MitreMapping[];
  risk: RiskAssessment;
  detection_rules: DetectionRule[];
  recommended_actions: string[];
  investigation_priorities: string[];
  incident_response_recommendations: string[];
  final_verdict: string;
  verdict_rationale: string;
  /** Which AI backend/model actually produced this conclusion (Phase 20
   * traceability) -- both null whenever ai_outcome !== "success" (neither
   * the no-evidence short-circuit nor a genuine generation failure ever
   * invokes/identifies a backend). Use ai_outcome, not ai_backend's
   * truthiness, to tell those two apart -- they render very differently:
   * "skipped_no_evidence" is a correct, unremarkable decision; "failed" is
   * a real error worth flagging (see FinalAssessmentPanel.tsx). */
  ai_backend: string | null;
  ai_model: string | null;
  /** "success" | "failed" | "skipped_no_evidence" -- optional only because
   * older persisted assessments (pre-Phase-9-tracking) may not have it. */
  ai_outcome?: "success" | "failed" | "skipped_no_evidence" | null;
}

// Mirrors backend/app/core/runtime_config.py's _row_to_public_dict() -- the
// runtime-configurable AI/IOC provider store, distinct from the .env-driven
// config the Windows Setup Wizard also still writes (kept as the initial
// bootstrap; runtime changes made here take effect with no restart).
export interface RuntimeProviderConfig {
  provider_id: string;
  provider_name: string;
  kind: "ai" | "ioc";
  enabled: boolean;
  is_active: boolean;
  configured: boolean;
  model_id: string | null;
  extra_config: Record<string, unknown>;
  masked_credentials: Record<string, string>;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_test_message: string | null;
  updated_at: string | null;
  // IOC-provider-only fields (present on /runtime/ioc-providers responses)
  requires_key?: boolean;
  credential_fields?: string[];
  category?: string;
  supported_types?: string[];
}

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  actor_email: string | null;
  action: string;
  detail: string;
}

export interface AssessmentRecord {
  id: string;
  ai_backend: string;
  ai_model: string | null;
  is_primary: boolean;
  assessment: FinalAssessment;
  created_at: string;
}

export interface GraphNode {
  node_id: string;
  ioc_type: string;
  value: string;
  labels: string[];
}

export interface GraphEdge {
  source: string;
  target: string;
  relationship: string;
  confidence: number;
  provenance: string;
}

export interface CorrelationPayload {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface LookupSummary {
  id: string;
  ioc_value: string;
  ioc_type: string;
  status: "pending" | "running" | "completed" | "failed";
  final_verdict?: string | null;
  risk_score?: number | null;
  confidence_score?: number | null;
  created_at: string;
}

// --- Evidence / analysis (mirrors backend/app/models/evidence.py + app/ai/analysis_schemas.py) ---

export interface EvidenceItem {
  id: string;
  evidence_type: string;
  source_label: string;
  provider_id?: string | null;
  claim: string;
  interpretation?: string | null;
  confidence: number;
  related_ioc_type?: string | null;
  related_ioc_value?: string | null;
  source_url?: string | null;
  observed_at?: string | null;
  created_at: string;
}

export interface ReasonWithEvidence {
  reason: string;
  evidence_ids: string[];
}

export interface WhyMaliciousExplanation {
  verdict_restated: string;
  reasons: ReasonWithEvidence[];
  caveat?: string | null;
}

export interface WhatIsThisIOC {
  plain_language_summary: string;
  technical_explanation: string;
  evidence_ids: string[];
  confidence_narrative: string;
  related_infrastructure: string[];
}

export interface DisagreementSummary {
  agreement: string;
  conflict: string;
  missing_data: string;
  most_reliable_evidence: string;
  evidence_ids: string[];
}

export interface FalsePositiveAssessment {
  likely_false_positive: boolean;
  candidate_categories: string[];
  explanation: string;
  evidence_ids: string[];
}

export interface ChallengeVerdict {
  supporting_evidence: ReasonWithEvidence[];
  contradictory_evidence: ReasonWithEvidence[];
  missing_evidence: string[];
  alternative_explanation: string;
  final_confidence: "low" | "medium" | "high";
  final_confidence_rationale: string;
}

export interface NextAction {
  action: string;
  target_ioc_value?: string | null;
  target_ioc_type?: string | null;
  rationale: string;
  priority: "low" | "medium" | "high";
}

export interface SmartNextActions {
  actions: NextAction[];
}

export interface IntelligenceGap {
  gap: string;
  how_to_close: string;
}

export interface IntelligenceGaps {
  gaps: IntelligenceGap[];
}

export interface ScoreComponent {
  component: string;
  contribution: string;
  evidence_ids: string[];
}

export interface ScoreExplanation {
  components: ScoreComponent[];
  summary: string;
}

export interface CopilotAnswer {
  answer: string;
  evidence_ids: string[];
  suggested_follow_ups: string[];
}

export interface IOCComparisonNarrative {
  most_dangerous_ioc_value?: string | null;
  narrative: string;
  key_differences: string[];
}

export interface IOCComparisonRow {
  ioc_value: string;
  ioc_type: string;
  verdict: string;
  risk_score: number | null;
  confidence_score: number | null;
  asn: string[];
  malware_families: string[];
  threat_actors: string[];
  related_domains: string[];
  first_seen: string;
}

export interface IOCComparisonResponse {
  rows: IOCComparisonRow[];
  narrative: IOCComparisonNarrative;
}

// --- Hunting / detection (mirrors backend/app/ai/analysis_schemas.py) ---

export interface HuntingQuery {
  format: string;
  query: string;
  detects: string;
}

export interface HuntingExpansionTarget {
  related_ioc_value: string;
  related_ioc_type: string;
  rationale: string;
}

export interface HuntingPackage {
  exact_match_queries: HuntingQuery[];
  expansion_targets: HuntingExpansionTarget[];
  broader_queries: HuntingQuery[];
}

export interface DetectionRuleDraft {
  format: string;
  title: string;
  rule: string;
  detection_objective: string;
  data_source: string;
  logic_explanation: string;
  false_positive_considerations: string;
  severity: string;
  mitre_technique_ids: string[];
}

// --- Pivot ---

export interface PivotSuggestion {
  ioc_value: string;
  ioc_type: string;
  relationship: string;
  confidence: number;
  corroborating_providers: number;
  provenance: string;
  relevance: "high" | "medium" | "low";
}

// --- IOC Basket ---

export interface BasketItem {
  id: string;
  ioc_value: string;
  ioc_type: string;
  note?: string | null;
  latest_lookup_id?: string | null;
  created_at: string;
}

// --- Case management ---

export type CaseStatus = "open" | "investigating" | "contained" | "resolved" | "false_positive" | "closed";
export type CaseSeverity = "low" | "medium" | "high" | "critical";

export interface CaseSummary {
  id: string;
  title: string;
  severity: CaseSeverity;
  status: CaseStatus;
  tags: string[];
  created_at: string;
}

export interface CaseIOCEntry {
  id: string;
  ioc_value: string;
  ioc_type: string;
  lookup_id?: string | null;
  added_by: string;
  created_at: string;
}

export interface CaseNoteEntry {
  id: string;
  author_id: string;
  body: string;
  anchor_type?: string | null;
  anchor_ref?: string | null;
  created_at: string;
}

export interface CaseReportEntry {
  id: string;
  report_type: string;
  title: string;
  generated_by: string;
  created_at: string;
}

export interface CaseDetail {
  id: string;
  title: string;
  description?: string | null;
  analyst_id: string;
  severity: CaseSeverity;
  status: CaseStatus;
  tags: string[];
  created_at: string;
  updated_at: string;
  iocs: CaseIOCEntry[];
  notes: CaseNoteEntry[];
  reports: CaseReportEntry[];
}

// Mirrors backend/app/main.py's /network-info response.
export interface NetworkInfo {
  detected_lan_ip: string | null;
  frontend_port: number;
  backend_port: number;
}

// --- Admin / user management (mirrors backend/app/core/users.py,
// backend/app/api/routes/admin.py) ---

export type Role = "admin" | "analyst" | "viewer";

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string;
  role: Role;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface UserListResponse {
  items: User[];
  total: number;
  page: number;
  page_size: number;
}

export interface UserStats {
  total_users: number;
  active_users: number;
  disabled_users: number;
  by_role: Record<string, number>;
  recent_logins: { email: string; last_login_at: string }[];
}

export interface RolePermissions {
  role: Role;
  permissions: string[];
}

// --- Security Assessment Toolkit (mirrors backend/app/schemas/security_assessment.py) ---

export type Severity = "info" | "low" | "medium" | "high" | "critical";
export type SecurityAssessmentRunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export interface ToolProfile {
  tool_id: string;
  tool_name: string;
  profile_id: string;
  name: string;
  description: string;
  supported_types: string[];
}

export interface ToolHealth {
  tool_id: string;
  tool_name: string;
  available: boolean;
}

export interface SecurityAssessmentFinding {
  id: string;
  tool_id: string;
  finding_type: string;
  severity: Severity;
  title: string;
  description: string;
  target_detail: string | null;
  cve_ids: string[];
  evidence: Record<string, unknown>;
  created_at: string;
}

export interface SecurityAssessmentRun {
  id: string;
  lookup_id: string;
  target: string;
  tool_ids: string[];
  profile: string;
  status: SecurityAssessmentRunStatus;
  requested_by: string | null;
  authorization_confirmed_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  findings: SecurityAssessmentFinding[];
}

// --- Pentest Suite (mirrors backend/app/schemas/pentest.py) ---

export type PentestAssessmentStatus = "draft" | "active" | "paused" | "completed" | "cancelled" | "expired";
export type PentestProfile = "passive" | "low_impact" | "standard" | "comprehensive" | "custom";
export type PentestTargetStatus =
  | "pending"
  | "discovering"
  | "enumerating"
  | "assessing"
  | "completed"
  | "failed"
  | "out_of_scope";
export type PentestFindingConfidence = "confirmed" | "likely" | "potential" | "informational";
export type PentestFindingStatus = "open" | "validated" | "false_positive" | "remediated" | "accepted_risk";

export interface PentestScopeDefinition {
  cidrs?: string[];
  domains?: string[];
}

export interface PentestTarget {
  id: string;
  assessment_id: string;
  target_type: string;
  value: string;
  port: number | null;
  asset_label: string | null;
  environment: string | null;
  target_group: string | null;
  status: PentestTargetStatus;
  created_at: string;
}

export interface PentestFindingEvidenceEntry {
  captured_at: string;
  tool_id: string;
  data: Record<string, unknown>;
}

export interface PentestFinding {
  id: string;
  assessment_id: string;
  target_id: string;
  tool_id: string;
  finding_type: string;
  severity: Severity;
  confidence: PentestFindingConfidence;
  cvss_score: number | null;
  cve_ids: string[];
  title: string;
  description: string;
  remediation: string | null;
  status: PentestFindingStatus;
  evidence: PentestFindingEvidenceEntry[];
  created_at: string;
}

export interface PentestAssessment {
  id: string;
  name: string;
  description: string | null;
  status: PentestAssessmentStatus;
  profile: PentestProfile;
  scope_definition: PentestScopeDefinition;
  max_runtime_minutes: number;
  max_requests: number;
  emergency_stopped: boolean;
  started_at: string | null;
  expires_at: string | null;
  created_by: string;
  created_at: string;
  targets: PentestTarget[];
  findings: PentestFinding[];
}

export type PentestValidationChecks = Record<string, string>;

export interface PentestFindingExplanation {
  finding_id: string;
  plain_language_summary: string;
  why_it_matters: string;
  likely_false_positive_reasons: string | null;
}

export interface PentestAssessmentSummaryReport {
  executive_summary: string;
  technical_summary: string;
  top_priorities: string[];
  overall_risk_narrative: string;
}

// --- Pentest Suite: gated real-exploit validation (Metasploit) --
// mirrors backend/app/api/routes/pentest_exploit.py. Deliberately separate
// from the automatic DISCOVER/ENUMERATE/ASSESS pipeline above -- every
// action here is a manually-selected module the operator explicitly ran.

export type PentestExploitMode = "check" | "exploit";
export type PentestExploitStatus = "pending" | "running" | "succeeded" | "session_opened" | "failed" | "error";

export interface PentestExploitModuleCandidate {
  fullname: string;
  name: string;
  module_type: string;
  rank: string;
  disclosure_date: string | null;
  matched_cve: string;
}

export interface PentestExploitModuleOptions {
  fullname: string;
  description: string | null;
  rank: string | null;
  references: [string, string][];
  options: Record<string, { type?: string; required?: boolean; advanced?: boolean; desc?: string; default?: unknown }>;
}

export interface PentestExploitAttempt {
  id: string;
  assessment_id: string;
  finding_id: string;
  target_id: string;
  module_fullname: string;
  module_options: Record<string, unknown>;
  mode: PentestExploitMode;
  status: PentestExploitStatus;
  result_transcript: string;
  session_id: number | null;
  requested_by: string;
  created_at: string;
}

// --- Executive Dashboard (mirrors backend GET /dashboard/kpis and
// GET /dashboard/executive-summary) ---

export interface DashboardKpis {
  active_investigations: number;
  critical_high_risk_iocs: number;
  open_cases: number;
  open_critical_cases: number;
  avg_threat_score: number;
  provider_health_percentage: number;
  /** Null when there's no AI-assessment data in the last 30 days -- a real
   * "no rate to report" state. Never coerce to 0%. */
  ai_success_rate: number | null;
}

export type ProviderHealthStatus = "healthy" | "degraded" | "down" | "unknown";

// Mirrors backend GET /providers/health's per-window object. "unknown" means
// the provider was never exercised in that window -- distinct from "down",
// and success_rate/avg_latency_ms are null (never 0) when there's no data.
export interface ProviderHealthWindow {
  status: ProviderHealthStatus;
  success_rate: number | null;
  avg_latency_ms: number | null;
  consecutive_failures: number;
  rate_limited_count: number;
}

export interface ProviderHealthEntry {
  provider_id: string;
  provider_name: string;
  category: string;
  configured: boolean;
  requires_key: boolean;
  supported_types: string[];
  "1h": ProviderHealthWindow;
  "24h": ProviderHealthWindow;
  "7d": ProviderHealthWindow;
  "30d": ProviderHealthWindow;
}

// Mirrors backend GET /dashboard/executive-summary. `source` is surfaced in
// the UI on purpose -- an analyst should always know whether the narrative
// was AI-generated or a template fallback (e.g. no AI backend configured).
export interface ExecutiveSummary {
  summary: string;
  source: "ai" | "template_fallback";
  kpis: DashboardKpis;
}
