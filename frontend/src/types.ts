// Mirrors backend/app/extraction/schema.py (ExtractedSyllabus) and api/schemas.py.

export type Strength = "high" | "medium" | "low";

export interface ScheduledAssessment {
  name: string;
  weight_pct: number | null;
  due_text_raw: string | null;
  due_date: string | null;
  due_week: number | null;
}

export interface WeekRow {
  week_no: number;
  topics: string[];
  readings: string[];
  assessments: ScheduledAssessment[];
  clo_numbers: number[];
  clo_text_raw: string | null;
}

export interface Program {
  name: string;
  plos: { number: number; text: string }[];
  clo_plo: { clo: number; plo: number; strength: Strength }[];
  abet_addressed: number[];
}

export interface SyllabusRecord {
  schema_version: string;
  course: {
    code: string | null;
    title: string | null;
    credit_hours: number | null;
    prerequisites: string | null;
    description: string | null;
    additional_info: string | null;
    methods_of_instruction: string | null;
  };
  offering: {
    term: string | null;
    term_raw: string | null;
    class_timing_raw: string | null;
    meetings: { days: string[]; time_text: string | null }[];
    instructor_name: string | null;
    instructor_contact: string | null;
  };
  resources: { textbooks: string[]; other: string[]; web: string[] };
  clos: { number: number; text: string }[];
  weights: { name: string; weight_pct: number | null }[];
  clo_matrix: { assessment: string; clo_numbers: number[] }[];
  weekly: WeekRow[];
  programs: Program[];
  raw_sections: Record<string, string>;
  notes: { where: string; message: string }[];
  sources: Record<string, SourceRef>;
}

/** Where a value was read from in the uploaded file (plan 0.6). */
export interface SourceRef {
  page: number | null;
  table: number | null;
  row: number | null;
  raw_text: string | null;
}

export interface Flag {
  id: number;
  rule_id: string;
  rule_title: string;
  severity: "error" | "warning" | "info";
  message: string;
  evidence_refs: string[];
  choices: { label: string }[];
  status: "open" | "resolved" | "cleared";
  resolution: string | null;
  resolution_note: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
}

export type Status = "extracted" | "in_review" | "locked" | "superseded";

export interface VersionSummary {
  id: number;
  status: Status;
  origin: string;
  course_code: string | null;
  course_title: string | null;
  term: string | null;
  version_no: number | null;
  source_filename: string | null;
  open_blocking: number;
  created_at: string;
  updated_at: string;
  locked_at: string | null;
  parent_version_id: number | null;
}

export interface VersionDetail extends VersionSummary {
  record: SyllabusRecord;
  flags: Flag[];
  edit_count: number;
  can_lock: boolean;
  previous: { id: number; term: string | null; version_no: number | null; matching_settled_flags: number } | null;
}

export interface EditOp {
  op: "replace" | "add" | "remove";
  path: string;
  value?: unknown;
}

export interface EditEntry {
  id: number;
  op: string;
  field_path: string;
  old_value: unknown;
  new_value: unknown;
  note: string | null;
  edited_by: string;
  at: string;
}

export interface Coverage {
  clos: { number: number; text: string; weight_pct: number; assessments: string[] }[];
  weight_note: string;
  programs: {
    name: string;
    plos: { number: number; text: string; covered: boolean; addressed: boolean }[];
    grid: Record<string, Record<string, Strength>>;
    uncovered_plos: number[];
  }[];
}

// ---- Phase 2: Draft Studio ------------------------------------------------
export type ItemStatus = "suggested" | "under_review" | "approved" | "rejected" | "needs_review";

export interface QualityScore {
  check: string;
  label: string;
  outcome: "pass" | "warn" | "fail" | "skipped";
  score: number | null;
  detail: string;
  hard: boolean;
}

export interface DraftItem {
  id: number;
  course_version_id: number;
  type: string;
  type_label: string;
  status: ItemStatus;
  clo_numbers: number[];
  week_no: number | null;
  bloom_level: string | null;
  difficulty: string | null;
  body: Record<string, any>;
  answer_key: Record<string, any> | null;
  feedback: Record<string, any> | null;
  grounded: boolean;
  model: string;
  prompt_version: string;
  parent_item_id: number | null;
  created_at: string;
  updated_at: string;
  approved_by: string | null;
  approved_at: string | null;
  scores: QualityScore[];
  can_approve: boolean;
  revision_count: number;
  events: { action: string; notes: string | null; by: string; at: string }[];
  shared: boolean;
}

export interface DraftType {
  type: string;
  label: string;
  question: boolean;
  has_answer_key: boolean;
}

export interface DraftContext {
  status: Status;
  can_generate: boolean;
  clos: { number: number; text: string; bloom_level: string | null; skills: boolean }[];
  weeks: { week_no: number; topics: string[] }[];
  bloom_levels: string[];
}

export interface GenerateRequest {
  item_type: string;
  clo_numbers: number[];
  weeks: number[];
  count: number;
  difficulty?: string | null;
  bloom_level?: string | null;
  notes?: string | null;
}

export interface Material {
  id: number;
  title: string;
  filename: string;
  kind: "slides" | "notes" | "past_exam" | "textbook" | "other";
  week_no: number | null;
  licensed: boolean;
  status: "pending" | "indexed" | "blocked" | "failed";
  error: string | null;
  chunk_count: number;
  embed_model: string | null;
  created_at: string;
  indexed_at: string | null;
}

export interface Job {
  id: number;
  kind: string;
  status: "queued" | "running" | "done" | "failed";
  progress: number;
  message: string | null;
  result: Record<string, any> | null;
  error: string | null;
  error_status: number | null;
  created_at: string;
  finished_at: string | null;
}
