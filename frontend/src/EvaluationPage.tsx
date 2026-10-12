import { useEffect, useState } from "react";
import { Download, RefreshCw, GitCompareArrows, BarChart3 } from "lucide-react";
import { api, download } from "./api";
import { Badge, ImageView, Panel } from "./components";
import { AlignmentEvidence } from "./InspectionResults";
import { ReviewStudyPanel } from "./ReviewStudyPanel";
import type { InspectionSource, State } from "./types";
import { defectLabels, driftLabels, inspectionStatuses } from "./types";
import { cohortLabels } from "./evaluationTypes";
import type {
  EvaluationReport,
  ComparisonReport,
  EvaluationSample,
} from "./evaluationTypes";

interface Run {
  session: string;
  started: number;
  dataset_id: string;
  inspection_source: InspectionSource;
}
const causes = ["none", "optical", "illumination", "mechanical", "product"];
const columns = [...causes, "unknown"];
const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;
const cause = (value: string | null) =>
  value === null
    ? "未运行"
    : value === "unknown"
      ? "证据不足"
      : driftLabels[value];
const sourceName = (source: InspectionSource) =>
  source.producer
    ? `${source.producer.name} / ${source.producer.version}`
    : "演示检测";
const verdict = (
  status: EvaluationSample["detection_status"],
  ng: boolean | null,
) =>
  status === null
    ? "未运行"
    : status === "ok"
      ? ng
        ? "NG"
        : "OK"
      : inspectionStatuses[status];

