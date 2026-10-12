import { useEffect, useState } from "react";
import { Layers, RefreshCw, Trash2, Crosshair } from "lucide-react";
import { Badge, Distribution, Panel, Trend } from "./components";
import { api } from "./api";
import type { Baseline, EvidenceEvent, State } from "./types";
import { metrics, sourceLabels, qualityReasons } from "./types";
import type { Act } from "./MonitorPage";
import { AlertEvidence } from "./AlertEvidence";

export function BaselinePage({ state: s, act }: { state: State; act: Act }) {
  const [metric, setMetric] = useState("sharpness"),
    [note, setNote] = useState("");
  const [count, setCount] = useState(20),
    [confirm, setConfirm] = useState(false);
  const [versions, setVersions] = useState<EvidenceEvent<Baseline>[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    api<EvidenceEvent<Baseline>[]>("/baselines")
      .then(setVersions)
      .catch((e) => setError(e.message));
  }, [s.session, s.baseline_generation]);
  const b = s.baseline,
    q = s.latest?.rule_report.metrics.image_quality;
  const history = s.history.slice(-30),
    registration = s.latest?.rule_report.metrics.image_drift.registration;
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>基线与漂移</h1>
          <p>把变化放回参考坐标，判断哪些信号值得关注。</p>
        </div>
        <Badge tone={b ? "blue" : "orange"}>
          <Layers size={13} />
          {b ? `当前基线 B${b.generation}` : "未建立基线"}
        </Badge>
      </div>
      {error && <div className="notice danger">{error}</div>}
      {s.baseline_attempt?.status === "rejected" && (
        <div
          className="notice danger baseline-rejection"
          role="alert"
          data-testid="baseline-rejected"
        >
          <strong>基线未替换</strong> · {s.baseline_attempt.error}
          <p>
            已通过质量门 {s.baseline_attempt.valid_samples}/
            {s.baseline_attempt.requested_samples} 帧。
            {s.baseline_attempt.retained_generation !== null
              ? `当前继续保留 B${s.baseline_attempt.retained_generation}，监测已暂停，可检查取景后重试。`
              : "当前仍无基线，请检查取景后重试。"}
          </p>
          {s.baseline_attempt.rejected_samples.length > 0 && (
            <details>
              <summary>查看拒绝样本</summary>
              {s.baseline_attempt.rejected_samples.map((sample) => (
                <p key={sample.index}>
                  第 {sample.index} 帧：
                  {sample.reasons
                    .map((reason) => qualityReasons[reason] ?? reason)
                    .join(" / ")}
                </p>
              ))}
            </details>
          )}
        </div>
      )}
      {!b && (
        <div className="notice">
          未建立基线。请先确认取景与工况，再采集正常参考样本。
        </div>
      )}
      <div className="baseline-layout">
        <div>
          <div className="summary-row">
            <div>
              <small>参考样本</small>
              <strong>
                {b?.sample_count ?? "—"} <span>帧</span>
              </strong>
            </div>
            <div>
              <small>当前窗口</small>
              <strong>
                {s.latest?.window_count ?? 0} <span>帧</span>
              </strong>
            </div>
            <div>
              <small>采集来源</small>
              <strong className="source-value">
                {sourceLabels[s.source]}{" "}
                {s.source === "synthetic" && (
                  <Badge tone="orange">合成演示</Badge>
                )}
              </strong>
            </div>
          </div>
          <Panel
            title="基线与最新测量"
            action={
              <small className="muted">
                {b
                  ? new Date(b.created * 1000).toLocaleString("zh-CN")
                  : "等待基线"}
              </small>
            }
          >
            <div className="table-scroll">
              <table className="comparison-table">
                <thead>
                  <tr>
                    <th>观测指标</th>
                    <th>参考基线</th>
                    <th>最新测量</th>
                    <th>相对变化</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(metrics).map(([key, label]) => {
                    const delta =
                      b && q
                        ? (q[key] - b.image_quality[key]) /
                          Math.max(b.image_quality[key], 1)
                        : undefined;
                    return (
                      <tr
                        key={key}
                        onClick={() => setMetric(key)}
                        className={metric === key ? "selected-row" : ""}
                      >
                        <td>
                          <button
                            className="table-metric"
                            onClick={() => setMetric(key)}
                          >
                            {label}
                          </button>
                        </td>
                        <td>{b?.image_quality[key].toFixed(2) ?? "—"}</td>
                        <td>{q?.[key].toFixed(2) ?? "—"}</td>
                        <td
                          className={
                            delta !== undefined && Math.abs(delta) > 0.2
                              ? "text-warning"
                              : ""
                          }
                        >
                          {delta === undefined
                            ? "—"
                            : `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(1)}%`}
                        </td>
                        <td>
                          <span className="muted">
                            {delta === undefined ? "尚无测量" : "数值对照"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="table-footnote">
              相对变化分母采用 max(基线均值, 1)。数值对照不等于统计显著性检验。
            </p>
          </Panel>
          <div className="two-charts">
            <Panel title={`${metrics[metric]}趋势`}>
              <Trend history={history} baseline={b} metric={metric} />
            </Panel>
            <Panel title="样本分布">
              {b && q && b.quality_samples?.length ? (
                <Distribution
                  reference={b.quality_samples}
                  current={history.map(
                    (f) => f.rule_report.metrics.image_quality,
                  )}
                  metric={metric}
                />
              ) : (
                <div className="empty-inline">采样后显示分布对照</div>
              )}
            </Panel>
          </div>
          {s.latest?.warmup && (
            <div className="notice">
              当前窗口 {s.latest.window_count} 帧。一致性统计至少需要 10
              帧且窗口内检测结果全部可用，当前证据不足。
            </div>
          )}
          <Panel title="位置与配准" action={<Crosshair size={18} />}>
            {registration && registration.response > 0.25 ? (
              <div className="registration">
                <div>
                  <small>水平位移</small>
                  <strong>
                    {registration.shift_x.toFixed(2)} <span>px</span>
                  </strong>
                </div>
                <div>
                  <small>垂直位移</small>
                  <strong>
                    {registration.shift_y.toFixed(2)} <span>px</span>
                  </strong>
                </div>
                <div>
                  <small>配准响应</small>
                  <strong>{registration.response.toFixed(3)}</strong>
                </div>
              </div>
            ) : (
              <div className="notice">
                {registration
                  ? "配准响应不高于 0.25，位移依据不可靠。"
                  : "尚无配准结果，采样后查看。"}
              </div>
            )}
            <p className="muted small">
              位置变化规则要求位移大于 8 px，且配准响应大于
              0.25。以上是演示规则，不是工业验收标准。
            </p>
          </Panel>
        </div>
        <aside>
          <Panel
            title="基线质量门"
            action={
              <Badge tone={b?.quality_gate ? "blue" : "orange"}>
                {b?.quality_gate
                  ? "全部样本通过"
                  : b
                    ? "历史基线无逐帧质量记录"
                    : "等待基线"}
              </Badge>
            }
          >
            <dl className="fact-list">
              <div>
                <dt>有效参考样本</dt>
                <dd>
                  {b?.quality_gate
                    ? `${b.quality_gate.valid_samples}/${b.sample_count}`
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>亮度门限</dt>
                <dd>10 &lt; 均值 &lt; 245</dd>
              </div>
              <div>
                <dt>对比度门限</dt>
                <dd>≥ 1</dd>
              </div>
            </dl>
            <p className="muted small">
              逐帧检查，任一帧拒绝则不发布新基线。检测结果必须全部成功；这些是演示取景质量门，不验证产品正常、基线稳定性或现场适用性。
            </p>
          </Panel>
          <AlertEvidence alert={s.alert} ready={!!b} />
          <Panel title="建立参考基线" action={<Layers size={18} />}>
            <p className="muted small">
              {s.replay
                ? "回放基线由数据集清单固定。重新建立回放会创建新会话，历史证据保留。"
                : "采集期间暂停监测，不应用软件扰动。候选基线通过校验并保存后才替换；失败保留旧基线与告警周期。"}
            </p>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (
                  confirm &&
                  (await act(
                    "/baseline",
                    { count, note },
                    "新基线已建立，请采样当前窗口。",
                  ))
                )
                  setConfirm(false);
              }}
            >
              <label>
                样本数量
                <input
                  type="number"
                  min={10}
                  max={100}
                  value={count}
                  onChange={(e) => setCount(Number(e.target.value))}
                  required
                />
              </label>
              <label>
                基线说明
                <textarea
                  value={note}
                  maxLength={2000}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="工位、取景、光源与产品批次…"
                />
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={confirm}
                  onChange={(e) => setConfirm(e.target.checked)}
                  required
                />
                确认当前取景适合作为参考基线
              </label>
              <button
                className="primary full-width"
                disabled={!confirm || !!s.replay}
                type="submit"
              >
                <RefreshCw size={15} />
                建立新基线
              </button>
            </form>
            <details>
              <summary>清空当前基线</summary>
              <p className="muted small">
                清空后需重建基线才能监测，不删除历史事件。
              </p>
              <button
                className="danger-button"
                disabled={!b || !!s.replay}
                onClick={() =>
                  act(
                    "/baseline",
                    undefined,
                    "基线已清空，监测已暂停。",
                    "DELETE",
                  )
                }
              >
                <Trash2 size={14} />
                重置基线
              </button>
            </details>
          </Panel>
          <Panel title="基线版本">
            <div className="version-list">
              {[...versions].reverse().map((e) => (
                <div key={e.id}>
                  <span className="version-node" />
                  <strong>B{e.payload.generation}</strong>
                  <div>
                    <p>{e.payload.operator_note || "未填写现场说明"}</p>
                    <small>
                      {e.payload.sample_count} 帧 ·{" "}
                      {new Date(e.created * 1000).toLocaleString("zh-CN")}
                    </small>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
          <p className="bottom-note">
            固定合成样本可能没有自然波动，不能据此估计真实产线分布。
          </p>
        </aside>
      </div>
    </>
  );
}
