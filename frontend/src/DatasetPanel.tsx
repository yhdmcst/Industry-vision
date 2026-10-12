import { useEffect, useState } from "react";
import { PathInput } from "./PathInput";
import { Database, Download, RefreshCw } from "lucide-react";
import { api } from "./api";
import { Badge, ImageView, Panel } from "./components";
import type { DatasetManifest, DatasetSummary, State } from "./types";
import { defectLabels } from "./types";
import type { Act } from "./MonitorPage";
import { InspectionInput } from "./InspectionResults";

export function DatasetPanel({ state: s, act }: { state: State; act: Act }) {
  const [path, setPath] = useState("");
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [selected, setSelected] = useState(s.replay?.dataset_id ?? "");
  const [manifest, setManifest] = useState<DatasetManifest | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [batch, setBatch] = useState("");
  const [split, setSplit] = useState("");
  const [page, setPage] = useState(0);
  const [sampleIndex, setSampleIndex] = useState(0);
  const [resultId, setResultId] = useState(s.inspection_source.result_id ?? "");
  useEffect(() => {
    setResultId(
      selected === s.replay?.dataset_id
        ? (s.inspection_source.result_id ?? "")
        : "",
    );
  }, [selected, s.replay?.dataset_id, s.inspection_source.result_id]);
  const [runs, setRuns] = useState<
    { session: string; started: number; dataset_id: string }[]
  >([]);
  const [run, setRun] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<{ session: string; started: number; dataset_id: string }[]>(
      "/replays",
      "GET",
      undefined,
      controller.signal,
    )
      .then(setRuns)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [s.session, revision]);
  useEffect(() => {
    const controller = new AbortController();
    api<DatasetSummary[]>("/datasets", "GET", undefined, controller.signal)
      .then(setDatasets)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [revision, s.acquisition.revision]);
  useEffect(() => {
    setManifest(null);
    setSampleIndex(0);
    setBatch("");
    setSplit("");
    setPage(0);
    if (!selected) return;
    const controller = new AbortController();
    api<DatasetManifest>(
      `/datasets/${selected}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((data) => {
        setManifest(data);
        setError("");
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [selected, revision]);
  const sample = manifest?.samples[sampleIndex];
  const filtered = (manifest?.samples ?? [])
    .map((item, index) => ({ item, index }))
    .filter(
      ({ item }) =>
        (!batch || item.batch === batch) && (!split || item.split === split),
    );
  return (
    <div className="dataset-panel">
      <Panel title="样本管理与回放" action={<Database size={19} />}>
        <div className="dataset-body">
          <p className="muted small">
            导入本机 JSON
            清单及其目录内的图像、指定视频帧。基线与评估样本分开保存，标签不传给模型。每次回放创建独立会话。
          </p>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              if (busy) return;
              setBusy(true);
              setError("");
              try {
                const result = await api<DatasetSummary>(
                  "/datasets/import",
                  "POST",
                  { path },
                );
                setSelected(result.id);
                setRevision((r) => r + 1);
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <PathInput
              label="数据集清单路径"
              value={path}
              onChange={setPath}
              disabled={busy}
              placeholder="/path/to/dataset/manifest.json"
            />
            <div className="actions">
              <button type="submit" disabled={busy}>
                {busy ? "正在导入并校验…" : "导入数据集"}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => setRevision((r) => r + 1)}
              >
                <RefreshCw size={14} />
                刷新列表
              </button>
            </div>
          </form>
          {error && (
            <div className="notice danger" role="alert">
              {error}
            </div>
          )}
          <label>
            已导入数据集
            <select
              aria-label="已导入数据集"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="">选择数据集…</option>
              {datasets.map((d) => (
                <option key={d.id} value={d.id} disabled={!!d.error}>
                  {d.name} ·{" "}
                  {d.error ||
                    `${d.baseline_count} 基线 / ${d.evaluation_count} 评估`}{" "}
                  · {d.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          {!datasets.length && (
            <div className="empty-inline">
              尚未导入数据集。清单格式见 docs/datasets.md。
            </div>
          )}
          {manifest && (
            <>
              <InspectionInput
                key={selected}
                datasetId={selected}
                sampleId={sample?.id}
                value={resultId}
                onChange={setResultId}
              />
              <div className="dataset-heading">
                <div>
                  <h3>{manifest.name}</h3>
                  <p className="muted small">
                    {manifest.description || "按清单中的顺序回放评估样本"}
                  </p>
                </div>
                <button
                  className="primary"
                  disabled={busy || s.running || s.model.pending}
                  onClick={() =>
                    act(
                      "/replay",
                      { dataset_id: selected, result_id: resultId || null },
                      "独立回放已建立，可单帧采样或开始监测。",
                    )
                  }
                >
                  建立回放
                </button>
              </div>
              {(s.running || s.model.pending) && (
                <p className="muted small">
                  建立回放前请暂停监测，并等待模型任务完成。
                </p>
              )}
              <div className="dataset-filters">
                <label>
                  样本分组
                  <select
                    aria-label="样本分组"
                    value={split}
                    onChange={(e) => {
                      setSplit(e.target.value);
                      setPage(0);
                    }}
                  >
                    <option value="">全部分组</option>
                    <option value="baseline">参考基线</option>
                    <option value="evaluation">评估样本</option>
                  </select>
                </label>
                <label>
                  批次筛选
                  <select
                    aria-label="批次筛选"
                    value={batch}
                    onChange={(e) => {
                      setBatch(e.target.value);
                      setPage(0);
                    }}
                  >
                    <option value="">全部批次</option>
                    {[
                      ...new Set(manifest.samples.map((item) => item.batch)),
                    ].map((b) => (
                      <option key={b}>{b}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="dataset-content">
                <div>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>样本 / 批次</th>
                          <th>分组</th>
                          <th>来源</th>
                          <th>缺陷标签</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filtered
                          .slice(page * 10, page * 10 + 10)
                          .map(({ item, index }) => (
                            <tr
                              key={item.id}
                              className={
                                sampleIndex === index ? "selected-row" : ""
                              }
                            >
                              <td>
                                <button
                                  className="table-metric"
                                  onClick={() => setSampleIndex(index)}
                                >
                                  {item.id}
                                </button>
                                <small className="dataset-batch">
                                  {item.batch}
                                </small>
                              </td>
                              <td>
                                {item.split === "baseline" ? "基线" : "评估"}
                              </td>
                              <td>
                                {item.origin === "synthetic"
                                  ? "合成"
                                  : "真实采集（声明）"}
                                {item.perturbation !== "none" && " / 软件扰动"}
                              </td>
                              <td>{defectLabels[item.label.defect]}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="dataset-pagination">
                    <span className="muted small">
                      共 {filtered.length} 个样本 · 第 {page + 1} 页
                    </span>
                    <div className="actions">
                      <button
                        disabled={page === 0}
                        onClick={() => setPage(page - 1)}
                      >
                        上一页
                      </button>
                      <button
                        disabled={(page + 1) * 10 >= filtered.length}
                        onClick={() => setPage(page + 1)}
                      >
                        下一页
                      </button>
                    </div>
                  </div>
                </div>
                {sample && (
                  <div>
                    <ImageView
                      label="样本预览"
                      meta={sample.id}
                      src={`/api/datasets/${selected}/images/${sampleIndex}`}
                    />
                    <dl className="fact-list">
                      <div>
                        <dt>采集时间</dt>
                        <dd>{sample.captured_at || "未提供"}</dd>
                      </div>
                      <div>
                        <dt>软件扰动</dt>
                        <dd>{sample.perturbation}</dd>
                      </div>
                      <div>
                        <dt>原因标签</dt>
                        <dd>{sample.label.cause}</dd>
                      </div>
                    </dl>
                    <p className="muted small">
                      {Object.entries(sample.conditions)
                        .map(([key, value]) => `${key}：${value}`)
                        .join("；") || "未提供采集条件"}
                    </p>
                    <p className="muted small">
                      {sample.label.note || "未填写标签依据"}
                    </p>
                    {sample.lineage && (
                      <p className="muted small">
                        根来源 {sample.lineage.kind} ·{" "}
                        {sample.lineage.source_id.slice(0, 12)} /{" "}
                        {sample.lineage.sample_id} · 批次{" "}
                        {sample.lineage.batch_key}
                      </p>
                    )}
                    <p className="muted small">
                      来源和标签由导入者声明，尚未独立核验。
                    </p>
                  </div>
                )}
              </div>
            </>
          )}
          {s.replay && (
            <div className="replay-progress" data-testid="replay-progress">
              <div className="dataset-heading">
                <strong>{s.replay.name}</strong>
                <Badge tone={s.replay.completed ? "green" : "blue"}>
                  {s.replay.completed
                    ? "回放完成"
                    : s.running
                      ? "回放中"
                      : "回放已暂停"}{" "}
                  · {s.replay.position}/{s.replay.total}
                </Badge>
              </div>
              <progress
                max={s.replay.total}
                value={s.replay.position}
                aria-label="回放进度"
              />
              <div className="actions">
                <button
                  disabled={s.running || s.replay.completed}
                  onClick={() => act("/capture", { action: "sample" })}
                >
                  回放下一帧
                </button>
                <button
                  disabled={s.replay.completed}
                  onClick={() =>
                    act("/capture", { action: s.running ? "pause" : "start" })
                  }
                >
                  {s.running ? "暂停回放" : "连续回放"}
                </button>
                <a className="button" href="/api/replay/export" download>
                  <Download size={14} />
                  导出回放结果
                </a>
              </div>
              <p className="muted small">
                重新点击“建立回放”可从首个评估样本开始，旧会话证据保留。部分回放导出会明确记录进度。
              </p>
            </div>
          )}
          {!!runs.length && (
            <div className="replay-progress">
              <label>
                历史回放
                <select
                  aria-label="历史回放"
                  value={run}
                  onChange={(e) => setRun(e.target.value)}
                >
                  <option value="">选择历史会话…</option>
                  {runs.map((r) => (
                    <option key={r.session} value={r.session}>
                      {new Date(r.started * 1000).toLocaleString("zh-CN")} ·{" "}
                      {datasets.find((d) => d.id === r.dataset_id)?.name ??
                        r.dataset_id.slice(0, 8)}{" "}
                      · {r.session.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              {run && (
                <a
                  className="button"
                  href={`/api/sessions/${run}/replay`}
                  download
                >
                  <Download size={14} />
                  导出所选回放
                </a>
              )}
              <p className="muted small">
                列出最近 100 个会话中的回放记录，服务重启后仍可导出。
              </p>
            </div>
          )}
        </div>
      </Panel>
    </div>
  );
}
