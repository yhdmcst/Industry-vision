import { useEffect, useState } from "react";
import { Camera, Save, Database, RefreshCw } from "lucide-react";
import { api } from "./api";
import { Badge, ImageView, Panel } from "./components";
import {
  defectLabels,
  driftLabels,
  qualityReasons,
  sourceLabels,
} from "./types";
import type {
  CaptureBatch,
  CaptureBatchSummary,
  CapturedSample,
  DatasetSummary,
  State,
} from "./types";
import type { Act } from "./MonitorPage";

export function AcquisitionPanel({
  state: s,
  act,
}: {
  state: State;
  act: Act;
}) {
  const [batches, setBatches] = useState<CaptureBatchSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [batch, setBatch] = useState<CaptureBatch | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [split, setSplit] = useState<"baseline" | "evaluation">("evaluation");
  const [condition, setCondition] = useState("");
  const [videoOrigin, setVideoOrigin] = useState("synthetic");
  const [sampleId, setSampleId] = useState("");
  const [published, setPublished] = useState<DatasetSummary | null>(null);
  useEffect(() => setPublished(null), [selected]);
  useEffect(() => {
    const controller = new AbortController();
    api<CaptureBatchSummary[]>(
      "/acquisition/batches",
      "GET",
      undefined,
      controller.signal,
    )
      .then(setBatches)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [revision, s.acquisition.revision]);
  useEffect(() => {
    setBatch(null);
    if (!selected) return;
    const controller = new AbortController();
    api<CaptureBatch>(
      `/acquisition/batches/${selected}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((data) => {
        setBatch(data);
        setError("");
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [selected, revision, s.acquisition.revision]);
  const preview = s.acquisition.preview;
  const expired = !preview || preview.remaining_seconds <= 0;
  const saved = batch?.samples.some(
    (sample) => sample.capture_token === preview?.token,
  );
  const summary = batches.find((item) => item.id === selected);
  const sample =
    batch?.samples.find((item) => item.id === sampleId) ??
    batch?.samples.at(-1);
  const canPreview = !s.running && !s.replay;
  async function perform(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await work();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="acquisition-panel">
      <Panel title="采集预检与样本留存" action={<Camera size={19} />}>
        <div className="acquisition-body">
          <p className="muted small">
            暂停监测后预览原始采集画面，无需基线或模型。预检不应用软件扰动，也不计入监测帧和恢复计数；留存会在本机保存像素，标签由你独立核验。
          </p>
          {(error || s.acquisition.error) && (
            <div className="notice danger" role="alert">
              {error || s.acquisition.error}
            </div>
          )}
          {message && (
            <div className="notice" role="status">
              {message}
            </div>
          )}
          <div className="acquisition-grid">
            <div>
              <div className="actions">
                <button
                  disabled={!canPreview || busy}
                  onClick={() => {
                    setError("");
                    setMessage("");
                    void act("/acquisition/preview");
                  }}
                >
                  <RefreshCw size={15} />
                  采集预览帧
                </button>
                <Badge tone={s.source === "synthetic" ? "orange" : "blue"}>
                  {sourceLabels[s.source]}
                </Badge>
              </div>
              {!canPreview && (
                <div className="notice">
                  请暂停监测并切回普通采集源，预检不会推进固定回放。
                </div>
              )}
              <ImageView
                label="取景预览"
                meta={
                  preview
                    ? new Date(preview.created).toLocaleTimeString("zh-CN")
                    : "尚未预检"
                }
                src={
                  preview
                    ? `/api/acquisition/preview/image?token=${preview.token}`
                    : null
                }
              />
              <div className="capture-quality" data-testid="capture-quality">
                <Badge tone={preview?.usable_for_baseline ? "blue" : "orange"}>
                  {preview
                    ? preview.usable_for_baseline
                      ? "取景质量门通过"
                      : "取景质量门拒绝"
                    : "等待预览"}
                </Badge>
                {preview && (
                  <>
                    <dl className="fact-list">
                      <div>
                        <dt>平均亮度</dt>
                        <dd>{preview.image_quality.brightness.toFixed(1)}</dd>
                      </div>
                      <div>
                        <dt>对比度</dt>
                        <dd>{preview.image_quality.contrast.toFixed(1)}</dd>
                      </div>
                      <div>
                        <dt>清晰度</dt>
                        <dd>{preview.image_quality.sharpness.toFixed(1)}</dd>
                      </div>
                    </dl>
                    <p className="muted small">
                      {preview.quality_reasons
                        .map((reason) => qualityReasons[reason] ?? reason)
                        .join(" / ") ||
                        "仅通过取景可用性检查，不证明参考稳定或产品正常。"}
                    </p>
                    <p className="muted small">
                      源报告尺寸：
                      {preview.source_properties.width &&
                      preview.source_properties.height
                        ? `${preview.source_properties.width} × ${preview.source_properties.height}`
                        : "未提供"}{" "}
                      · 预览归一化：640 × 480。
                      {s.source === "camera" &&
                        "曝光等读数取决于设备后端，本页面不自动修改设备参数。"}
                    </p>
                  </>
                )}
              </div>
            </div>
            <div>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void perform(async () => {
                    const created = await api<CaptureBatch>(
                      "/acquisition/batches",
                      "POST",
                      { name, description },
                    );
                    setSelected(created.id);
                    setRevision((value) => value + 1);
                    setName("");
                    setMessage("采集批次已创建，预览后可留存样本。");
                  });
                }}
              >
                <label>
                  新批次名称
                  <input
                    required
                    maxLength={200}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="工位 A · 批次 2026-10-09"
                  />
                </label>
                <label>
                  采集计划
                  <textarea
                    maxLength={2000}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="参考工况、评估工况、固定曝光与独立核验计划…"
                  />
                </label>
                <button type="submit" disabled={busy}>
                  创建采集批次
                </button>
              </form>
              <label>
                留存批次
                <select
                  aria-label="留存批次"
                  value={selected}
                  onChange={(e) => {
                    setSelected(e.target.value);
                    setSampleId("");
                    setMessage("");
                  }}
                >
                  <option value="">选择批次</option>
                  {batches.map((item) => (
                    <option
                      key={item.id}
                      value={item.id}
                      disabled={!!item.error}
                    >
                      {item.name} · {item.sample_count ?? 0} 帧
                      {item.error ? " · 损坏" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!preview) return;
                  void perform(async () => {
                    const success = await act(
                      `/acquisition/batches/${selected}/samples`,
                      {
                        token: preview.token,
                        split,
                        origin: videoOrigin,
                        conditions: condition.trim()
                          ? { operator_record: condition.trim() }
                          : {},
                        label: {
                          defect: "unknown",
                          cause: "unknown",
                          note: "",
                        },
                      },
                    );
                    if (success) {
                      setRevision((value) => value + 1);
                      setMessage(
                        "预览像素已留存；标签保持未标注，请独立核验。",
                      );
                    }
                  });
                }}
              >
                <label>
                  留存分组
                  <select
                    aria-label="留存分组"
                    value={split}
                    onChange={(e) => setSplit(e.target.value as typeof split)}
                  >
                    <option value="baseline">参考基线</option>
                    <option value="evaluation">评估样本</option>
                  </select>
                </label>
                {s.source === "video" && (
                  <label>
                    视频来源声明
                    <select
                      aria-label="视频来源声明"
                      value={videoOrigin}
                      onChange={(e) => setVideoOrigin(e.target.value)}
                    >
                      <option value="synthetic">合成／测试视频</option>
                      <option value="real">真实采集视频（声明）</option>
                    </select>
                  </label>
                )}
                <label>
                  当前采集条件
                  <textarea
                    maxLength={200}
                    value={condition}
                    onChange={(e) => setCondition(e.target.value)}
                    placeholder="光源、曝光、固定工装、物理变化；不要把推测当成独立标签"
                  />
                </label>
                <p className="muted small">
                  {s.source === "synthetic"
                    ? "合成源强制标为 synthetic。"
                    : s.source === "camera"
                      ? "摄像头标为真实采集，不能据此认定真实缺陷。"
                      : "视频来源按你的声明记录。"}{" "}
                  本步骤保存原始预览，不叠加演示扰动。
                </p>
                <button
                  type="submit"
                  disabled={
                    busy ||
                    !batch ||
                    !canPreview ||
                    expired ||
                    saved ||
                    (split === "baseline" && !preview?.usable_for_baseline)
                  }
                >
                  <Save size={15} />
                  留存预览样本
                </button>
                {preview && (
                  <p className="muted small">
                    {saved
                      ? "此帧已留存，请重新采集。"
                      : expired
                        ? "预览已超过 60 秒，请重新采集。"
                        : "预览在 60 秒内可留存；每次重新采集获得新的样本身份。"}
                  </p>
                )}
              </form>
            </div>
          </div>
          {batch && (
            <>
              <div className="source-strip">
                <span data-testid="capture-counts">
                  参考 {summary?.baseline_count ?? 0} · 评估{" "}
                  {summary?.evaluation_count ?? 0} · 共 {batch.samples.length}
                  /500 帧
                </span>
                <span>重复图像 {summary?.duplicate_images ?? 0} 帧</span>
              </div>
              {!!summary?.duplicate_images && (
                <div className="notice">
                  存在像素摘要重复的样本，不能据此认为它们是独立统计证据；合成固定画面会重复。
                </div>
              )}
              {batch.samples.length > 0 && (
                <div className="acquisition-grid">
                  <div>
                    <label>
                      已留存样本
                      <select
                        aria-label="已留存样本"
                        value={sample?.id ?? ""}
                        onChange={(e) => setSampleId(e.target.value)}
                      >
                        {batch.samples.map((item, index) => (
                          <option key={item.id} value={item.id}>
                            {index + 1} ·{" "}
                            {item.split === "baseline" ? "参考" : "评估"} ·{" "}
                            {defectLabels[item.label.defect]}
                          </option>
                        ))}
                      </select>
                    </label>
                    <ImageView
                      label="留存样本"
                      meta={
                        sample
                          ? new Date(sample.captured_at).toLocaleString("zh-CN")
                          : "—"
                      }
                      src={
                        sample
                          ? `/api/acquisition/batches/${batch.id}/samples/${sample.id}/image`
                          : null
                      }
                    />
                  </div>
                  {sample && (
                    <Annotation
                      key={sample.id}
                      sample={sample}
                      busy={busy}
                      save={(values) =>
                        perform(async () => {
                          await api(
                            `/acquisition/batches/${batch.id}/samples/${sample.id}`,
                            "PATCH",
                            values,
                          );
                          setRevision((value) => value + 1);
                          setMessage(
                            "独立核验标注已保存；已有数据集版本保持不变。",
                          );
                        })
                      }
                    />
                  )}
                </div>
              )}
              <div className="actions">
                <button
                  disabled={
                    busy ||
                    (summary?.baseline_count ?? 0) < 10 ||
                    (summary?.baseline_count ?? 0) > 100 ||
                    (summary?.evaluation_count ?? 0) < 1
                  }
                  onClick={() =>
                    void perform(async () => {
                      const result = await api<DatasetSummary>(
                        `/acquisition/batches/${batch.id}/publish`,
                        "POST",
                      );
                      setPublished(result);
                      setMessage(
                        "固定数据集已发布，可在样本管理中选择并建立回放。",
                      );
                    })
                  }
                >
                  <Database size={15} />
                  发布为回放数据集
                </button>
              </div>
              <p className="muted small">
                发布需要 10–100 个参考样本和至少 1
                个评估样本。发布不切换采集源；修改草稿后再次发布生成对应版本，原版本保留。
              </p>
            </>
          )}
          {published && (
            <div className="notice" data-testid="published-capture">
              数据集 {published.name} · {published.id.slice(0, 12)} · 参考{" "}
              {published.baseline_count} / 评估 {published.evaluation_count}
            </div>
          )}
        </div>
      </Panel>
    </div>
  );
}

function Annotation({
  sample,
  busy,
  save,
}: {
  sample: CapturedSample;
  busy: boolean;
  save: (values: unknown) => Promise<void>;
}) {
  const [split, setSplit] = useState(sample.split);
  const [defect, setDefect] = useState(sample.label.defect);
  const [cause, setCause] = useState(sample.label.cause);
  const [note, setNote] = useState(sample.label.note);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void save({
          split,
          label: { defect, cause, note },
          conditions: sample.conditions,
        });
      }}
    >
      <label>
        样本用途
        <select
          aria-label="样本用途"
          value={split}
          onChange={(e) => setSplit(e.target.value as typeof split)}
        >
          <option value="baseline">参考基线</option>
          <option value="evaluation">评估样本</option>
        </select>
      </label>
      <label>
        独立缺陷标签
        <select
          aria-label="独立缺陷标签"
          value={defect}
          onChange={(e) => setDefect(e.target.value as typeof defect)}
        >
          {Object.entries(defectLabels).map(([key, value]) => (
            <option key={key} value={key}>
              {value}
            </option>
          ))}
        </select>
      </label>
      <label>
        独立原因标签
        <select
          aria-label="独立原因标签"
          value={cause}
          onChange={(e) => setCause(e.target.value)}
        >
          <option value="unknown">未核验</option>
          {Object.entries(driftLabels)
            .filter(([key]) => key !== "unknown")
            .map(([key, value]) => (
              <option key={key} value={key}>
                {key === "none" ? "无异常（核验）" : value}
              </option>
            ))}
        </select>
      </label>
      <label>
        标注依据
        <textarea
          maxLength={2000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="独立测量、人工检查的方法与结果；未知请保留未标注"
        />
      </label>
      <button type="submit" disabled={busy}>
        保存样本标注
      </button>
      <p className="muted small">
        标注属于操作员声明，不进入模型快照，也不自动等同于真实缺陷或已验证根因。
      </p>
    </form>
  );
}
