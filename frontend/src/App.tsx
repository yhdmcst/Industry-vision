import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  Cpu,
  LayoutDashboard,
  Files,
  Layers,
  Settings2,
  Zap,
  ArrowUpRight,
  CircleHelp,
  Bell,
  ChevronRight,
  AlertTriangle,
  X,
  Menu,
  CheckCircle2,
  BarChart3,
} from "lucide-react";
import { api } from "./api";
import type { Incident, State } from "./types";
import { MonitorPage } from "./MonitorPage";
import { ReviewPage } from "./ReviewPage";
import { BaselinePage } from "./BaselinePage";
import { ModelPage } from "./ModelPage";
import { SettingsPage } from "./SettingsPage";
import { EvaluationPage } from "./EvaluationPage";
import "./styles.css";

const pages = [
  { id: "monitor", name: "监测工作台", sub: "Monitor", icon: LayoutDashboard },
  { id: "review", name: "事件复核", sub: "Evidence", icon: Files },
  { id: "baseline", name: "基线与漂移", sub: "Baseline", icon: Layers },
  { id: "evaluation", name: "回放评估", sub: "Evaluation", icon: BarChart3 },
  { id: "models", name: "本地模型", sub: "Models", icon: Cpu },
  { id: "settings", name: "设置与演示", sub: "Settings", icon: Settings2 },
];
export default function App() {
  const initial = location.hash.slice(1);
  const [page, setPage] = useState(
    pages.some((p) => p.id === initial) ? initial : "monitor",
  );
  const [state, setState] = useState<State | null>(null),
    [incidents, setIncidents] = useState<Incident[]>([]);
  const [offline, setOffline] = useState(""),
    [error, setError] = useState(""),
    [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false),
    [menu, setMenu] = useState(false),
    [selectedEvent, setSelectedEvent] = useState<number>();
  const busyRef = useRef(false);
  const stateRef = useRef<State | null>(null);
  const incidentRevision = useRef("");
  const refreshSequence = useRef(0);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    const sequence = ++refreshSequence.current;
    const cached = stateRef.current;
    const payload = await api<
      Omit<State, "history"> & { history?: State["history"] }
    >(
      cached
        ? `/state?history_token=${encodeURIComponent(cached.history_token)}`
        : "/state",
      "GET",
      undefined,
      signal,
    );
    if (sequence !== refreshSequence.current || signal?.aborted) return;
    const next: State = {
      ...payload,
      history: payload.history ?? cached?.history ?? [],
    };
    stateRef.current = next;
    setState(next);
    setOffline("");
    const revision = `${next.session}:${next.event_revision}`;
    if (incidentRevision.current !== revision) {
      const items = await api<Incident[]>(
        `/sessions/${next.session}/incidents`,
        "GET",
        undefined,
        signal,
      );
      if (sequence !== refreshSequence.current || signal?.aborted) return;
      setIncidents(items);
      incidentRevision.current = revision;
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        await refresh(controller.signal);
      } catch (e) {
        if (!controller.signal.aborted) setOffline((e as Error).message);
      }
      if (!controller.signal.aborted) timer = setTimeout(tick, 900);
    };
    void tick();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [refresh]);
  useEffect(() => {
    const listener = () => {
      const id = location.hash.slice(1);
      if (pages.some((p) => p.id === id)) setPage(id);
    };
    addEventListener("hashchange", listener);
    return () => removeEventListener("hashchange", listener);
  }, []);
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(""), 4500);
      return () => clearTimeout(timer);
    }
  }, [toast]);
  const navigate = (id: string) => {
    location.hash = id;
    setPage(id);
    setMenu(false);
  };
  const openReview = (id?: number) => {
    setSelectedEvent(id);
    navigate("review");
  };
  const act = async (
    path: string,
    body?: unknown,
    message?: string,
    method = "POST",
  ) => {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setToast("");
    try {
      await api(path, method, body);
      await refresh();
      if (message) setToast(message);
      return true;
    } catch (e) {
      setError((e as Error).message);
      try {
        await refresh();
      } catch (refreshError) {
        setOffline((refreshError as Error).message);
      }
      return false;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  const pending = incidents.filter((e) => !e.assessment).length;
  return (
    <div className={`app-shell ${menu ? "menu-open" : ""}`}>
      <a className="skip-link" href="#main">
        跳到工作区
      </a>
      <aside className="sidebar">
        <a
          href="#monitor"
          className="brand"
          onClick={() => navigate("monitor")}
        >
          <span className="brand-symbol">
            <Zap size={22} fill="currentColor" />
          </span>
          <span>
            Spark<span className="brand-light">Guard</span>
            <small>VISION OPERATIONS</small>
          </span>
        </a>
        <div className="workspace-label">
          工作空间 <span>LOCAL</span>
        </div>
        <div className="station-switch">
          <span className="station-icon">
            <Activity size={18} />
          </span>
          <div>
            视觉质检工位<small>单工位 · 旁路复核</small>
          </div>
          <ChevronRight size={14} />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="主导航">
          {pages.map((p) => (
            <button
              key={p.id}
              aria-current={page === p.id ? "page" : undefined}
              onClick={() => navigate(p.id)}
            >
              <p.icon size={18} />
              <span>{p.name}</span>
              {p.id === "review" && pending > 0 ? <b>{pending}</b> : null}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card">
            <span className={`status-dot ${offline ? "" : "live"}`} />
            <span>
              端侧服务
              <small>
                {offline
                  ? "连接中断"
                  : !state
                    ? "正在连接"
                    : "本地运行 · 数据留在本机"}
              </small>
            </span>
            <ArrowUpRight size={14} />
          </div>
          <button className="help-link" onClick={() => navigate("settings")}>
            <CircleHelp size={16} />
            运行与使用说明
          </button>
          <div className="sidebar-version">
            <span>本地工作台</span>
          </div>
        </div>
      </aside>
      {menu && (
        <button
          aria-label="关闭导航"
          className="menu-scrim"
          onClick={() => setMenu(false)}
        />
      )}
      <div className="workspace">
        <header className="topbar">
          <div>
            <button
              className="icon-button mobile-menu"
              aria-label="打开导航"
              onClick={() => setMenu(true)}
            >
              <Menu size={20} />
            </button>
            <span className="breadcrumb">
              工作空间 <ChevronRight size={13} />
              <strong>{pages.find((p) => p.id === page)?.name}</strong>
            </span>
          </div>
          <div className="topbar-right">
            <span className={`connection ${offline ? "text-error" : ""}`}>
              <span className={`status-dot ${offline ? "" : "live"}`} />
              {offline
                ? "服务离线"
                : !state
                  ? "正在连接本地服务"
                  : "本地服务已连接"}
            </span>
            <span className="topbar-divider" />
            <button
              className="icon-button"
              aria-label="查看待复核事件"
              onClick={() => openReview()}
            >
              <Bell size={18} />
              {pending > 0 && <i className="notification-dot" />}
            </button>
            <span className="avatar">SG</span>
          </div>
        </header>
        <main id="main" className={busy ? "is-busy" : ""}>
          {state?.maintenance_busy && (
            <div className="notice" role="status">
              工作空间维护进行中。状态仍可查看，新的保存、采集和模型操作需等待完成。
            </div>
          )}
          {offline && (
            <div role="alert" className="notice danger">
              <AlertTriangle size={16} />
              无法连接本地服务，当前数据显示可能已过期。{offline}
            </div>
          )}
          {error && (
            <div role="alert" className="notice danger">
              <AlertTriangle size={16} />
              {error}
              <button
                className="icon-button"
                aria-label="关闭错误"
                onClick={() => setError("")}
              >
                <X size={14} />
              </button>
            </div>
          )}
          {state?.capture_error && (
            <div role="alert" className="notice danger">
              采集失败：{state.capture_error}。当前画面为最后一次成功采样。
            </div>
          )}
          {state?.model.review_error && (
            <div role="alert" className="notice danger">
              模型复核未完成：{state.model.review_error}
            </div>
          )}
          {!state ? (
            <div className="empty-state">
              <Activity size={38} />
              <h1>连接本地工作站</h1>
              <p>正在加载采集状态与证据记录…</p>
            </div>
          ) : (
            <>
              {page === "monitor" && (
                <MonitorPage
                  state={state}
                  incidents={incidents}
                  act={act}
                  openReview={openReview}
                />
              )}
              {page === "review" && (
                <ReviewPage
                  state={state}
                  act={act}
                  initialId={selectedEvent}
                  onOpened={() => setSelectedEvent(undefined)}
                />
              )}
              {page === "baseline" && <BaselinePage state={state} act={act} />}
              {page === "evaluation" && <EvaluationPage state={state} />}
              {page === "models" && <ModelPage state={state} act={act} />}
              {page === "settings" && <SettingsPage state={state} act={act} />}
            </>
          )}
        </main>
        <footer className="app-footer">
          <span>
            <span className="status-dot live" />
            Spark Guard · 工业视觉旁路复核
          </span>
          <span>观测 → 证据 → 人工核验</span>
        </footer>
      </div>
      {toast && (
        <div role="status" className="toast">
          <CheckCircle2 size={17} />
          {toast}
        </div>
      )}
      {busy && (
        <div className="request-progress" role="status">
          正在处理…
        </div>
      )}
    </div>
  );
}
