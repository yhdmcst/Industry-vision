import { useEffect, useRef, useState } from "react";
import {
  Download,
  Search,
  ArrowUpRight,
  FileCheck2,
  Sparkles,
  Check,
} from "lucide-react";
import { api, download } from "./api";
import { Badge, ImageView, Panel } from "./components";
import type { Bundle, Incident, Session, State } from "./types";
import {
  defectLabels,
  driftLabels,
  metrics,
  outcomes,
  sourceLabels,
  stamp,
  lifecycleLabels,
  closureLabels,
  inspectionStatuses,
} from "./types";
import type { Act } from "./MonitorPage";
import { InspectionEvidence } from "./InspectionResults";
import { useSessionValue } from "./useSessionValue";
import { ImageCompare } from "./ImageCompare";

export function ReviewPage({
  state,
  act,
  initialId,
  onOpened,
}: {
  state: State;
  act: Act;
  initialId?: number;
  onOpened: () => void;
}) {
  const [session, setSession] = useSessionValue(
    "review:session",
    state.session,
  );
  const [sessions, setSessions] = useState<Session[]>([]);
  const [events, setEvents] = useState<Incident[]>([]);
  const [savedSelected, setSelected] = useSessionValue<number | undefined>(
    `review:selected:${session}`,
    undefined,
  );
  const selected = savedSelected;
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [filter, setFilter] = useSessionValue("review:filter", "all");
  const [search, setSearch] = useSessionValue("review:search", "");
  const [pages, setPages] = useSessionValue<number[]>(
    `review:pages:${session}:${filter}:${search}`,
    [],
  );
  const before = pages.at(-1);
  const [nextBefore, setNextBefore] = useState<number | null>(null);
  const [queueLoading, setQueueLoading] = useState(true);
  const [sessionsMore, setSessionsMore] = useState(true);
  const draftKey = `review:draft:${session}:${selected}`;
  const [note, setNote] = useSessionValue(draftKey + ":note", "");
  const [outcome, setOutcome] = useSessionValue(
    draftKey + ":outcome",
    "insufficient_evidence",
  );
  const [context, setContext] = useSessionValue(draftKey + ":context", "");
  const [error, setError] = useState("");
  const [sessionError, setSessionError] = useState("");
  const [queueError, setQueueError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [loading, setLoading] = useState(false);
  const activeEvent = useRef("");
  activeEvent.current = `${session}:${selected}`;
  useEffect(() => {
    if (initialId !== undefined) {
      try {
        sessionStorage.setItem(
          `spark:review:selected:${state.session}`,
          JSON.stringify(initialId),
        );
      } catch {
        /* optional tab storage */
      }
      setSession(state.session);
      if (session === state.session) setSelected(initialId);
      onOpened();
    }
  }, [initialId]);
  useEffect(() => {
    api<Session[]>("/sessions")
      .then((data) => {
        setSessions(data);
        setSessionsMore(data.length === 30);
      })
      .catch((e) => setSessionError(e.message));
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setQueueLoading(true);
    setEvents([]);
    setNextBefore(null);
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const term =
          Object.entries(driftLabels).find(
            ([, label]) => label === search.trim(),
          )?.[0] ?? search.trim();
        const data = await api<{
          items: Incident[];
          next_before: number | null;
        }>(
          `/sessions/${session}/incidents?page=true&limit=50&status=${filter}&search=${encodeURIComponent(term)}${before ? `&before=${before}` : ""}`,
          "GET",
          undefined,
          controller.signal,
        );
        setEvents(data.items);
        setNextBefore(data.next_before);
        setQueueLoading(false);
        setQueueError("");
        if (selected === undefined && data.items.length)
          setSelected(data.items[0].id);
      } catch (e) {
        if (!controller.signal.aborted) {
          setQueueError((e as Error).message);
          setQueueLoading(false);
        }
      }
      if (!controller.signal.aborted) timer = setTimeout(load, 1500);
    };
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [session, selected, filter, search, before]);
  useEffect(() => {
    setBundle(null);
    setDetailError("");
    setLoading(selected !== undefined);
    if (selected === undefined) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        setBundle(
          await api<Bundle>(
            `/sessions/${session}/incidents/${selected}`,
            "GET",
            undefined,
            controller.signal,
          ),
        );
        setLoading(false);
        setDetailError("");
      } catch (e) {
        if (!controller.signal.aborted) {
          setDetailError((e as Error).message);
          setLoading(false);
        }
      }
      if (!controller.signal.aborted) timer = setTimeout(load, 1500);
    };
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [session, selected]);
  const visible = events;
  const payload =
      bundle?.event.id === selected ? bundle?.event.payload : undefined,
    review = bundle?.reviews.at(-1)?.payload,
    assessment = bundle?.assessments.at(-1)?.payload;
  const base = `/sessions/${session}/incidents/${selected}`;
  const timeline = [
    ...(bundle?.lifecycle_events ?? []).map((event) => ({
      ...event,
      text: closureLabels[event.payload.reason] ?? event.payload.reason,
    })),
    ...(bundle?.updates ?? []).map((event) => ({
      ...event,
      text: `新增证据 · ${driftLabels[event.payload.rule_report.drift_type]} · 检测${inspectionStatuses[event.payload.detection.status]}${event.payload.detection.metadata?.result?.error ? ` · ${event.payload.detection.metadata.result.error}` : ""}`,
    })),
  ].sort((left, right) => left.id - right.id);
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>事件复核</h1>
          <p>从发生时的证据出发，留下可追溯的判断。</p>
        </div>
        <button
          disabled={!bundle}
          onClick={() => download(`spark-event-${selected}.json`, bundle)}
        >
          <Download size={16} />
          导出事件证据
        </button>
      </div>
      {[sessionError, queueError, detailError, error]
        .filter(Boolean)
        .map((message, index) => (
          <div key={index} role="alert" className="notice danger">
            {message}
          </div>
        ))}
      <div className="review-layout">
        <aside className="event-list-panel">
          <div className="event-list-header">
            <h2>
              事件队列 <small>{events.length}</small>
            </h2>
            <label className="sr-only" htmlFor="session">
              采集会话
            </label>
            <select
              id="session"
              value={session}
              onChange={(e) => {
                setSession(e.target.value);
              }}
            >
              <option value={state.session}>当前会话</option>
              {sessions
                .filter((s) => s.session !== state.session)
                .map((s) => (
                  <option key={s.session} value={s.session}>
                    历史 · {new Date(s.started * 1000).toLocaleString("zh-CN")}
                  </option>
                ))}
            </select>
            {sessionsMore && (
              <button
                className="text-button"
                onClick={async () => {
                  try {
                    const data = await api<Session[]>(
                      `/sessions?offset=${sessions.length}`,
                    );
                    setSessions([...sessions, ...data]);
                    setSessionsMore(data.length === 30);
                  } catch (e) {
                    setError((e as Error).message);
                  }
                }}
              >
                加载更早会话
              </button>
            )}
            <div className="search-field">
              <Search size={15} />
              <input
                aria-label="搜索事件"
                placeholder="搜索事件或编号…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="segmented">
              <button
                className={filter === "all" ? "active" : ""}
                onClick={() => setFilter("all")}
              >
                全部
              </button>
              <button
                className={filter === "pending" ? "active" : ""}
                onClick={() => setFilter("pending")}
              >
                待复核
              </button>
              <button
                className={filter === "done" ? "active" : ""}
                onClick={() => setFilter("done")}
              >
                已记录
              </button>
            </div>
          </div>
          <div className="event-list">
            {visible.map((e) => (
              <button
                key={e.id}
                className={`event-card ${selected === e.id ? "active" : ""}`}
                onClick={() => setSelected(e.id)}
              >
                <div>
                  <Badge tone={e.assessment ? "green" : "orange"}>
                    {e.assessment ? outcomes[e.assessment.outcome] : "待复核"}
                  </Badge>
                  <small>#{e.id}</small>
                </div>
                <strong>{driftLabels[e.drift_type]}</strong>
                <p>
                  {stamp(e.created)}{" "}
                  <span>
                    帧 {e.frame} · B{e.baseline_generation}
                  </span>
                </p>
                <small>
                  {lifecycleLabels[e.lifecycle.state]} ·{" "}
                  {sourceLabels[e.source]}
                  {e.injected ? " / 软件扰动" : ""}
                </small>
              </button>
            ))}
            {!visible.length && (
              <div className="empty-inline">
                <FileCheck2 />
                <span>
                  {queueLoading
                    ? "正在读取事件…"
                    : queueError
                      ? "事件读取失败，请检查服务"
                      : "暂无匹配事件"}
                </span>
                <small>在监测页标记或触发变化后查看</small>
              </div>
            )}
          </div>
          <div className="list-footer actions">
            <button
              disabled={!pages.length || queueLoading}
              onClick={() => setPages(pages.slice(0, -1))}
            >
              上一页
            </button>
            <span>
              第 {pages.length + 1} 页 · {events.length} 条
            </span>
            <button
              disabled={nextBefore === null || queueLoading}
              onClick={() => {
                if (nextBefore !== null) setPages([...pages, nextBefore]);
              }}
            >
              下一页
            </button>
          </div>
        </aside>
        <div className="event-detail">
          {!payload ? (
            <div className="empty-state">
              <FileCheck2 size={42} />
              <h2>{loading ? "正在读取事件证据…" : "选择一条事件"}</h2>
              <p>查看图像、测量和人工核验记录。</p>
            </div>
          ) : (
            <>
              <div className="detail-heading">
                <div>
                  <span className="eyebrow">EVENT #{selected}</span>
                  <h2>{driftLabels[payload.rule_report.drift_type]}</h2>
                </div>
                <Badge
                  tone={payload.synthetic || payload.injected ? "orange" : ""}
                >
                  {payload.synthetic || payload.injected
                    ? "合成证据"
                    : "真实采集"}
                </Badge>
              </div>
              <Panel
                title="告警生命周期"
                action={
                  <Badge
                    tone={
                      bundle?.lifecycle.state === "active" ? "orange" : "blue"
                    }
                  >
                    {bundle && lifecycleLabels[bundle.lifecycle.state]}
                  </Badge>
                }
              >
                <div
                  className="episode-timeline"
                  data-testid="episode-timeline"
                >
                  {timeline.map((event) => (
                    <p key={event.id} className="muted small">
                      {stamp(event.created)} · 帧 {event.payload.frame} · B
                      {event.payload.baseline_generation}：{event.text}
                    </p>
                  ))}
                </div>
                <p className="muted small">
                  规则恢复与周期终止独立于人工复核。更换基线或采集源仅终止原周期，不能据此认定异常已消失；无恢复记录的历史事件保留未确认状态。
                </p>
              </Panel>
              {payload.sample && (
                <div className="notice">
                  样本 {payload.sample.id} · 批次 {payload.sample.batch} ·
                  导入标签：{defectLabels[payload.sample.label.defect]} /{" "}
                  {payload.sample.label.cause}
                  <br />
                  标签由导入者声明，不参与模型输入。
                  {payload.sample.perturbation !== "none" &&
                    `软件扰动：${payload.sample.perturbation}`}
                </div>
              )}
              <div className="review-evidence">
                <div>
                  <ImageCompare
                    identity={`${session}:${selected}`}
                    images={[
                      {
                        label: "事件图像",
                        src: `data:image/png;base64,${payload.images.current}`,
                      },
                      {
                        label: `基线 B${payload.baseline_generation}`,
                        src: payload.images.baseline
                          ? `data:image/png;base64,${payload.images.baseline}`
                          : null,
                      },
                    ]}
                  />
                  <div className="image-grid thumbnails">
                    {["previous"].map((key) => (
                      <ImageView
                        key={key}
                        compact
                        label={
                          key === "previous"
                            ? "前一采样"
                            : `基线 B${payload.baseline_generation}`
                        }
                        src={
                          payload.images[key]
                            ? `data:image/png;base64,${payload.images[key]}`
                            : null
                        }
                      />
                    ))}
                  </div>
                </div>
                <Panel title="测量事实">
                  <table>
                    <thead>
                      <tr>
                        <th>指标</th>
                        <th>当前</th>
                        <th>基线</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(metrics).map(([key, label]) => (
                        <tr key={key}>
                          <td>{label}</td>
                          <td>
                            {payload.snapshot.current_metrics.image_quality[
                              key
                            ].toFixed(1)}
                          </td>
                          <td>
                            {payload.snapshot.baseline.image_quality[
                              key
                            ].toFixed(1)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="rule-evidence">
                    {payload.rule_report.evidence.map((e, i) => (
                      <div key={i}>
                        <ArrowUpRight size={15} />
                        {e}
                      </div>
                    ))}
                  </div>
                  {payload.snapshot.warmup && (
                    <div className="notice">
                      窗口预热或检测结果不完整，尚无一致性结论。
                    </div>
                  )}
                  {payload.inspection_source && (
                    <InspectionEvidence
                      source={payload.inspection_source}
                      detection={payload.detection}
                      availability={payload.detection_availability}
                    />
                  )}
                  <p className="muted small">
                    事件图像与基线已冻结，后续采样不会覆盖。
                  </p>
                </Panel>
              </div>
              <div className="review-bottom">
                <Panel title="原因假设" action={<Sparkles size={17} />}>
                  <p className="muted small">
                    模型仅接收文本指标，结论需结合现场核验。
                  </p>
                  {bundle?.errors.map((e) => (
                    <div className="notice danger" key={e.id}>
                      {e.payload.error}
                    </div>
                  ))}
                  {review ? (
                    <>
                      <Badge tone="blue">
                        模型假设：{driftLabels[review.analysis.drift_type]}
                      </Badge>
                      <p>{review.analysis.root_cause}</p>
                      {review.evidence_warnings.map((w, i) => (
                        <div className="notice" key={i}>
                          {w}
                        </div>
                      ))}
                      <h3>模型引用的证据</h3>
                      <ul>
                        {review.analysis.evidence.map((v, i) => (
                          <li key={i}>{v}</li>
                        ))}
                      </ul>
                      <h3>竞争解释与验证</h3>
                      <ul>
                        {[
                          ...review.analysis.alternative_causes,
                          ...review.analysis.verification_steps,
                        ].map((v, i) => (
                          <li key={i}>{v}</li>
                        ))}
                      </ul>
                      <details>
                        <summary>人工核验建议</summary>
                        <ul>
                          {review.analysis.recommendations.map((v, i) => (
                            <li key={i}>{v}</li>
                          ))}
                        </ul>
                      </details>
                      <details>
                        <summary>原始模型响应</summary>
                        <pre>{review.raw_response}</pre>
                      </details>
                    </>
                  ) : (
                    <div className="model-empty">
                      <Sparkles size={24} />
                      <span>
                        {state.model.pending
                          ? "模型正在复核快照…"
                          : "该事件尚无模型结论"}
                      </span>
                      <small>
                        {state.model.connected
                          ? "补充现场记录后请求复核"
                          : "可直接人工核验，或在设置中连接本地模型"}
                      </small>
                    </div>
                  )}
                  <label>
                    现场补充记录
                    <textarea
                      value={context}
                      onChange={(e) => setContext(e.target.value)}
                      maxLength={2000}
                      placeholder="例如：近期调整过光源，曝光参数尚未检查。"
                    />
                  </label>
                  <button
                    disabled={
                      !state.model.connected ||
                      state.model.pending ||
                      session !== state.session
                    }
                    onClick={() =>
                      act(base + "/review", { context }, "已提交本地模型复核。")
                    }
                  >
                    <Sparkles size={15} />
                    请求模型复核
                  </button>
                </Panel>
                <Panel title="人工结论" action={<FileCheck2 size={17} />}>
                  {assessment && (
                    <div className="saved-assessment">
                      <Check size={16} />
                      <div>
                        <strong>已记录：{outcomes[assessment.outcome]}</strong>
                        <p>{assessment.note}</p>
                      </div>
                    </div>
                  )}
                  <form
                    onSubmit={async (e) => {
                      e.preventDefault();
                      const target = `${session}:${selected}`;
                      if (
                        await act(
                          base + "/assessment",
                          { outcome, note },
                          "人工复核已保存。",
                        )
                      ) {
                        try {
                          const updated = await api<Bundle>(base);
                          if (activeEvent.current === target)
                            setBundle(updated);
                        } catch (e) {
                          setError((e as Error).message);
                        }
                      }
                    }}
                  >
                    <label>
                      核验结论
                      <select
                        aria-label="核验结论"
                        value={outcome}
                        onChange={(e) => setOutcome(e.target.value)}
                      >
                        {Object.entries(outcomes).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      复核记录
                      <textarea
                        required
                        maxLength={2000}
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        placeholder="记录检查方法、观察结果与仍缺少的证据。"
                      />
                    </label>
                    <p className="muted small">
                      草稿按事件保留在本标签页，切页和刷新可继续编辑；关闭标签页或禁止浏览器存储后可能丢失。保存后才进入证据记录。
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        setNote("");
                        setContext("");
                        setOutcome("insufficient_evidence");
                      }}
                    >
                      清空此事件草稿
                    </button>
                    <button className="primary" type="submit">
                      <Check size={15} />
                      记录人工复核
                    </button>
                  </form>
                  <details>
                    <summary>
                      核验历史 · {bundle?.assessments.length ?? 0} 条
                    </summary>
                    {bundle?.assessments.map((e) => (
                      <p key={e.id}>
                        {stamp(e.created)} · {outcomes[e.payload.outcome]}
                        <br />
                        {e.payload.note}
                      </p>
                    ))}
                  </details>
                </Panel>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
