export type Quality = Record<string, number>;
export interface InspectionProducer {
  name: string;
  version: string;
  provenance: "upstream" | "synthetic_fixture";
  score_semantics: "decision_confidence" | "anomaly_score";
  decision_threshold?: number | null;
}
export interface InspectionSource {
  kind: "reference_residual_demo" | "external_results" | "local_visual";
  provenance: "upstream" | "synthetic_fixture";
  result_id?: string;
  model_id?: string;
  producer?: InspectionProducer;
}
export interface InspectionResult {
  sample_id: string;
  status: "ok" | "missing" | "error" | "timeout";
  detected: boolean | null;
  confidence: number | null;
  anomaly_score?: number | null;
  alignment?: Alignment | null;
  is_ng: boolean | null;
  defect_types: string[];
  error: string;
}
export interface Alignment {
  status: "passed" | "disabled" | "rejected";
  angle_deg?: number | null;
  shift_x?: number | null;
  shift_y?: number | null;
  scale?: number | null;
  inliers: number;
  inlier_ratio?: number | null;
  reprojection_error?: number | null;
  coverage?: number | null;
  error: string;
}
export interface Detection {
  status: InspectionResult["status"];
  confidence: number | null;
  is_ng: boolean | null;
  metadata: { result?: InspectionResult; elapsed_ms?: number };
}
export interface DetectionAvailability {
  total: number;
  valid: number;
  unavailable: number;
  ready: boolean;
}
export const inspectionStatuses = {
  ok: "成功",
  missing: "缺失",
  error: "失败",
  timeout: "超时",
};
export interface DatasetSample {
  id: string;
  batch: string;
  split: "baseline" | "evaluation";
  origin: "real" | "synthetic";
  perturbation: string;
  captured_at: string;
  conditions: Record<string, string>;
  label: {
    defect: "unknown" | "normal" | "defect";
    cause: string;
    note: string;
  };
  dataset_id?: string;
  lineage?: {
    kind: string;
    source_id: string;
    sample_id: string;
    batch_key: string;
  };
}
export interface DatasetSummary {
  id: string;
  name: string;
  description: string;
  baseline_count: number;
  evaluation_count: number;
  batches: string[];
  origins: string[];
  labeled_count: number;
  perturbed_count: number;
  error?: string;
}
export interface DatasetManifest {
  name: string;
  description: string;
  samples: DatasetSample[];
}
export const defectLabels = {
  unknown: "未标注",
  normal: "正常",
  defect: "缺陷",
};
export interface Report {
  drift_detected: boolean;
  drift_type: string;
  evidence: string[];
  metrics: {
    image_quality: Quality;
    image_drift: { changes: Quality; registration?: Quality };
    consistency: Record<string, number | null>;
  };
}
export interface Frame {
  alert: Alert;
  detection: Detection;
  inspection_source: InspectionSource;
  detection_availability: DetectionAvailability;
  sample?: DatasetSample;
  frame: number;
  created: number;
  synthetic: boolean;
  injected: boolean;
  scenario: string;
  warmup: boolean;
  window_count: number;
  vision_ms: number;
  rule_report: Report;
}
export interface Baseline {
  quality_gate?: {
    status: "passed";
    valid_samples: number;
    rejected_samples: number;
  };
  generation: number;
  sample_count: number;
  created: number;
  source: string;
  image_quality: Quality;
  quality_samples: Quality[];
  operator_note: string;
}
export interface ModelPolicy {
  profile: string;
  keep_alive_minutes: number;
  timeout_seconds: number;
  autostart: boolean;
  auto_restart: boolean;
}
export interface State {
  maintenance_busy?: boolean;
  vision_management_error: string;
  history_token: string;
  event_revision: number;
  vision_runtime: {
    status: "disabled" | "loading" | "ready" | "processing" | "failed";
    model_id?: string;
    mode?: "raw" | "aligned";
    timeout_seconds?: number;
    pending: boolean;
    last_ms?: number | null;
    error: string;
  };
  acquisition: {
    preview: CapturePreview | null;
    error: string;
    revision: number;
  };
  alert: Alert;
  baseline_attempt: BaselineAttempt | null;
  inspection_source: InspectionSource;
  replay: {
    dataset_id: string;
    name: string;
    position: number;
    total: number;
    completed: boolean;
    fingerprint: string;
  } | null;
  session: string;
  source: string;
  running: boolean;
  scenario: string;
  intensity: number;
  frame_count: number;
  baseline_generation: number;
  baseline: Baseline | null;
  latest: Frame | null;
  history: Frame[];
  capture_error: string;
  model: {
    name: string;
    endpoint: string;
    executable: string;
    runtime_plan: RuntimePlan;
    connected: boolean;
    checked_at: number | null;
    details: {
      family?: string;
      parameter_size?: string;
      quantization_level?: string;
      weight_sha256?: string;
      runtime_version?: string;
    };
    pending: boolean;
    error: string;
    review_error: string;
    stale: boolean;
    health_error: string;
    log_error: string;
    resident_checked_at: number | null;
    operation: string | null;
    tasks: {
      id: string;
      action: string;
      target: string;
      status: string;
      stage: string;
      created: number;
      finished: number | null;
      error: string;
    }[];
    task_error: string;
    catalog: {
      name: string;
      title: string;
      size_bytes: number;
      file_status: string;
      checked_at: number | null;
      selected: boolean;
      revision: string;
      source: string;
      license: string;
      quantization: string;
      purpose: string;
    }[];
    fault: {
      code: string;
      message: string;
      remedy: string;
      impact: string;
      detail: string;
    } | null;
    progress: {
      phase: string;
      completed_bytes?: number;
      total_bytes?: number;
    } | null;
    policy: ModelPolicy;
    policy_presets: Record<
      string,
      { keep_alive_minutes: number; timeout_seconds: number }
    >;
    recovery: { message: string; attempts_in_window: number };
    validation: {
      id: string;
      name: string;
      created: number;
      status: string;
      scope: string;
      details: Record<string, unknown>;
    } | null;
    previous_name: string | null;
    owned: boolean;
    pid: number | null;
    config_path: string;
    health_interval_seconds: number;
    loaded: {
      name: string;
      size: number | null;
      size_vram: number | null;
      context_length: number | null;
      expires_at: string;
    }[];
    resources: {
      memory_total_bytes?: number | null;
      memory_available_bytes?: number | null;
      swap_used_bytes?: number | null;
      disk_free_bytes?: number | null;
      platform?: string;
      architecture?: string;
    };
    resources_checked_at: number | null;
    deployment: {
      ready: boolean;
      weight_verified: boolean;
      expected_weight_sha256: string;
      runtime_cli: string | null;
      runtime_error: string;
      weight_path: string;
      checked_at: number;
      runtime_plan: RuntimePlan;
    } | null;
  };
}
export interface RuntimePlan {
  system: string;
  architecture: string;
  label: string;
  start_supported: boolean;
  prepare_supported: boolean;
  source: "project_pinned" | "system" | "explicit";
  candidate: string | null;
  pinned_version: string | null;
  minimum_version: string;
  install_url: string | null;
  install_commands: string[];
  integrity: string;
  guidance: string;
}
export interface CapturePreview {
  token: string;
  created: string;
  captured_timestamp: number;
  remaining_seconds: number;
  source: string;
  session: string;
  generation: number;
  image_quality: Quality;
  quality_reasons: string[];
  usable_for_baseline: boolean;
  source_properties: Record<string, number | null>;
}
export interface CapturedSample extends DatasetSample {
  sha256: string;
  capture_token: string;
  source: string;
  source_properties: Record<string, number | null>;
  image_quality: Quality;
  quality_reasons: string[];
}
export interface CaptureBatch {
  id: string;
  name: string;
  description: string;
  created: string;
  samples: CapturedSample[];
}
export interface CaptureBatchSummary {
  id: string;
  name: string;
  sample_count: number;
  baseline_count: number;
  evaluation_count: number;
  duplicate_images: number;
  error?: string;
}
export const qualityReasons: Record<string, string> = {
  underexposure: "过暗",
  overexposure: "过曝",
  no_texture: "缺少纹理",
  non_finite_metrics: "指标无效",
};
export interface Assessment {
  outcome: string;
  note: string;
  incident_id: number;
  created?: number;
}
export interface Incident {
  trigger: string;
  lifecycle: IncidentLifecycle;
  id: number;
  created: number;
  frame: number;
  source: string;
  injected: boolean;
  drift_type: string;
  baseline_generation: number;
  assessment?: Assessment;
}
export interface EvidenceEvent<T> {
  id: number;
  kind: string;
  created: number;
  payload: T;
}
export interface IncidentPayload {
  detection?: Detection;
  inspection_source?: InspectionSource;
  detection_availability?: DetectionAvailability;
  sample?: DatasetSample;
  frame: number;
  source: string;
  synthetic: boolean;
  injected: boolean;
  baseline_generation: number;
  rule_report: Report;
  images: Record<string, string | null>;
  snapshot: {
    warmup: boolean;
    baseline: { image_quality: Quality };
    current_metrics: { image_quality: Quality };
  };
}
export interface Review {
  analysis: {
    drift_type: string;
    root_cause: string;
    alternative_causes: string[];
    verification_steps: string[];
    evidence: string[];
    recommendations: string[];
  };
  evidence_warnings: string[];
  raw_response: string;
}
export interface Bundle {
  updates: EvidenceEvent<{
    frame: number;
    baseline_generation: number;
    rule_report: Report;
    detection: Detection;
  }>[];
  lifecycle: IncidentLifecycle;
  lifecycle_events: EvidenceEvent<{
    reason: string;
    frame: number;
    baseline_generation: number;
  }>[];
  event: EvidenceEvent<IncidentPayload>;
  assessments: EvidenceEvent<Assessment>[];
  reviews: EvidenceEvent<Review>[];
  errors: EvidenceEvent<{ error: string }>[];
}
export interface Alert {
  state:
    | "warming"
    | "active"
    | "blocked"
    | "recovering"
    | "recovered"
    | "clear"
    | "unavailable";
  observation: "unavailable" | "drift" | "clear" | "insufficient";
  active: boolean;
  recovery_samples: number;
  recovery_streak: number;
  abnormal_streak: number;
  episode: {
    number: number;
    incident_id: number | null;
    baseline_generation: number;
    started_frame: number;
    last_abnormal_frame: number;
    ended_frame: number | null;
    drift_types: string[];
    unavailable_statuses: string[];
  } | null;
}
export interface BaselineAttempt {
  created: number;
  status: "passed" | "rejected";
  requested_samples: number;
  valid_samples: number;
  error: string;
  retained_generation: number | null;
  rejected_samples: {
    index: number;
    reasons: string[];
    image_quality: Quality;
  }[];
}
export interface IncidentLifecycle {
  state: "active" | "recovered" | "closed" | "unresolved" | "bookmark";
  reason?: string;
  frame?: number;
  created?: number;
}
export const lifecycleLabels: Record<IncidentLifecycle["state"], string> = {
  active: "告警持续",
  recovered: "规则已恢复",
  closed: "周期已终止",
  unresolved: "无恢复记录",
  bookmark: "人工标记",
};
export const closureLabels: Record<string, string> = {
  consecutive_clear_frames: "连续帧满足恢复规则",
  baseline_replaced: "基线已替换，原周期终止",
  baseline_reset: "基线已清空，原周期终止",
  source_changed: "采集源已切换，原周期终止",
  replay_replaced: "回放会话已切换，原周期终止",
};
export interface Session {
  session: string;
  started: number;
  last_event: number;
  count: number;
}
export const scenarios: Record<string, string> = {
  none: "无扰动",
  focus_change: "失焦",
  light_fade: "光照衰减",
  position_shift: "位置偏移",
  camera_dirty: "镜头污染",
  angle_change: "角度变化",
  ambient_change: "环境光变化",
  product_defect: "合成表面划痕",
};
export const driftLabels: Record<string, string> = {
  none: "未触发规则",
  optical: "光学变化",
  illumination: "光照变化",
  mechanical: "位置／稳定性变化",
  product: "检测结果变化",
  unknown: "原因待核验",
};
export const sourceLabels: Record<string, string> = {
  dataset: "数据集回放",
  synthetic: "合成 PCB",
  camera: "本地摄像头",
  video: "本地视频",
};
export const outcomes: Record<string, string> = {
  insufficient_evidence: "证据不足",
  confirmed_change: "确认变化",
  false_alarm: "误报",
};
export const metrics: Record<string, string> = {
  sharpness: "清晰度",
  brightness: "亮度",
  contrast: "对比度",
  noise_level: "噪声代理",
};
export const stamp = (value: number) =>
  new Date(value * 1000).toLocaleTimeString("zh-CN", { hour12: false });
