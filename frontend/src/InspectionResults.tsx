import { useEffect, useState } from "react";
import { api } from "./api";
import { Badge } from "./components";
import { inspectionStatuses } from "./types";
import type {
  Detection,
  DetectionAvailability,
  InspectionProducer,
  InspectionResult,
  InspectionSource,
  Alignment,
} from "./types";

export function AlignmentEvidence({
  alignment,
  detectorError,
}: {
  alignment?: Alignment | null;
  detectorError?: string;
}) {
  if (!alignment) return null;
  return (
    <div className="alignment-evidence">
      <p className="muted small">
        姿态对齐：
        {alignment.status === "passed"
          ? "通过"
          : alignment.status === "disabled"
            ? "未启用"
            : "拒绝"}
      </p>
      {alignment.status === "passed" && (
        <p className="muted small">
          旋转 {alignment.angle_deg?.toFixed(1)}° · 尺度{" "}
          {alignment.scale?.toFixed(3)} · 内点 {alignment.inliers} · 重投影{" "}
          {alignment.reprojection_error?.toFixed(2)} px · 有效覆盖{" "}
          {((alignment.coverage ?? 0) * 100).toFixed(1)}%
        </p>
      )}
      {alignment.error && alignment.error !== detectorError && (
        <p className="notice danger">{alignment.error}</p>
      )}
    </div>
  );
}

interface ResultSummary {
  id: string;
  dataset_id: string;
  producer: InspectionProducer;
  counts: Record<InspectionResult["status"], number>;
  baseline_ready: boolean;
}

