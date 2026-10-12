import type { InspectionSource, InspectionResult, Alignment } from "./types";

export type Cohort = "real_unmodified" | "real_perturbed" | "synthetic";
export const cohortLabels: Record<Cohort, string> = {
  real_unmodified: "真实采集 · 无软件扰动（声明）",
  real_perturbed: "真实采集 · 软件扰动（声明）",
  synthetic: "合成样本",
};
export interface EvaluationSummary {
  total: number;
  processed: number;
  not_run: number;
  detection_counts: Record<InspectionResult["status"], number>;
  inspection: {
    enabled: boolean;
    labeled: number;
    unlabeled: number;
    labeled_processed: number;
    assessed: number;
    unavailable_labeled: number;
    not_run_labeled: number;
    coverage: number | null;
    tp: number;
    tn: number;
    fp: number;
    fn: number;
    label_agreement: number | null;
    precision: number | null;
    recall: number | null;
    false_positive_rate: number | null;
    miss_rate: number | null;
  };
  rule: {
    labeled: number;
    unlabeled: number;
    assessed: number;
    abstained: number;
    not_run_labeled: number;
    coverage: number | null;
    label_agreement: number | null;
    correct: number;
    matrix: Record<string, Record<string, number>>;
  };
}
export interface EvaluationSample {
  sample_id: string;
  image_sha256: string;
  image_index: number;
  batch: string;
  cohort: Cohort;
  perturbation: string;
  defect_label: "unknown" | "normal" | "defect";
  cause_label: string;
  processed: boolean;
  detection_status: InspectionResult["status"] | null;
  is_ng: boolean | null;
  confidence: number | null;
  anomaly_score: number | null;
  alignment: Alignment | null;
  rule_prediction: string | null;
  inspection_mismatch: boolean;
  rule_mismatch: boolean;
}
export interface EvaluationReport {
  session: string;
  dataset_id: string;
  dataset_name: string;
  completed: boolean;
  fingerprint: string;
  report_sha256: string;
  results_sha256: string;
  inspection_source: InspectionSource;
  summary: EvaluationSummary;
  groups: { batch: string; cohort: Cohort; summary: EvaluationSummary }[];
  leakage: {
    baseline_duplicate_ids: string[];
    evaluation_duplicate_ids: string[];
    shared_batches: string[];
    shared_batch_keys: string[];
    unique_evaluation_images: number;
  };
  warnings: string[];
  samples: EvaluationSample[];
}
export interface ComparisonSample {
  sample_id: string;
  image_index: number;
  batch: string;
  cohort: Cohort;
  defect_label: string;
  cause_label: string;
  left_status: InspectionResult["status"];
  right_status: InspectionResult["status"];
  left_ng: boolean | null;
  right_ng: boolean | null;
  left_rule: string;
  right_rule: string;
  status_changed: boolean;
  verdict_changed: boolean | null;
  rule_changed: boolean;
}
export interface ComparisonReport {
  comparable: boolean;
  reasons: string[];
  left: EvaluationReport;
  right: EvaluationReport;
  paired: number;
  left_only: number;
  right_only: number;
  both_completed: boolean;
  both_ok: number;
  binary_enabled: boolean;
  verdict_changes: number;
  status_changes: number;
  rule_changes: number;
  paired_summaries: EvaluationSummary[] | null;
  samples: ComparisonSample[];
}