export function EvaluationPage({ state: s }: { state: State }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [session, setSession] = useState(s.replay ? s.session : "");
  const [right, setRight] = useState("");
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [comparison, setComparison] = useState<ComparisonReport | null>(null);
  const [error, setError] = useState("");
  const [compareError, setCompareError] = useState("");
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false);
  const [batch, setBatch] = useState("");
  const [group, setGroup] = useState("");
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const [sampleId, setSampleId] = useState("");
  const [changesOnly, setChangesOnly] = useState(true);
  const [comparePage, setComparePage] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api<Run[]>("/replays", "GET", undefined, controller.signal),
      api<{ id: string; name: string }[]>(
        "/datasets",
        "GET",
        undefined,
        controller.signal,
      ),
    ])
      .then(([history, datasets]) => {
        setRuns(history);
        setNames(Object.fromEntries(datasets.map((d) => [d.id, d.name])));
        setSession((current) => current || history[0]?.session || "");
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [s.session, revision]);
  useEffect(() => {
    setReport(null);
    setComparison(null);
    setError("");
    setBatch("");
    setGroup("");
    setFilter("");
    setPage(0);
    setSampleId("");
    setLoading(false);
    if (!session) return;
    const controller = new AbortController();
    setLoading(true);
    api<EvaluationReport>(
      `/sessions/${session}/evaluation`,
      "GET",
      undefined,
      controller.signal,
    )
      .then(setReport)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [session, revision]);
  useEffect(() => {
    setComparison(null);
    setCompareError("");
    setComparePage(0);
    if (!report || !right || right === session) return;
    const controller = new AbortController();
    api<ComparisonReport>(
      `/evaluation/compare?left=${encodeURIComponent(session)}&right=${encodeURIComponent(right)}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then(setComparison)
      .catch((e) => {
        if (!controller.signal.aborted) setCompareError(e.message);
      });
    return () => controller.abort();
  }, [session, right, report]);
  const runLabel = (run: Run) =>
    `${names[run.dataset_id] ?? run.dataset_id.slice(0, 8)} · ${sourceName(run.inspection_source)} · ${new Date(run.started * 1000).toLocaleString("zh-CN")} · ${run.session.slice(0, 8)}`;
  const rows = (report?.samples ?? []).filter(
    (r) =>
      (!batch || r.batch === batch) &&
      (!group || r.cohort === group) &&
      (!filter ||
        (filter === "issue" &&
          (r.inspection_mismatch ||
            r.rule_mismatch ||
            (r.processed && r.detection_status !== "ok"))) ||
        (filter === "unlabeled" &&
          (r.defect_label === "unknown" || r.cause_label === "unknown")) ||
        (filter === "not_run" && !r.processed)),
  );
  const sample =
    report?.samples.find((r) => r.sample_id === sampleId) ?? rows[0];
  const differences = (comparison?.samples ?? []).filter(
    (r) =>
      !changesOnly || r.status_changed || r.verdict_changed || r.rule_changed,
  );
  const summary = report?.summary;
  const metrics = summary?.inspection;
  const rule = summary?.rule;
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>回放评估</h1>
          <p>核对标签、覆盖率与版本差异，让结果可复查。</p>
        </div>
        <button onClick={() => setRevision((r) => r + 1)} disabled={loading}>
          <RefreshCw size={15} />
          刷新报告
        </button>
      </div>
      <ReviewStudyPanel />
      <Panel title="评估会话" action={<BarChart3 size={19} />}>
        <div className="evaluation-body">
          <label>
            评估会话
            <select
              aria-label="评估会话"
              value={session}
              onChange={(e) => setSession(e.target.value)}
            >
              <option value="">选择回放会话…</option>
              {runs.map((run) => (
                <option key={run.session} value={run.session}>
                  {runLabel(run)}
                </option>
              ))}
            </select>
          </label>
          <p className="muted small">
            报告使用已保存的回放测量。新采样后点击“刷新报告”；标签来自导入者声明，匹配率仅描述当前样本。
          </p>
          {error && (
            <div role="alert" className="notice danger">
              报告读取失败：{error}
            </div>
          )}
          {loading && <p role="status">正在读取回放证据…</p>}
          {!runs.length && !error && (
            <div className="empty-state">
              <p>暂无回放会话。先在“设置与演示”导入数据集并建立回放。</p>
              <a className="button" href="#settings">
                进入样本管理
              </a>
            </div>
          )}
          {report && (
            <>
              <div className="actions">
                <Badge tone={report.completed ? "blue" : "orange"}>
                  {report.completed ? "回放完成" : "部分回放"}
                </Badge>
                <Badge>{sourceName(report.inspection_source)}</Badge>
                <Badge
                  tone={
                    report.inspection_source.provenance === "synthetic_fixture"
                      ? "orange"
                      : ""
                  }
                >
                  {report.inspection_source.provenance === "synthetic_fixture"
                    ? "合成检测结果"
                    : "上游结果（声明）"}
                </Badge>
                <button
                  onClick={() => download("spark-evaluation.json", report)}
                >
                  <Download size={14} />
                  导出评估报告
                </button>
              </div>
              <p className="muted small">{report.dataset_name}</p>
              <details>
                <summary>报告版本与追溯</summary>
                <p className="muted small evaluation-digest">
                  {report.dataset_name} · 会话 {report.session.slice(0, 12)} ·
                  报告 {report.report_sha256.slice(0, 12)}
                  {report.inspection_source.result_id &&
                    ` · 结果版本 ${report.inspection_source.result_id.slice(0, 12)}`}
                </p>
              </details>
              <details className="evaluation-warnings" open>
                <summary>数据与评估边界</summary>
                {report.warnings.map((text) => (
                  <p key={text}>{text}</p>
                ))}
              </details>
            </>
          )}
        </div>
      </Panel>
      {report && summary && metrics && rule && (
        <>
          <div className="evaluation-metrics">
            {[
              [
                "回放进度",
                `${summary.processed}/${summary.total}`,
                `${summary.not_run} 个未运行`,
              ],
              [
                "检测可用",
                `${summary.detection_counts.ok}/${summary.processed}`,
                `缺失 ${summary.detection_counts.missing} · 失败 ${summary.detection_counts.error} · 超时 ${summary.detection_counts.timeout}`,
              ],
              [
                "缺陷标签覆盖",
                metrics.enabled
                  ? `${metrics.assessed}/${metrics.labeled}`
                  : "—",
                metrics.enabled
                  ? `覆盖率 ${percent(metrics.coverage)} · ${metrics.unlabeled} 个未标注`
                  : "演示检测不计算缺陷分类指标",
              ],
              [
                "原因标签覆盖",
                `${rule.assessed}/${rule.labeled}`,
                `证据不足 ${rule.abstained} · 未运行 ${rule.not_run_labeled}`,
              ],
            ].map(([title, value, note]) => (
              <div className="evaluation-metric" key={title}>
                <span>{title}</span>
                <strong>{value}</strong>
                <small>{note}</small>
              </div>
            ))}
          </div>
          <div className="evaluation-grid">
            <Panel title="上游判定与缺陷标签">
              <div className="evaluation-body">
                {!metrics.enabled ? (
                  <p className="muted">
                    当前使用演示检测，不计算缺陷标签分类指标。
                  </p>
                ) : (
                  <>
                    <div
                      className="evaluation-binary"
                      aria-label="缺陷判定混淆矩阵"
                    >
                      {[
                        ["TP · 缺陷判 NG", metrics.tp],
                        ["FN · 缺陷判 OK", metrics.fn],
                        ["FP · 正常判 NG", metrics.fp],
                        ["TN · 正常判 OK", metrics.tn],
                      ].map(([label, count]) => (
                        <div key={label}>
                          <span>{label}</span>
                          <strong>{count}</strong>
                        </div>
                      ))}
                    </div>
                    <dl className="fact-list">
                      {[
                        ["标签匹配率", percent(metrics.label_agreement)],
                        ["精确率", percent(metrics.precision)],
                        ["召回率", percent(metrics.recall)],
                        ["误报率", percent(metrics.false_positive_rate)],
                        ["漏检率", percent(metrics.miss_rate)],
                      ].map(([label, value]) => (
                        <div key={label}>
                          <dt>{label}</dt>
                          <dd>{value}</dd>
                        </div>
                      ))}
                    </dl>
                    <p className="muted small">
                      仅计算 {metrics.assessed} 个有缺陷标签且检测成功的样本；
                      {metrics.unavailable_labeled} 个不可用、
                      {metrics.not_run_labeled}{" "}
                      个未运行，分别保留。分母为零显示“—”。
                    </p>
                  </>
                )}
              </div>
            </Panel>
            <Panel title="规则观测与原因标签">
              <div className="evaluation-body">
                <div className="evaluation-table-wrap">
                  <table className="evaluation-table evaluation-matrix">
                    <caption>行：原因标签 · 列：规则观测</caption>
                    <thead>
                      <tr>
                        <th>标签 ↓ / 观测 →</th>
                        {columns.map((c) => (
                          <th key={c}>{cause(c)}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {causes.map((label) => (
                        <tr key={label}>
                          <th>{cause(label)}</th>
                          {columns.map((prediction) => (
                            <td
                              key={prediction}
                              className={
                                label === prediction
                                  ? "matrix-match"
                                  : rule.matrix[label][prediction]
                                    ? "matrix-error"
                                    : ""
                              }
                            >
                              {rule.matrix[label][prediction]}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted small">
                  标签匹配率 {percent(rule.label_agreement)} · 已分类{" "}
                  {rule.assessed}/{rule.labeled}
                  。“证据不足”计入覆盖率分母，排除在已分类匹配率之外；预热期间的稳定观测也记为证据不足。
                </p>
              </div>
            </Panel>
          </div>
          <Panel title="按批次与数据来源核对">
            <div className="evaluation-body">
              <div className="evaluation-table-wrap">
                <table className="evaluation-table">
                  <thead>
                    <tr>
                      <th>批次</th>
                      <th>数据来源</th>
                      <th>已运行 / 总数</th>
                      <th>缺陷标签覆盖</th>
                      <th>缺陷标签匹配</th>
                      <th>原因标签覆盖</th>
                      <th>原因标签匹配</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.groups.map((g) => (
                      <tr key={`${g.batch}/${g.cohort}`}>
                        <td>{g.batch}</td>
                        <td>{cohortLabels[g.cohort]}</td>
                        <td>
                          {g.summary.processed}/{g.summary.total}
                        </td>
                        <td>
                          {g.summary.inspection.enabled
                            ? `${g.summary.inspection.assessed}/${g.summary.inspection.labeled}`
                            : "—"}
                        </td>
                        <td>{percent(g.summary.inspection.label_agreement)}</td>
                        <td>
                          {g.summary.rule.assessed}/{g.summary.rule.labeled}
                        </td>
                        <td>{percent(g.summary.rule.label_agreement)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small">
                评估图像摘要共 {report.leakage.unique_evaluation_images}{" "}
                个；与基线重复 {report.leakage.baseline_duplicate_ids.length}{" "}
                个，共同批次名称{" "}
                {report.leakage.shared_batches.join("、") || "无"}；共同来源批次{" "}
                {report.leakage.shared_batch_keys.join("、") || "无"}
                。来源由导入者声明。
              </p>
            </div>
          </Panel>
          <Panel title="逐样本核对">
            <div className="evaluation-body">
              <div className="evaluation-filters">
                <label>
                  评估批次
                  <select
                    aria-label="评估批次"
                    value={batch}
                    onChange={(e) => {
                      setBatch(e.target.value);
                      setPage(0);
                      setSampleId("");
                    }}
                  >
                    <option value="">全部批次</option>
                    {[...new Set(report.samples.map((r) => r.batch))].map(
                      (b) => (
                        <option key={b}>{b}</option>
                      ),
                    )}
                  </select>
                </label>
                <label>
                  评估来源
                  <select
                    aria-label="评估来源"
                    value={group}
                    onChange={(e) => {
                      setGroup(e.target.value);
                      setPage(0);
                      setSampleId("");
                    }}
                  >
                    <option value="">全部来源</option>
                    {Object.entries(cohortLabels).map(([key, label]) => (
                      <option key={key} value={key}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  核对筛选
                  <select
                    aria-label="核对筛选"
                    value={filter}
                    onChange={(e) => {
                      setFilter(e.target.value);
                      setPage(0);
                      setSampleId("");
                    }}
                  >
                    <option value="">全部样本</option>
                    <option value="issue">标签不匹配或检测不可用</option>
                    <option value="unlabeled">至少一种标签未标注</option>
                    <option value="not_run">未运行</option>
                  </select>
                </label>
              </div>
              <div className="evaluation-samples">
                <div>
                  <div className="evaluation-table-wrap">
                    <table className="evaluation-table">
                      <thead>
                        <tr>
                          <th>样本</th>
                          <th>独立缺陷标签</th>
                          <th>检测判定</th>
                          <th>原因标签</th>
                          <th>规则观测</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.slice(page * 10, (page + 1) * 10).map((r) => (
                          <tr
                            key={r.sample_id}
                            className={
                              r.inspection_mismatch || r.rule_mismatch
                                ? "evaluation-issue"
                                : ""
                            }
                          >
                            <td>
                              <button
                                className="text-button"
                                onClick={() => setSampleId(r.sample_id)}
                              >
                                {r.sample_id}
                              </button>
                            </td>
                            <td>{defectLabels[r.defect_label]}</td>
                            <td>{verdict(r.detection_status, r.is_ng)}</td>
                            <td>
                              {r.cause_label === "unknown"
                                ? "未标注"
                                : cause(r.cause_label)}
                            </td>
                            <td>{cause(r.rule_prediction)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {!rows.length && <p className="muted">暂无匹配样本。</p>}
                  <div className="evaluation-pagination">
                    <span>
                      共 {rows.length} 个 · 第 {page + 1} 页
                    </span>
                    <div className="actions">
                      <button
                        disabled={page === 0}
                        onClick={() => setPage((p) => p - 1)}
                      >
                        上一页
                      </button>
                      <button
                        disabled={(page + 1) * 10 >= rows.length}
                        onClick={() => setPage((p) => p + 1)}
                      >
                        下一页
                      </button>
                    </div>
                  </div>
                </div>
                {sample && (
                  <div>
                    <ImageView
                      label="评估样本"
                      meta={sample.sample_id}
                      src={`/api/datasets/${report.dataset_id}/images/${sample.image_index}`}
                    />
                    <p className="muted small">
                      {sample.batch} · {cohortLabels[sample.cohort]} ·
                      软件扰动：{sample.perturbation}
                    </p>
                    <dl className="fact-list">
                      <div>
                        <dt>
                          {report.inspection_source.producer
                            ?.score_semantics === "anomaly_score"
                            ? "异常分数"
                            : "检测分数"}
                        </dt>
                        <dd>
                          {(report.inspection_source.producer
                            ?.score_semantics === "anomaly_score"
                            ? sample.anomaly_score
                            : sample.confidence
                          )?.toFixed(3) ?? "—"}
                        </dd>
                      </div>
                      <div>
                        <dt>缺陷标签</dt>
                        <dd>{defectLabels[sample.defect_label]}</dd>
                      </div>
                      <div>
                        <dt>检测判定</dt>
                        <dd>
                          {verdict(sample.detection_status, sample.is_ng)}
                        </dd>
                      </div>
                    </dl>
                    <AlignmentEvidence alignment={sample.alignment} />
                    <p className="muted small">
                      预测与独立标签分别显示；检测分数不表示合格概率。
                    </p>
                  </div>
                )}
              </div>
            </div>
          </Panel>
          <Panel title="版本对比" action={<GitCompareArrows size={19} />}>
            <div className="evaluation-body">
              <label>
                对比会话
                <select
                  aria-label="对比会话"
                  value={right === session ? "" : right}
                  onChange={(e) => setRight(e.target.value)}
                >
                  <option value="">选择另一回放会话…</option>
                  {runs
                    .filter((r) => r.session !== session)
                    .map((run) => (
                      <option key={run.session} value={run.session}>
                        {runLabel(run)}
                      </option>
                    ))}
                </select>
              </label>
              <p className="muted small">
                A 为当前评估会话，B
                为对比会话。数据集、基线、顺序、阈值和测量实现须一致；检测器与结果版本可不同。分数语义可能不同，不比较分数高低。
              </p>
              {compareError && (
                <div role="alert" className="notice danger">
                  对比读取失败：{compareError}
                </div>
              )}
              {right && right !== session && !comparison && !compareError && (
                <p role="status">正在对齐回放…</p>
              )}
              {comparison && (
                <>
                  {!comparison.comparable ? (
                    <div className="notice danger" role="alert">
                      不能进行同条件对比：{comparison.reasons.join("；")}
                    </div>
                  ) : (
                    <>
                      <div className="actions">
                        <Badge tone="blue">已配对 {comparison.paired} 个</Badge>
                        <Badge>
                          仅 A {comparison.left_only} · 仅 B{" "}
                          {comparison.right_only}
                        </Badge>
                        <button
                          onClick={() =>
                            download(
                              "spark-evaluation-comparison.json",
                              comparison,
                            )
                          }
                        >
                          <Download size={14} />
                          导出版本对比
                        </button>
                      </div>
                      {!comparison.both_completed && (
                        <div className="notice">
                          至少一个回放未完成，仅比较共同已运行样本；完整报告的匹配率不能直接用于版本优劣排名。
                        </div>
                      )}
                      <p>
                        A：{sourceName(comparison.left.inspection_source)} · B：
                        {sourceName(comparison.right.inspection_source)}
                      </p>
                      <p className="muted">
                        状态变化 {comparison.status_changes} · 判定变化{" "}
                        {comparison.binary_enabled
                          ? `${comparison.verdict_changes}/${comparison.both_ok} 个双侧成功结果`
                          : "含演示检测，不比较缺陷判定"}{" "}
                        · 规则观测变化 {comparison.rule_changes}
                      </p>
                      <div className="evaluation-table-wrap">
                        <table className="evaluation-table">
                          <caption>
                            共同已运行样本的计数 · 对比请求时的证据快照
                          </caption>
                          <thead>
                            <tr>
                              <th>会话</th>
                              <th>缺陷标签覆盖</th>
                              <th>FP · 误报</th>
                              <th>FN · 漏检</th>
                              <th>不可用且有标签</th>
                              <th>规则已分类 / 标签</th>
                            </tr>
                          </thead>
                          <tbody>
                            {comparison.paired_summaries?.map(
                              (stats, index) => (
                                <tr key={index}>
                                  <td>{index === 0 ? "A" : "B"}</td>
                                  <td>
                                    {stats.inspection.enabled
                                      ? `${stats.inspection.assessed}/${stats.inspection.labeled}`
                                      : "—"}
                                  </td>
                                  <td>
                                    {stats.inspection.enabled
                                      ? stats.inspection.fp
                                      : "—"}
                                  </td>
                                  <td>
                                    {stats.inspection.enabled
                                      ? stats.inspection.fn
                                      : "—"}
                                  </td>
                                  <td>
                                    {stats.inspection.unavailable_labeled}
                                  </td>
                                  <td>
                                    {stats.rule.assessed}/{stats.rule.labeled}
                                  </td>
                                </tr>
                              ),
                            )}
                          </tbody>
                        </table>
                      </div>
                      <label className="check-label">
                        <input
                          type="checkbox"
                          checked={changesOnly}
                          onChange={(e) => {
                            setChangesOnly(e.target.checked);
                            setComparePage(0);
                          }}
                        />
                        只显示变化样本
                      </label>
                      <div className="evaluation-table-wrap">
                        <table className="evaluation-table">
                          <thead>
                            <tr>
                              <th>样本</th>
                              <th>A 检测</th>
                              <th>B 检测</th>
                              <th>A 规则</th>
                              <th>B 规则</th>
                            </tr>
                          </thead>
                          <tbody>
                            {differences
                              .slice(comparePage * 10, (comparePage + 1) * 10)
                              .map((r) => (
                                <tr key={r.sample_id}>
                                  <td>{r.sample_id}</td>
                                  <td>{verdict(r.left_status, r.left_ng)}</td>
                                  <td>{verdict(r.right_status, r.right_ng)}</td>
                                  <td>{cause(r.left_rule)}</td>
                                  <td>{cause(r.right_rule)}</td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                      {!differences.length && (
                        <p className="muted">暂无匹配的配对样本。</p>
                      )}
                      <div className="evaluation-pagination">
                        <span>
                          共 {differences.length} 个 · 第 {comparePage + 1} 页
                        </span>
                        <div className="actions">
                          <button
                            disabled={comparePage === 0}
                            onClick={() => setComparePage((p) => p - 1)}
                          >
                            上一页
                          </button>
                          <button
                            disabled={
                              (comparePage + 1) * 10 >= differences.length
                            }
                            onClick={() => setComparePage((p) => p + 1)}
                          >
                            下一页
                          </button>
                        </div>
                      </div>
                      <p className="muted small">
                        差异只描述已配对样本，不代表统计显著性或模型收益。模型复核质量需要另行盲测。
                      </p>
                    </>
                  )}
                </>
              )}
            </div>
          </Panel>
        </>
      )}
    </>
  );
}