export function InspectionInput({
  datasetId,
  sampleId,
  value,
  onChange,
}: {
  datasetId: string;
  sampleId?: string;
  value: string;
  onChange: (id: string) => void;
}) {
  const [path, setPath] = useState("");
  const [packages, setPackages] = useState<ResultSummary[]>([]);
  const [results, setResults] = useState<InspectionResult[] | null>(null);
  const [resultError, setResultError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api<ResultSummary[]>(
      `/datasets/${datasetId}/inspection-results`,
      "GET",
      undefined,
      controller.signal,
    )
      .then(setPackages)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [datasetId, revision]);
  useEffect(() => {
    setResults(null);
    setResultError("");
    if (!value) return;
    const controller = new AbortController();
    api<{ results: InspectionResult[] }>(
      `/inspection-results/${value}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((data) => setResults(data.results))
      .catch((e) => {
        if (!controller.signal.aborted) setResultError(e.message);
      });
    return () => controller.abort();
  }, [value]);
  const selected = packages.find((p) => p.id === value);
  const result = results?.find((r) => r.sample_id === sampleId);
  return (
    <div className="inspection-input">
      <h3>质检结果来源</h3>
      <p className="muted small">
        为下一次回放选择检测结果。外部判定与独立缺陷标签分别保存；改变选择不影响当前回放。
      </p>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (busy) return;
          setBusy(true);
          setError("");
          try {
            const result = await api<ResultSummary>(
              "/inspection-results/import",
              "POST",
              { path },
            );
            if (result.dataset_id !== datasetId) {
              setError(
                "结果已导入，但属于其他数据集；请切换到对应数据集查看。",
              );
            } else {
              setRevision((r) => r + 1);
              if (result.baseline_ready) onChange(result.id);
              else setError("结果已保存，基线存在不可用结果，暂不能用于回放。");
            }
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          检测结果文件路径
          <input
            value={path}
            required
            onChange={(e) => setPath(e.target.value)}
            placeholder="/path/to/inspection-results.json"
          />
        </label>
        <button disabled={busy} type="submit">
          {busy ? "正在校验结果…" : "导入检测结果"}
        </button>
      </form>
      {error && (
        <div className="notice danger" role="alert">
          {error}
        </div>
      )}
      <label>
        检测结果来源
        <select
          aria-label="检测结果来源"
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
            setError("");
          }}
        >
          <option value="">演示检测 · 无真实缺陷标签</option>
          {packages.map((p) => (
            <option key={p.id} value={p.id} disabled={!p.baseline_ready}>
              {p.producer.name} / {p.producer.version} ·{" "}
              {p.producer.provenance === "synthetic_fixture"
                ? "合成演示结果"
                : "上游结果（声明）"}{" "}
              · {p.id.slice(0, 8)}
              {!p.baseline_ready && " · 基线结果不完整"}
            </option>
          ))}
        </select>
      </label>
      {selected && (
        <>
          <div className="actions">
            {Object.entries(selected.counts).map(([status, count]) => (
              <Badge key={status} tone={status === "ok" ? "green" : "orange"}>
                {inspectionStatuses[status as InspectionResult["status"]]}{" "}
                {count}
              </Badge>
            ))}
          </div>
          <p className="muted small">
            样本 {sampleId}：
            {resultError
              ? "结果读取失败"
              : results === null
                ? "正在读取结果…"
                : !result
                  ? "缺失（结果包未提供）"
                  : `${inspectionStatuses[result.status]}${result.status === "ok" ? ` · ${result.is_ng ? "NG" : "OK"} · ${selected.producer.score_semantics === "anomaly_score" ? `异常分数 ${result.anomaly_score?.toFixed(3)}` : `判定置信度 ${result.confidence?.toFixed(3)}`}` : ""}`}
          </p>
          {selected.producer.score_semantics === "anomaly_score" && (
            <p className="muted small">
              固定阈值 {selected.producer.decision_threshold?.toFixed(3)}
              ；异常分数不是置信度，高于阈值判 NG。
            </p>
          )}
          <AlignmentEvidence
            alignment={result?.alignment}
            detectorError={result?.error}
          />
          {resultError && (
            <div className="notice danger" role="alert">
              {resultError}
            </div>
          )}
          {result?.defect_types.length ? (
            <p className="muted small">
              预测类别：{result.defect_types.join("、")}
            </p>
          ) : null}
          {result?.error && <div className="notice">{result.error}</div>}
        </>
      )}
    </div>
  );
}

export function InspectionEvidence({
  source,
  detection,
  availability,
}: {
  source?: InspectionSource;
  detection?: Detection;
  availability?: DetectionAvailability;
}) {
  const live = source?.kind === "local_visual";
  const external = live || source?.kind === "external_results";
  const anomaly = source?.producer?.score_semantics === "anomaly_score";
  return (
    <div className="inspection-evidence">
      <div className="actions">
        <Badge tone={external ? "blue" : "orange"}>
          {live ? "本地视觉推理" : external ? "外部质检结果" : "演示检测"}
        </Badge>
        {source?.producer?.provenance === "synthetic_fixture" && (
          <Badge tone="orange">合成结果夹具</Badge>
        )}
        {source?.producer?.provenance === "upstream" && (
          <Badge>{live ? "固定视觉模型" : "上游输出（声明）"}</Badge>
        )}
      </div>
      {source?.producer && (
        <p className="muted small">
          {source.producer.name} · {source.producer.version}
        </p>
      )}
      {source?.result_id && (
        <p className="muted small">结果版本 {source.result_id.slice(0, 12)}</p>
      )}
      {live && detection?.metadata.elapsed_ms != null && (
        <p className="muted small">
          检测观测耗时 {detection.metadata.elapsed_ms.toFixed(1)} ms
        </p>
      )}
      <dl className="fact-list">
        <div>
          <dt>检测状态</dt>
          <dd>
            {detection ? inspectionStatuses[detection.status] : "等待结果"}
          </dd>
        </div>
        <div>
          <dt>{live ? "视觉判定" : external ? "上游判定" : "演示判定"}</dt>
          <dd>
            {detection?.status === "ok"
              ? detection.is_ng
                ? "NG"
                : "OK"
              : "不可用"}
          </dd>
        </div>
        <div>
          <dt>{external ? "判定置信度" : "参考匹配度"}</dt>
          <dd>{detection?.confidence?.toFixed(3) ?? "—"}</dd>
        </div>
      </dl>
      {anomaly && (
        <dl className="fact-list">
          <div>
            <dt>异常分数</dt>
            <dd>
              {detection?.metadata.result?.anomaly_score?.toFixed(3) ?? "—"}
            </dd>
          </div>
          <div>
            <dt>固定判定阈值</dt>
            <dd>{source?.producer?.decision_threshold?.toFixed(3) ?? "—"}</dd>
          </div>
        </dl>
      )}
      {anomaly && (
        <p className="muted small">
          异常分数未经概率标定；置信度、稳定性与综合评分不计算。原图成像观测保留，对齐只用于检测器。
        </p>
      )}
      <AlignmentEvidence
        alignment={detection?.metadata.result?.alignment}
        detectorError={detection?.metadata.result?.error}
      />
      {!!detection?.metadata.result?.defect_types.length && (
        <p className="muted small">
          预测类别：{detection.metadata.result.defect_types.join("、")}
        </p>
      )}
      {detection?.metadata.result?.error && (
        <div className="notice danger">{detection.metadata.result.error}</div>
      )}
      {!!availability?.unavailable && (
        <div className="notice">
          当前窗口 {availability.unavailable}/{availability.total}{" "}
          个结果不可用，一致性统计暂停，图像观测继续。
        </div>
      )}
      {external && (
        <p className="muted small">
          {anomaly
            ? "阈值判定不等于独立缺陷标签。"
            : "高置信度不代表合格；预测结果不等于独立缺陷标签。"}
        </p>
      )}
    </div>
  );
}
