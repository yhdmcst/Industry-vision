import { useEffect, useState } from "react";
import { Download, FileCheck2, Upload } from "lucide-react";
import { api, download } from "./api";
import { Badge, Panel } from "./components";
import { driftLabels } from "./types";

type Dimension = "evidence_faithful" | "actionable" | "unsafe_action";
interface Rating {
  card_id: string;
  evidence_faithful: boolean | null;
  actionable: boolean | null;
  unsafe_action: boolean | null;
  note: string;
}
interface Annotation {
  schema_version: 1;
  study_id: string;
  rubric_id: "review-human-v1";
  reviewer: string;
  independent_reviewer_declared: boolean;
  ratings: Rating[];
}
interface StudySummary {
  id: string;
  name: string;
  planned: number;
  statuses: Record<string, number>;
  coverage: number;
  category_agreement: number | null;
  consistency: number;
  latency_ms: { p50: number | null; p95: number | null };
  status: string;
  sample_support: boolean;
  human: Record<
    Dimension,
    { rated: number; pending: number; rate_assessed: number | null }
  >;
}
interface Report {
  report_sha256: string;
  study_id: string;
  name: string;
  scope: string;
  accepted: boolean;
  unique_roots: number;
  runtime_scope: string;
  source: Record<string, unknown>;
  summaries: StudySummary[];
  pairs: {
    left: string;
    right: string;
    improved: number;
    regressed: number;
    unavailable_pairs: number;
    human: Record<
      Dimension,
      {
        paired_rated: number;
        pending_pairs: number;
        improved: number;
        regressed: number;
      }
    >;
  }[];
  rows: {
    case_id: string;
    candidate_id: string;
    status: string;
    expected_type: string | null;
    analysis: Record<string, unknown> | null;
    error: string;
    measurement_warnings: string[];
  }[];
  annotation: Annotation | null;
}
interface Card {
  card_id: string;
  snapshot: Record<string, unknown>;
  operator_context: string;
  analysis: {
    drift_type: string;
    root_cause: string;
    evidence: string[];
    verification_steps?: string[];
    recommendations: string[];
  };
}
interface Cards {
  study_id: string;
  rubric: Record<string, string>;
  cards: Card[];
}
const pct = (n: number | null) =>
  n === null ? "待评" : `${(n * 100).toFixed(1)}%`;
const labels: Record<Dimension, string> = {
  evidence_faithful: "证据忠实",
  actionable: "步骤可执行",
  unsafe_action: "存在危害建议",
};
const states: Record<string, string> = {
  passed: "门槛通过",
  failed: "未通过",
  insufficient_evidence: "证据不足",
};
const scopes: Record<string, string> = {
  controlled_development: "软件变化开发对照",
  field_development: "现场开发对照",
  field_validation: "现场标签验收",
  fixture: "测试夹具",
};

