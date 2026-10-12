import { useEffect, useRef, useState } from "react";
import { Layers, Trash2 } from "lucide-react";
import { api } from "./api";
import { Badge, ImageView, Panel } from "./components";
import { defectLabels } from "./types";
import type {
  CaptureBatch,
  CaptureBatchSummary,
  DatasetManifest,
  DatasetSample,
  DatasetSummary,
  State,
} from "./types";

type Selection = {
  kind: "capture" | "dataset";
  source_id: string;
  sample_id: string;
  split: "baseline" | "evaluation";
};
type CheckedSample = DatasetSample & {
  sha256: string;
  lineage: {
    kind: string;
    source_id: string;
    sample_id: string;
    batch_key: string;
  };
};
type Preflight = {
  checked_sha256: string;
  baseline_count: number;
  evaluation_count: number;
  warnings: string[];
  samples: CheckedSample[];
};

export function CompositionPanel({ state: s }: { state: State }) {
  const [kind, setKind] = useState<Selection["kind"]>("capture");
  const [catalog, setCatalog] = useState<
    (CaptureBatchSummary | DatasetSummary)[]
  >([]);
  const [source, setSource] = useState("");
  const [samples, setSamples] = useState<DatasetSample[]>([]);
  const [selections, setSelections] = useState<Selection[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [split, setSplit] = useState<Selection["split"]>("evaluation");
  const [page, setPage] = useState(0);
  const [previewIndex, setPreviewIndex] = useState(0);
  const [check, setCheck] = useState<Preflight | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const sourceRevision = useRef(s.acquisition.revision);
  sourceRevision.current = s.acquisition.revision;
  useEffect(() => {
    const controller = new AbortController();
    setCatalog([]);
    api<(CaptureBatchSummary | DatasetSummary)[]>(
      kind === "capture" ? "/acquisition/batches" : "/datasets",
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setCatalog(value);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [kind, s.acquisition.revision, revision]);
  useEffect(() => {
    const controller = new AbortController();
    setSamples([]);
    setPage(0);
    setPreviewIndex(0);
    if (!source) return;
    api<CaptureBatch | DatasetManifest>(
      kind === "capture"
        ? `/acquisition/batches/${source}`
        : `/datasets/${source}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (controller.signal.aborted) return;
        setSamples(value.samples);
        setError("");
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [source, kind, s.acquisition.revision, revision]);
  useEffect(() => {
    setCheck(null);
    setMessage("");
  }, [name, description, selections]);
  useEffect(() => setCheck(null), [s.acquisition.revision, revision]);
  const command = { name, description, selections };
  function add(items: DatasetSample[]) {
    const additions = items.filter(
      (item) =>
        !selections.some(
          (x) =>
            x.kind === kind &&
            x.source_id === source &&
            x.sample_id === item.id,
        ),
    );
    if (selections.length + additions.length > 500) {
      setError("每次编排最多 500 个样本");
      return;
    }
    setSelections([
      ...selections,
      ...additions.map((item) => ({
        kind,
        source_id: source,
        sample_id: item.id,
        split,
      })),
    ]);
  }
  async function perform(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await work();
    } catch (e) {
      setCheck(null);
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const item = samples[previewIndex];
  const preview = item
    ? kind === "capture"
      ? `/api/acquisition/batches/${source}/samples/${item.id}/image`
      : `/api/datasets/${source}/images/${previewIndex}`
    : null;
  return (
    <div className="composition-panel">
      <Panel title="跨批次数据集编排" action={<Layers size={19} />}>
        <div className="acquisition-body">
          <p className="muted small">
            从采集批次或已导入数据集选择参考与评估样本，保留原样本身份、标签和来源。发布前检查批次交叉与重复像素；检查通过不等于完成盲测。
          </p>
          {error && (
            <div className="notice danger" role="alert">
              {error}
            </div>
          )}
          {message && (
            <div className="notice" role="status">
              {message}
            </div>
          )}
          <div className="acquisition-grid">
            <div>
              <label>
                编排来源类型
                <select
                  aria-label="编排来源类型"
                  value={kind}
                  onChange={(e) => {
                    setKind(e.target.value as Selection["kind"]);
                    setSource("");
                  }}
                >
                  <option value="capture">采集批次</option>
                  <option value="dataset">固定数据集</option>
                </select>
              </label>
              <label>
                编排来源
                <select
                  aria-label="编排来源"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                >
                  <option value="">选择来源…</option>
                  {catalog.map((c) => (
                    <option key={c.id} value={c.id} disabled={!!c.error}>
                      {c.name} · {c.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                加入用途
                <select
                  aria-label="加入用途"
                  value={split}
                  onChange={(e) =>
                    setSplit(e.target.value as Selection["split"])
                  }
                >
                  <option value="baseline">参考基线</option>
                  <option value="evaluation">评估样本</option>
                </select>
              </label>
              <div className="actions">
                <button
                  disabled={busy || !samples.length}
                  onClick={() => add(samples.filter((x) => x.split === split))}
                >
                  加入来源的{split === "baseline" ? "参考" : "评估"}组
                </button>
                <button
                  disabled={busy}
                  onClick={() => setRevision((r) => r + 1)}
                >
                  刷新来源
                </button>
              </div>
              <div className="composition-list">
                {samples
                  .slice(page * 10, (page + 1) * 10)
                  .map((sample, offset) => {
                    const selected = selections.find(
                      (x) =>
                        x.kind === kind &&
                        x.source_id === source &&
                        x.sample_id === sample.id,
                    );
                    return (
                      <div className="composition-row" key={sample.id}>
                        <button
                          className="text-button"
                          onClick={() => setPreviewIndex(page * 10 + offset)}
                        >
                          {sample.id.slice(0, 20)} ·{" "}
                          {defectLabels[sample.label.defect]}
                        </button>
                        <button
                          disabled={busy || !!selected}
                          onClick={() => add([sample])}
                        >
                          {selected
                            ? selected.split === "baseline"
                              ? "已选参考"
                              : "已选评估"
                            : "加入"}
                        </button>
                      </div>
                    );
                  })}
              </div>
              {!!samples.length && (
                <div className="actions">
                  <button
                    disabled={page === 0}
                    onClick={() => setPage(page - 1)}
                  >
                    上一组样本
                  </button>
                  <span>
                    {page + 1}/{Math.ceil(samples.length / 10)}
                  </span>
                  <button
                    disabled={(page + 1) * 10 >= samples.length}
                    onClick={() => setPage(page + 1)}
                  >
                    下一组样本
                  </button>
                </div>
              )}
              <ImageView
                label="编排来源预览"
                meta={item?.id ?? "尚未选择"}
                src={preview}
              />
            </div>
            <div>
              <label>
                编排数据集名称
                <input
                  maxLength={200}
                  disabled={busy}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="工位 A · 参考与独立评估"
                />
              </label>
              <label>
                编排说明
                <textarea
                  maxLength={2000}
                  disabled={busy}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="采集划分依据与使用范围"
                />
              </label>
              <div className="source-strip" data-testid="composition-counts">
                参考 {selections.filter((x) => x.split === "baseline").length} ·
                评估 {selections.filter((x) => x.split === "evaluation").length}{" "}
                · 共 {selections.length}/500
              </div>
              <div className="composition-list">
                {selections.map((selection, index) => (
                  <div
                    className="composition-row"
                    key={`${selection.kind}:${selection.source_id}:${selection.sample_id}`}
                  >
                    <span>
                      {index + 1} · {selection.source_id.slice(0, 8)} /{" "}
                      {selection.sample_id.slice(0, 16)}
                    </span>
                    <select
                      aria-label={`样本 ${index + 1} 用途`}
                      value={selection.split}
                      disabled={busy}
                      onChange={(e) =>
                        setSelections(
                          selections.map((x, i) =>
                            i === index
                              ? {
                                  ...x,
                                  split: e.target.value as Selection["split"],
                                }
                              : x,
                          ),
                        )
                      }
                    >
                      <option value="baseline">参考</option>
                      <option value="evaluation">评估</option>
                    </select>
                    <button
                      className="icon-button"
                      aria-label={`移除样本 ${index + 1}`}
                      disabled={busy}
                      onClick={() =>
                        setSelections(selections.filter((_, i) => i !== index))
                      }
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
              <div className="actions">
                <button
                  disabled={busy || !selections.length}
                  onClick={() => setSelections([])}
                >
                  清空编排选择
                </button>
                <button
                  disabled={busy || !name.trim() || selections.length < 11}
                  onClick={() =>
                    void perform(async () => {
                      const requestedRevision = sourceRevision.current;
                      const result = await api<Preflight>(
                        "/composition/preflight",
                        "POST",
                        command,
                      );
                      if (requestedRevision === sourceRevision.current)
                        setCheck(result);
                      else setError("来源已变化，请刷新并重新检查");
                    })
                  }
                >
                  检查编排
                </button>
              </div>
              {check && (
                <div data-testid="composition-check">
                  <Badge tone="blue">
                    参考 {check.baseline_count} / 评估 {check.evaluation_count}
                  </Badge>
                  {check.warnings.map((warning, index) => (
                    <p className="notice" key={index}>
                      {warning}
                    </p>
                  ))}
                  <p className="muted small">
                    数据检查完成 ；发布时重新校验源记录与像素。
                  </p>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void perform(async () => {
                        const result = await api<DatasetSummary>(
                          "/composition/publish",
                          "POST",
                          { ...command, checked_sha256: check.checked_sha256 },
                        );
                        setCheck(null);
                        setRevision((r) => r + 1);
                        setMessage(
                          `编排数据集已发布：${result.name} · ${result.id.slice(0, 12)}，在样本管理中刷新列表后可回放。`,
                        );
                      })
                    }
                  >
                    发布编排数据集
                  </button>
                </div>
              )}
            </div>
          </div>
          <p className="muted small">
            选择只保留在当前页面；发布生成固定版本，不修改来源草稿、已有数据集或工作站会话。来源标签有变化时须刷新并重新检查。仅有导入批次名称时仍属于来源声明。
          </p>
        </div>
      </Panel>
    </div>
  );
}
