// Shapes of the JSON artefacts in runs/<run-id>/ and generated/manifest.json, as served by `fluxora serve`.

export interface Rule {
  id: string;
  source: { file: string; ref: string };
  formula: string;
  rule: string;
  inputs: string[];
  output: string;
  confidence: "high" | "medium" | "low";
  status: "pending" | "approved" | "rejected";
}

export interface Approval {
  ruleId: string;
  decision: "approved" | "rejected";
  at: string;
}

export interface Unsupported {
  file: string;
  ref: string;
  construct: string;
  reason: string;
}

export interface Register {
  runId: string;
  createdAt: string;
  fixture: string;
  ruleTextModel: string;
  rules: Rule[];
  precedence: string[][];
  unsupported: Unsupported[];
  approvals: Approval[];
}

export interface FieldDiff {
  expected: unknown;
  actual: unknown;
}

export interface ParityCase {
  id: string;
  ruleIds: string[];
  description: string;
  oracle: string;
  inputs: Record<string, unknown>;
  expected: Record<string, unknown>;
  actual: Record<string, unknown>;
  diff: Record<string, FieldDiff>;
  implicatedRules: string[];
  pass: boolean;
}

export interface ParityRule {
  id: string;
  rule: string;
  casesTotal: number;
  casesFailed: number;
  status: string;
  oracle: string;
  failedCases: string[];
}

export interface Counts {
  passed: number;
  failed: number;
  total: number;
}

export interface Summary {
  result: "PASS" | "FAIL";
  cases: Counts;
  rules: Counts;
}

export interface SeededDefect {
  name: string;
  ruleId: string;
  file: string;
  before: string;
  after: string;
  description: string;
}

export interface Parity {
  runId: string;
  judgedAt: string;
  api: { project: string; url: string };
  referenceCases: { path: string; sha256Before: string; sha256After: string; unchanged: boolean };
  timings: Record<string, number>;
  summary: Summary;
  rules: ParityRule[];
  cases: ParityCase[];
  seededDefect?: SeededDefect | null;
  initial?: {
    summary: Summary;
    failedCases: string[];
    redRules: string[];
    rules: { id: string; status: string; failedCases: string[] }[];
    cases: ParityCase[];
  };
  repair?: { maxAttempts: number; attempts: number; fixed: string[]; unresolved: string[] };
  tamperGuard?: { file: string; sha256Before: string; sha256After: string; unchanged: boolean; message?: string };
}

export interface Attempt {
  attempt: number;
  ruleId: string;
  at: string;
  mode: "live" | "replay" | "none";
  source: string;
  provenance?: { provider?: string; model?: string; servedBy?: string };
  diff?: string;
  build?: string;
  judge?: { result: string; casesPassed: number; casesTotal: number; ruleStatus: string; newFailures: string[] };
  outcome: string;
  detail?: string;
}

export interface Repairs {
  runId: string;
  seededDefect: SeededDefect | null;
  maxAttempts: number;
  fixed: string[];
  unresolved: string[];
  attempts: Attempt[];
}

export interface Manifest {
  generatedFrom: { runId: string; fixture: string };
  ruleBodyModel: string;
  skipped: { id: string; status: string }[];
  files: { path: string; rules: string[] }[];
  note?: string;
}

export interface MigrationCheck {
  check: string;
  pass: boolean;
  detail: string;
}

export interface Migration {
  result: string;
  counts: { read: number; migrated: number; quarantined: number };
  checks: MigrationCheck[];
  quarantined: { row: number; record: string; claimId: string | null; reasons: string[] }[];
  defaulted: { record: string; column: string; value: unknown }[];
  source: { path: string; table: string; entitySet: string; sha256Before: string; sha256After?: string };
  target: { store: string; document: string; id: string; partitionKey: string; file: string; sha256?: string };
  replay: Replay | null;
}

export interface ReplayEntry {
  id: string;
  stored: string | null;
  migratedApp: string | null;
  errors: string[];
  firedRules: string[];
  detail?: string;
}

export interface Replay {
  replayedAt: string;
  asOf: string;
  compared: number;
  matched: number;
  mismatched: ReplayEntry[];
  noStoredStatus: ReplayEntry[];
  result: string;
}

export interface Evidence {
  runId: string;
  fixture: string;
  register: { rules: number; approved: number; rejected: number; pending: number; decisions: number; lastDecisionAt: string | null };
  unsupported: Unsupported[];
  oracle: Record<string, number>;
  parity: {
    result: string;
    cases: Counts;
    rules: Counts;
    judgedAt: string;
    seededDefect: SeededDefect | null;
    initial: Summary | null;
    initialRedRules: string[];
  } | null;
  repairs: { attempts: number; fixed: string[]; unresolved: string[]; modes: Record<string, number> } | null;
  tamperGuard: { unchanged: boolean; sha256Before: string; sha256After: string; message?: string } | null;
  timings: Record<string, number> | null;
  migration: Migration | null;
  dataNotes: string[];
}

export interface RunData {
  runId: string;
  rules: Register;
  parity: Parity | null;
  repairs: Repairs | null;
  manifest: Manifest | null;
  evidence: Evidence;
}
