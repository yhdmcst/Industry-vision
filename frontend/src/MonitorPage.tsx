import { useEffect, useState } from "react";
import { api } from "./api";
import {
  Play,
  Pause,
  ScanLine,
  BookmarkPlus,
  ArrowRight,
  Layers,
  ShieldCheck,
  Activity,
} from "lucide-react";
import { Badge, ImageView, Metric, Panel, Trend } from "./components";
import { driftLabels, metrics, scenarios, stamp } from "./types";
import type { State, Incident } from "./types";
import { InspectionEvidence } from "./InspectionResults";
import { AlertEvidence } from "./AlertEvidence";
import { ImageCompare } from "./ImageCompare";
import { useSessionValue } from "./useSessionValue";

export type Act = (
  path: string,
  body?: unknown,
  message?: string,
  method?: string,
) => Promise<boolean>;
export function MonitorPage({
  state: s,
  incidents,
  act,
  openReview,
}: {
  state: State;
  incidents: Incident[];
  act: Act;
  openReview: (id?: number) => void;
}) {
  const [metric, setMetric] = useSessionValue("monitor:metric", "sharpness");
  const [view, setView] = useSessionValue("monitor:view", "compare");
  const [selectedFrame, setSelectedFrame] = useState<number | null>(null);
  const [linked, setLinked] = useState<Incident[]>([]);
  const [linkError, setLinkError] = useState("");
  const [linkLoading, setLinkLoading] = useState(false);
  useEffect(() => {
    setSelectedFrame(null);
  }, [s.session, s.baseline_generation]);
  useEffect(() => {
    setLinked([]);
    setLinkError("");
    if (selectedFrame === null) return;
    const controller = new AbortController();
    setLinkLoading(true);
    api<Incident[]>(
      `/sessions/${s.session}/incidents?frame=${selectedFrame}&baseline_generation=${s.baseline_generation}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((data) => {
        if (!controller.signal.aborted) setLinked(data);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setLinkError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLinkLoading(false);
      });
    return () => controller.abort();
  }, [selectedFrame, s.session, s.baseline_generation, s.event_revision]);
  const latest = s.latest,
    report = latest?.rule_report,
    quality = report?.metrics.image_quality;
  const selected = s.history.find((f) => f.frame === selectedFrame);
  const imageVersion = `${s.session}-${s.baseline_generation}-${s.frame_count}`;
  const ready = s.baseline !== null;
  const complete = !!s.replay?.completed;
  const pending = incidents.filter((x) => !x.assessment).length;
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>
            监测工作台
            <span className="heading-dot" />
          </h1>
          <p>让每一次变化，都有迹可循。</p>
        </div>
        <div className="actions">
          <button
            disabled={
              !ready ||
              s.running ||
              complete ||
              s.vision_runtime.pending ||
              s.vision_runtime.status === "loading"
            }
            onClick={() => act("/capture", { action: "sample" })}
          >
            <ScanLine size={16} />
            采样一帧
          </button>
          <button
            className="primary"
            disabled={
              !ready ||
              complete ||
              (!s.running &&
                (s.vision_runtime.pending ||
                  s.vision_runtime.status === "loading"))
            }
            onClick={() =>
              act("/capture", { action: s.running ? "pause" : "start" })
            }
          >
            {s.running ? <Pause size={16} /> : <Play size={16} />}
            {s.running ? "暂停监测" : "开始监测"}
          </button>
        </div>
      </div>
      {s.vision_runtime.status === "failed" && (
        <div className="notice danger" role="alert">
          {s.vision_runtime.error}。历史观测保留，当前视觉服务不可用。
        </div>
      )}
      <div className="source-strip">
        <span>
          <span className={`status-dot ${s.running ? "live" : ""}`} />
          {s.vision_runtime.pending
            ? "当前帧视觉推理中"
            : complete
              ? "回放完成"
              : s.running
                ? "持续观测中"
                : "采集已暂停"}
        </span>
        <span>
          {s.replay ? (
            <Badge tone="blue">数据集回放</Badge>
          ) : s.source === "synthetic" ? (
            <Badge tone="orange">合成演示</Badge>
          ) : s.source === "video" ? (
            <Badge>视频输入</Badge>
          ) : (
            <Badge>真实采集</Badge>
          )}{" "}
          {s.replay
            ? `${s.replay.name} · ${s.replay.position}/${s.replay.total}`
            : s.source === "synthetic"
              ? "合成 PCB · 本地指标计算"
              : "本地采集源"}
        </span>
        <span>
          <Layers size={14} />
          {ready
            ? `基线 B${s.baseline_generation} · ${s.baseline?.sample_count} 个样本`
            : "尚未建立基线"}
        </span>
        <span className="source-tail">
          {latest?.sample
            ? `${latest.synthetic ? "合成样本" : "真实采集（声明）"} · ${latest.injected ? `软件扰动：${latest.sample.perturbation}` : "无软件扰动"}`
            : s.scenario !== "none"
              ? `软件扰动：${scenarios[s.scenario]}`
              : "无软件扰动"}
        </span>
      </div>
      <div className="metrics-grid">
        {Object.entries(metrics).map(([key, label]) => (
          <Metric
            key={key}
            title={label}
            value={quality ? quality[key].toFixed(1) : "—"}
            change={
              quality && s.baseline
                ? (quality[key] - s.baseline.image_quality[key]) /
                  Math.max(s.baseline.image_quality[key], 1)
                : undefined
            }
            active={metric === key}
            onClick={() => setMetric(key)}
          />
        ))}
      </div>
      <div className="monitor-grid">
        <div className="monitor-main">
          <Panel
            title="视觉观测"
            action={
              <div className="segmented">
                <button
                  className={view === "compare" ? "active" : ""}
                  onClick={() => setView("compare")}
                >
                  基线对照
                </button>
                <button
                  className={view === "current" ? "active" : ""}
                  onClick={() => setView("current")}
                >
                  当前画面
                </button>
              </div>
            }
          >
            {view === "compare" ? (
              <ImageCompare
                identity={`${s.session}:${s.baseline_generation}`}
                images={[
                  {
                    label: "当前画面",
                    src: ready ? `/api/images/current?v=${imageVersion}` : null,
                  },
                  {
                    label: "基线参考",
                    meta: `B${s.baseline_generation}`,
                    src: ready
                      ? `/api/images/baseline?v=${s.session}-${s.baseline_generation}`
                      : null,
                  },
                ]}
              />
            ) : (
              <div className="image-grid single">
                <ImageView
                  label="当前画面"
                  meta={
                    latest
                      ? latest.sample
                        ? `${latest.sample.id} · ${latest.sample.batch}`
                        : `FRAME ${String(latest.frame).padStart(4, "0")}`
                      : "等待采样"
                  }
                  src={ready ? `/api/images/current?v=${imageVersion}` : null}
                />
                {view === "compare" && (
                  <ImageView
                    label="基线参考"
                    meta={`B${s.baseline_generation}`}
                    src={
                      ready
                        ? `/api/images/baseline?v=${s.session}-${s.baseline_generation}`
                        : null
                    }
                  />
                )}
              </div>
            )}
            <div className="image-footer">
              <span>
                <ScanLine size={13} />
                640 × 480 <i />
                原始色彩 <i />
                {latest ? stamp(latest.created) : "—"}
              </span>
              <button
                className="text-button"
                disabled={!latest}
                onClick={() =>
                  act(
                    "/capture",
                    { action: "bookmark" },
                    "已保存当前帧，可进入事件复核。",
                  )
                }
              >
                <BookmarkPlus size={14} />
                标记待复核
              </button>
            </div>
          </Panel>
          <Panel
            title={`${metrics[metric]}趋势`}
            action={
              <div className="legend">
                <span className="green-line" />
                当前
                <span className="blue-line" />
                基线 <small>最近 {s.history.length} 帧</small>
              </div>
            }
          >
            <Trend
              history={s.history}
              baseline={s.baseline}
              metric={metric}
              selectFrame={setSelectedFrame}
            />
            <div className="chart-footer">
              {selected
                ? `帧 ${selected.frame} · ${metrics[metric]} ${selected.rule_report.metrics.image_quality[metric].toFixed(2)} · ${driftLabels[selected.rule_report.drift_type]}`
                : "点击趋势查看该帧测量值；图像区域保持显示当前采样。"}
              <span>采样帧 →</span>
            </div>
            {selected && (
              <div className="actions">
                {linked.map((event) => (
                  <button key={event.id} onClick={() => openReview(event.id)}>
                    查看关联事件 #{event.id}
                  </button>
                ))}
                {linkLoading && <span role="status">正在查询关联事件…</span>}
                {linkError && (
                  <span className="text-error" role="alert">
                    关联查询失败：{linkError}
                  </span>
                )}
                {!linked.length && !linkLoading && !linkError && (
                  <span className="muted small">此帧暂无关联事件。</span>
                )}
              </div>
            )}
          </Panel>
        </div>
        <aside className="evidence-rail">
          <Panel title="观测结论" action={<Activity size={17} />}>
            <div
              className={`observation-status ${report?.drift_detected || latest?.detection_availability?.unavailable ? "warning" : ""}`}
            >
              <span className="status-dot" />
              {report ? driftLabels[report.drift_type] : "等待测量"}
            </div>
            <p className="rail-description">
              {!report
                ? "尚无有效测量，请先建立基线并采样。"
                : report.drift_detected
                  ? "指标相对基线出现变化，请结合图像和现场记录进一步核验。"
                  : latest?.detection_availability?.unavailable
                    ? "图像观测继续，但检测结果不完整，当前无法判断检测一致性。"
                    : "当前规则未发现显著变化。持续观测不等于确认产品质量合格。"}
            </p>
            <div className="rule-evidence">
              {report?.evidence.map((text, i) => (
                <div key={i}>
                  <span>{String(i + 1).padStart(2, "0")}</span>
                  {text}
                </div>
              ))}
            </div>
            {latest?.warmup && (
              <div className="notice">
                {latest.detection_availability?.unavailable
                  ? "检测结果不完整 · 一致性证据不足"
                  : `窗口预热 ${latest.window_count}/10 帧 · 一致性证据不足`}
              </div>
            )}
            <dl className="fact-list">
              <div>
                <dt>视觉处理</dt>
                <dd>
                  {latest?.vision_ms.toFixed(1) ?? "—"} <small>ms</small>
                </dd>
              </div>
              <div>
                <dt>已采样帧</dt>
                <dd data-testid="frame-count">{s.frame_count}</dd>
              </div>
              <div>
                <dt>配准响应</dt>
                <dd>
                  {report?.metrics.image_drift.registration?.response?.toFixed(
                    3,
                  ) ?? "—"}
                </dd>
              </div>
            </dl>
          </Panel>
          <Panel title="质检结果">
            <InspectionEvidence
              source={s.inspection_source}
              detection={latest?.detection}
              availability={latest?.detection_availability}
            />
          </Panel>
          <AlertEvidence alert={s.alert} ready={ready} />
          <Panel
            title="待复核事件"
            action={<Badge tone={pending ? "orange" : ""}>{pending}</Badge>}
          >
            <div className="mini-events">
              {incidents.slice(0, 3).map((event) => (
                <button key={event.id} onClick={() => openReview(event.id)}>
                  <span
                    className={`event-dot ${event.assessment ? "done" : ""}`}
                  />
                  <span>
                    <strong>{driftLabels[event.drift_type]}</strong>
                    <small>
                      {stamp(event.created)} · 帧 {event.frame}
                    </small>
                  </span>
                  <ArrowRight size={15} />
                </button>
              ))}
              {!incidents.length && (
                <div className="empty-inline">
                  <ShieldCheck size={28} />
                  <span>暂无事件</span>
                  <small>规则变化或人工标记后在此呈现</small>
                </div>
              )}
            </div>
            <button
              className="text-button full-width"
              onClick={() => openReview()}
            >
              打开事件复核 <ArrowRight size={14} />
            </button>
          </Panel>
          <div className="boundary-note">
            <ShieldCheck size={16} />
            <p>
              旁路观察，人工决策
              <br />
              <span>不执行停线、放行或剔除</span>
            </p>
          </div>
        </aside>
      </div>
      {s.source === "synthetic" && (
        <p className="bottom-note">
          合成演示不提供真实缺陷标签，检测结果仅用于演示，不代表产线验证。
        </p>
      )}
    </>
  );
}