export function ReviewStudyPanel() {
  const [path, setPath] = useState("");
  const [ratingsPath, setRatingsPath] = useState("");
  const [reports, setReports] = useState<
    Pick<Report, "report_sha256" | "name" | "scope">[]
  >([]);
  const [selected, setSelected] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [cards, setCards] = useState<Cards | null>(null);
  const [ratings, setRatings] = useState<Record<string, Rating>>({});
  const [reviewer, setReviewer] = useState("");
  const [independent, setIndependent] = useState(false);
  const [blind, setBlind] = useState(false);
  const [cardIndex, setCardIndex] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api<typeof reports>("/review-studies", "GET", undefined, controller.signal)
      .then((list) => {
        setReports(list);
        setSelected((id) => id || list[0]?.report_sha256 || "");
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    setReport(null);
    setCards(null);
    setError("");
    setRatings({});
    setDirty(false);
    setCardIndex(0);
    if (!selected) return;
    const controller = new AbortController();
    Promise.all([
      api<Report>(
        `/review-studies/${selected}`,
        "GET",
        undefined,
        controller.signal,
      ),
      api<Cards>(
        `/review-studies/${selected}/cards`,
        "GET",
        undefined,
        controller.signal,
      ),
    ])
      .then(([r, c]) => {
        setReport(r);
        setCards(c);
        setReviewer(r.annotation?.reviewer || "");
        setIndependent(r.annotation?.independent_reviewer_declared || false);
        setRatings(
          Object.fromEntries(
            (r.annotation?.ratings || []).map((v) => [v.card_id, v]),
          ),
        );
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [selected]);
  const card = cards?.cards[cardIndex];
  const rating: Rating | null = card
    ? ratings[card.card_id] || {
        card_id: card.card_id,
        evidence_faithful: null,
        actionable: null,
        unsafe_action: null,
        note: "",
      }
    : null;
  const update = (change: Partial<Rating>) => {
    if (!rating) return;
    setRatings((r) => ({ ...r, [rating.card_id]: { ...rating, ...change } }));
    setDirty(true);
    setMessage("");
  };
  const annotation = (): Annotation => ({
    schema_version: 1,
    study_id: report!.study_id,
    rubric_id: "review-human-v1",
    reviewer,
    independent_reviewer_declared: independent,
    ratings: Object.values(ratings).filter(
      (r) =>
        r.note.trim() &&
        Object.keys(labels).some((d) => r[d as Dimension] !== null),
    ),
  });
  const adopt = async (result: Report) => {
    const list = await api<typeof reports>("/review-studies");
    setReports(list);
    setSelected(result.report_sha256);
    setDirty(false);
  };
  return (
    <Panel title="模型复核评估" action={<FileCheck2 size={19} />}>
      <div className="evaluation-body">
        <p className="muted small">
          固定同一份测量，对比规则、模型及上下文。未知原因、失败和未执行均保留；软件变化只能检查类别响应。
        </p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            setMessage("");
            try {
              const r = await api<Report>("/review-studies/import", "POST", {
                path,
                ratings_path: ratingsPath.trim() || null,
              });
              await adopt(r);
              setMessage("复核实验已导入，评分仍按实际记录计算。");
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            复核实验文件路径
            <input
              aria-label="复核实验文件路径"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="/path/to/study.json"
              required
              disabled={busy || dirty}
            />
          </label>
          <label>
            人工评分文件（可选）
            <input
              aria-label="人工评分文件（可选）"
              value={ratingsPath}
              onChange={(e) => setRatingsPath(e.target.value)}
              placeholder="/path/to/ratings.json"
              disabled={busy || dirty}
            />
          </label>
          <button type="submit" disabled={busy || dirty}>
            <Upload size={15} />
            导入复核实验
          </button>
        </form>
        <label>
          复核报告版本
          <select
            aria-label="复核报告版本"
            value={selected}
            disabled={busy || dirty}
            onChange={(e) => {
              setMessage("");
              setSelected(e.target.value);
            }}
          >
            <option value="">选择复核实验…</option>
            {reports.map((r) => (
              <option key={r.report_sha256} value={r.report_sha256}>
                {r.name} · {scopes[r.scope]}
              </option>
            ))}
          </select>
        </label>
        {error && (
          <div className="notice danger" role="alert">
            {error}
          </div>
        )}
        {message && <p role="status">{message}</p>}
        {!reports.length && !error && (
          <p className="muted">
            尚无复核实验。按部署文档准备固定题库并运行本地模型对照后导入。
          </p>
        )}
        {report && report.report_sha256 === selected && !busy && (
          <>
            <div className="actions">
              <Badge tone={report.accepted ? "green" : "orange"}>
                {report.accepted ? "声明数据满足验收门槛" : "效果尚未验收"}
              </Badge>
              <Badge>{scopes[report.scope]}</Badge>
              <span className="muted small">
                独立根图像 {report.unique_roots} 张；派生视图不增加样本支持
              </span>
              <button onClick={() => setBlind((b) => !b)}>
                {blind ? "退出匿名评分" : "进入匿名评分"}
              </button>
              <button
                onClick={() =>
                  download(`review-report-${selected.slice(0, 8)}.json`, report)
                }
              >
                <Download size={15} />
                下载复核报告
              </button>
            </div>
            {!blind && (
              <>
                <div className="evaluation-table-wrap">
                  <table className="evaluation-table">
                    <caption>同题方法对照 · 窄屏可横向滚动查看全部指标</caption>
                    <thead>
                      <tr>
                        <th>方法</th>
                        <th>成功 / 计划</th>
                        <th>类别一致率</th>
                        <th>内部一致率</th>
                        <th>调用 p50 / p95</th>
                        <th>人工忠实度</th>
                        <th>人工可执行性</th>
                        <th>人工危害率</th>
                        <th>门槛</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.summaries.map((s) => (
                        <tr key={s.id}>
                          <td>{s.name}</td>
                          <td>
                            {s.statuses.ok || 0} / {s.planned}
                          </td>
                          <td>{pct(s.category_agreement)}</td>
                          <td>{pct(s.consistency)}</td>
                          <td>
                            {s.latency_ms.p50 === null
                              ? "不适用"
                              : `${(s.latency_ms.p50 / 1000).toFixed(2)}s / ${((s.latency_ms.p95 || 0) / 1000).toFixed(2)}s`}
                          </td>
                          {Object.keys(labels).map((d) => (
                            <td key={d}>
                              {`${pct(s.human[d as Dimension].rate_assessed)} · ${s.human[d as Dimension].rated}/${s.planned}`}
                            </td>
                          ))}
                          <td>{states[s.status]}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted small">
                  类别一致率按所有有标签的计划案例计算，失败也保留分母；人工比率仅按已评条目，同时显示覆盖。低冲突数不代表证据忠实或建议安全。
                </p>
                <details>
                  <summary>实验来源与范围</summary>
                  <pre>
                    {JSON.stringify(
                      {
                        scope: report.scope,
                        runtime: report.runtime_scope,
                        source: report.source,
                      },
                      null,
                      2,
                    )}
                  </pre>
                </details>
                <details>
                  <summary>逐项结果与失败</summary>
                  {report.rows.map((r) => (
                    <div
                      className="notice"
                      key={`${r.candidate_id}:${r.case_id}`}
                    >
                      <strong>
                        {r.candidate_id} · {r.case_id}
                      </strong>
                      <p>
                        {r.status} · 期望{" "}
                        {r.expected_type === null
                          ? "未知标签"
                          : driftLabels[r.expected_type]}{" "}
                        · 回答{" "}
                        {r.analysis
                          ? driftLabels[String(r.analysis.drift_type)]
                          : "不可用"}
                      </p>
                      {r.error && <p>{r.error}</p>}
                      {r.measurement_warnings.map((w) => (
                        <p key={w}>{w}</p>
                      ))}
                    </div>
                  ))}
                </details>
                <details>
                  <summary>同题增益与退化</summary>
                  {report.pairs.map((p) => (
                    <div
                      className="notice review-pair"
                      key={`${p.left}:${p.right}`}
                    >
                      <strong>
                        {report.summaries.find((s) => s.id === p.left)?.name} →{" "}
                        {report.summaries.find((s) => s.id === p.right)?.name}
                      </strong>
                      <p>
                        类别：改善 {p.improved}，退化 {p.regressed}，不可用配对{" "}
                        {p.unavailable_pairs}。
                      </p>
                      {Object.keys(labels).map((d) => {
                        const metric = p.human[d as Dimension];
                        return (
                          <p key={d}>
                            {labels[d as Dimension]}：
                            {metric.paired_rated === 0
                              ? "待评"
                              : `改善 ${metric.improved}，退化 ${metric.regressed}，已配对 ${metric.paired_rated}`}
                            {`，待配对 ${metric.pending_pairs}`}
                          </p>
                        );
                      })}
                    </div>
                  ))}
                  <p className="muted small">
                    仅描述本题库。危害建议从“有”变“无”计为改善；尚未评分或仅评一侧不计为通过。
                  </p>
                </details>
              </>
            )}
            {blind && cards && (
              <>
                <div className="notice">
                  匿名评分隐藏方法名、期望标签和耗时；此前查看结果或回答措辞仍可能破坏盲法，不能声称双盲。请由未看结果的复核人使用下载评分卡。
                </div>
                <button
                  onClick={() =>
                    download(
                      `review-cards-${report.study_id.slice(0, 8)}.json`,
                      cards,
                    )
                  }
                >
                  <Download size={15} />
                  下载匿名评分卡
                </button>
                <label>
                  实际复核人
                  <input
                    aria-label="实际复核人"
                    value={reviewer}
                    maxLength={200}
                    onChange={(e) => {
                      setReviewer(e.target.value);
                      setDirty(true);
                    }}
                  />
                </label>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={independent}
                    onChange={(e) => {
                      setIndependent(e.target.checked);
                      setDirty(true);
                    }}
                  />
                  声明由独立复核人评分（仅记录声明）
                </label>
                <label>
                  评分卡
                  <select
                    aria-label="评分卡"
                    value={cardIndex}
                    onChange={(e) => setCardIndex(Number(e.target.value))}
                  >
                    {cards.cards.map((c, i) => (
                      <option key={c.card_id} value={i}>
                        {i + 1} / {cards.cards.length} · {c.card_id.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                </label>
                {!cards.cards.length && (
                  <p className="muted">
                    没有成功模型回答可供评分，失败仍保留在计划分母。
                  </p>
                )}
                {card && rating && (
                  <>
                    <p>
                      <strong>{card.analysis.root_cause}</strong>
                    </p>
                    <p>引用证据：{card.analysis.evidence.join("；")}</p>
                    <p>
                      核验步骤：
                      {card.analysis.verification_steps?.join("；") ||
                        "原始回答无独立核验步骤字段，请按原始建议评分"}
                    </p>
                    <p>建议：{card.analysis.recommendations.join("；")}</p>
                    <p>操作员记录：{card.operator_context || "未提供"}</p>
                    <details>
                      <summary>输入测量与完整回答</summary>
                      <pre className="raw-output">
                        {JSON.stringify(
                          { snapshot: card.snapshot, analysis: card.analysis },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                    {Object.keys(labels).map((d) => (
                      <label key={d}>
                        {labels[d as Dimension]}
                        <select
                          aria-label={labels[d as Dimension]}
                          value={
                            rating[d as Dimension] === null
                              ? "unknown"
                              : String(rating[d as Dimension])
                          }
                          onChange={(e) =>
                            update({
                              [d]:
                                e.target.value === "unknown"
                                  ? null
                                  : e.target.value === "true",
                            })
                          }
                        >
                          <option value="unknown">尚未评定</option>
                          <option value="true">是</option>
                          <option value="false">否</option>
                        </select>
                        <span className="muted small">{cards.rubric[d]}</span>
                      </label>
                    ))}
                    <label>
                      评分依据
                      <textarea
                        aria-label="评分依据"
                        maxLength={2000}
                        value={rating.note}
                        onChange={(e) => update({ note: e.target.value })}
                        placeholder="指出具体引用或核验步骤，以及支持或不支持的理由。"
                      />
                    </label>
                  </>
                )}
                <div className="actions">
                  <button
                    disabled={
                      busy ||
                      !reviewer.trim() ||
                      Object.values(ratings).some(
                        (r) =>
                          Object.keys(labels).some(
                            (d) => r[d as Dimension] !== null,
                          ) && !r.note.trim(),
                      )
                    }
                    onClick={async () => {
                      setBusy(true);
                      setError("");
                      setMessage("");
                      try {
                        const r = await api<Report>(
                          `/review-studies/${selected}/ratings`,
                          "POST",
                          annotation(),
                        );
                        await adopt(r);
                        setMessage("评分已保存为报告版本，未评定项继续保留。");
                      } catch (e) {
                        setError((e as Error).message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    保存评分版本
                  </button>
                  <button
                    disabled={!reviewer.trim()}
                    onClick={() =>
                      download("review-ratings.json", annotation())
                    }
                  >
                    下载人工评分
                  </button>
                  {dirty && (
                    <button
                      disabled={busy}
                      onClick={() => {
                        setRatings(
                          Object.fromEntries(
                            (report.annotation?.ratings || []).map((r) => [
                              r.card_id,
                              r,
                            ]),
                          ),
                        );
                        setReviewer(report.annotation?.reviewer || "");
                        setIndependent(
                          report.annotation?.independent_reviewer_declared ||
                            false,
                        );
                        setDirty(false);
                        setMessage("未保存评分已放弃。");
                      }}
                    >
                      放弃未保存评分
                    </button>
                  )}
                </div>
                {dirty && (
                  <p className="muted small">
                    存在未保存评分；保存或放弃后可切换报告。关闭页面会丢失未保存内容。
                  </p>
                )}
              </>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}
