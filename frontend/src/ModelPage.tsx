import { useEffect, useState } from "react";
import { Cpu, Play, Square, RefreshCw, ShieldCheck } from "lucide-react";
import { Panel, Badge, StatusFact } from "./components";
import { VisionPanel } from "./VisionPanel";
import { api } from "./api";
import type { State, ModelPolicy } from "./types";
import type { Act } from "./MonitorPage";

const bytes = (value?: number | null) =>
  value == null ? "待测量" : `${(value / 1024 ** 3).toFixed(2)} GiB`;
const operations: Record<string, string> = {
  check: "正在检查部署条件",
  start: "正在启动模型",
  stop: "正在停止服务",
  restart: "正在重启服务",
  connect: "正在核验连接",
  prepare: "正在准备部署文件",
  validate: "正在推理自检",
  switch: "正在验证候选模型",
  rollback: "正在恢复上一版本",
};
export function ModelPage({ state, act }: { state: State; act: Act }) {
  const m = state.model;
  const [policy, setPolicy] = useState<ModelPolicy>(m.policy);
  const savedPolicy = JSON.stringify(m.policy);
  useEffect(
    () => setPolicy(JSON.parse(savedPolicy) as ModelPolicy),
    [savedPolicy],
  );
  const [name, setName] = useState(m.name);
  const [endpoint, setEndpoint] = useState(m.endpoint);
  const [executable, setExecutable] = useState(m.executable);
  const [log, setLog] = useState({ text: "", error: "" });
  const [showLog, setShowLog] = useState(false);
  useEffect(() => {
    setName(m.name);
    setEndpoint(m.endpoint);
    setExecutable(m.executable);
  }, [m.name, m.endpoint, m.executable]);
  useEffect(() => {
    if (!showLog) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const next = await api<{ text: string }>(
          "/model/logs",
          "GET",
          undefined,
          controller.signal,
        );
        if (!controller.signal.aborted) setLog({ ...next, error: "" });
      } catch (error) {
        if (!controller.signal.aborted)
          setLog((previous) => ({
            ...previous,
            error: (error as Error).message,
          }));
      }
      if (!controller.signal.aborted) timer = setTimeout(tick, 3000);
    };
    void tick();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [showLog]);
  const dirty =
    name !== m.name || endpoint !== m.endpoint || executable !== m.executable;
  const selectionChanged = name !== m.name;
  const busy = !!m.operation || m.pending;
  const resourcesStale =
    !m.resources_checked_at || Date.now() / 1000 - m.resources_checked_at > 15;
  const activeAsset = m.catalog.find((asset) => asset.selected);
  const filesReady =
    m.deployment?.ready && activeAsset?.file_status === "checked";
  const nextStep = busy
    ? "当前任务进行中；切换页面后仍可回来查看进度。"
    : m.stale
      ? "连接状态已过期，请核验连接后再使用模型。"
      : m.connected
        ? m.validation
          ? "复核服务在线，可前往事件复核；模型回答仍需人工核验。"
          : "服务在线，建议执行推理自检确认输出格式可用。"
        : filesReady
          ? "部署文件上次检查通过，下一步启动本地服务。"
          : "先检查部署条件；文件未准备时下载模型，已有外部服务则核验连接。";
  const run = (action: string) =>
    void act(
      `/model/${action}`,
      undefined,
      "操作已提交，状态将在页面更新。",
      "POST",
    );
  const suggestedAction = m.stale
    ? "connect"
    : m.connected
      ? m.validation
        ? null
        : "validate"
      : filesReady
        ? "start"
        : "check";
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">模型管理</div>
          <h1>本地模型</h1>
          <p>
            准备、运行和维护本机复核模型。模型提出原因假设，结论仍需人工核验。
          </p>
        </div>
        <Badge>
          <ShieldCheck size={13} />
          仅本机
        </Badge>
      </div>
      <div className="model-overview" aria-label="模型状态概览">
        <StatusFact
          title="部署文件"
          value={
            m.deployment
              ? m.deployment.ready
                ? "上次检查通过"
                : "尚未准备完成"
              : "尚未检查"
          }
          source="最近文件检查"
          observedAt={m.deployment?.checked_at}
        />
        <StatusFact
          title="服务连接"
          value={
            m.stale
              ? "等待重新核验"
              : m.connected
                ? "已连接"
                : m.checked_at
                  ? "未连接"
                  : "尚未核验"
          }
          source="周期连接探测"
          observedAt={m.checked_at}
          stale={m.stale}
          tone={m.connected ? "green" : ""}
        />
        <StatusFact
          title="模型驻留"
          value={
            m.connected && m.resident_checked_at && !m.health_error
              ? m.loaded.length
                ? "已加载到内存"
                : "当前未驻留"
              : "未知"
          }
          source="运行时查询"
          observedAt={m.resident_checked_at}
          stale={m.stale}
        />
        <StatusFact
          title="推理自检"
          value={m.validation ? "最近自检通过" : "尚未执行"}
          source="最近一次真实调用"
          observedAt={m.validation?.created}
        />
      </div>
      <div className="notice model-guidance" role="status">
        <span>{nextStep}</span>
        {suggestedAction && (
          <button
            disabled={
              busy ||
              dirty ||
              (suggestedAction === "start" && !m.runtime_plan.start_supported)
            }
            onClick={() => run(suggestedAction)}
          >
            {
              {
                connect: "重新核验连接",
                validate: "执行推理自检",
                start: "启动已准备的服务",
                check: "检查当前部署",
              }[suggestedAction]
            }
          </button>
        )}
      </div>
      <div className="settings-grid model-grid">
        <Panel title="复核模型" action={<Cpu size={19} />}>
          <div className="model-status">
            <Badge tone={m.connected ? "green" : ""}>
              {m.operation
                ? operations[m.operation]
                : m.connected
                  ? "服务可用"
                  : m.stale
                    ? "状态待更新"
                    : "服务未连接"}
            </Badge>
            <span className="muted small">
              {m.owned ? "由工作台管理" : m.connected ? "外部服务" : "尚未启动"}
            </span>
          </div>
          <label>
            模型名称
            <select
              aria-label="模型名称"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
            >
              <option value="spark-drift:1.7b-q4">
                Spark-X2.5 · 1.7B · 资源优先
              </option>
              <option value="spark-drift:4b-q4">
                Spark-X2.5 · 4B · 需更多内存
              </option>
            </select>
          </label>
          <p className="muted small">
            分析观测指标，不直接读取图像或控制生产设备。
          </p>
          <button
            disabled={
              busy || !dirty || m.owned || (selectionChanged && !!m.validation)
            }
            onClick={() =>
              void act(
                "/model/configure",
                { name, endpoint, executable },
                "模型选择已保存。",
              )
            }
          >
            保存模型选择
          </button>
          <p className="muted small">
            当前模型：{m.name.includes("4b") ? "4B" : "1.7B"} ·{" "}
            {m.validation
              ? `最近推理自检通过（${new Date(m.validation.created * 1000).toLocaleString("zh-CN")}）`
              : "尚未执行推理自检"}
          </p>
          <div className="model-actions">
            <button
              disabled={busy || !m.connected || selectionChanged}
              onClick={() => run("validate")}
            >
              推理自检
            </button>
            <button
              disabled={
                busy ||
                !m.connected ||
                !selectionChanged ||
                endpoint !== m.endpoint ||
                executable !== m.executable
              }
              onClick={() =>
                void act(
                  "/model/switch",
                  { name },
                  "正在验证候选模型，通过后才切换。",
                  "POST",
                )
              }
            >
              验证并切换候选
            </button>
            <button
              disabled={busy || !m.connected || !m.previous_name}
              onClick={() => run("rollback")}
            >
              恢复上一版本
            </button>
          </div>
          <p className="muted small">
            自检确认模型能生成可解析的复核结果，不代表诊断正确率。候选失败会保留当前选择。
          </p>
          {dirty && (
            <p className="muted small">
              候选模型可先下载准备；服务可用后点击“验证并切换候选”。连接设置变更请先保存。
            </p>
          )}
          <div className="model-actions">
            <button disabled={busy || dirty} onClick={() => run("check")}>
              <ShieldCheck size={15} />
              检查部署条件
            </button>
            <button
              disabled={
                busy || dirty || m.owned || !m.runtime_plan.start_supported
              }
              onClick={() => run("start")}
            >
              <Play size={15} />
              启动本地服务
            </button>
            <button disabled={busy || !m.owned} onClick={() => run("restart")}>
              <RefreshCw size={15} />
              重启服务
            </button>
            <button disabled={busy || !m.owned} onClick={() => run("stop")}>
              <Square size={15} />
              停止本地服务
            </button>
            <button
              disabled={busy || dirty}
              onClick={() =>
                void act(
                  "/model/connect",
                  { name, endpoint, executable },
                  "连接已核验。",
                  "POST",
                )
              }
            >
              核验连接
            </button>
          </div>
          {m.operation && (
            <p role="status">{operations[m.operation]}；切换页面不取消操作。</p>
          )}
          {m.operation &&
            [
              "check",
              "start",
              "restart",
              "prepare",
              "validate",
              "switch",
              "rollback",
            ].includes(m.operation) && (
              <button onClick={() => run("cancel")}>取消操作</button>
            )}
          {m.pending && (
            <p className="muted">复核进行中，请等待完成再维护模型。</p>
          )}
          {dirty && (
            <p className="muted small">
              当前有未保存的选择或连接设置；检查、启动与核验连接须先保存。已通过自检的模型请使用验证切换。
            </p>
          )}
          {!m.owned && (
            <p className="muted small">重启和停止仅对工作台启动的服务开放。</p>
          )}
          {m.fault ? (
            <div role="alert" className="notice danger">
              <strong>{m.fault.message}</strong>
              <p>{m.fault.remedy}</p>
              <p className="small">{m.fault.impact}</p>
            </div>
          ) : (
            m.error && (
              <div role="alert" className="notice danger">
                {m.error}
              </div>
            )
          )}
          {m.log_error && (
            <div role="alert" className="notice danger">
              服务日志未能保存，请检查磁盘空间与目录权限。模型运行状态请以连接检查为准。
            </div>
          )}
          {m.health_error && (
            <div className="notice danger">
              模型状态未能更新，请核验连接或查看维护详情。
            </div>
          )}
          <p className="muted small">
            外部服务仅支持连接。关闭浏览器不会停止服务；退出工作台会停止其创建的服务。
          </p>
        </Panel>
        <Panel title="部署与设备">
          <p className="muted small">
            以下是运行工作台后端的设备，由本机探测取得。浏览器所在设备不参与部署判断。
          </p>
          <button
            disabled={busy || !m.runtime_plan.prepare_supported}
            onClick={() =>
              void act("/model/prepare", { name }, "正在准备所选模型。", "POST")
            }
          >
            下载并准备模型
          </button>
          {m.progress && m.operation && (
            <p role="status">
              {m.progress.phase}
              {m.progress.total_bytes
                ? ` · ${Math.round(((m.progress.completed_bytes || 0) / m.progress.total_bytes) * 100)}%`
                : ""}
            </p>
          )}
          <p className="muted small">
            使用固定版本官方文件，下载可续传；完成后点击启动。不会覆盖损坏的已有文件。
          </p>
          <p className="muted small">
            准备对象：{name.includes("4b") ? "Spark 4B" : "Spark 1.7B"}
            。选择候选只改变准备对象，通过推理验证才会切换当前模型。
          </p>
          <div className="model-assets" aria-label="复核模型资产">
            {m.catalog.map((asset) => (
              <div className="operation-record" key={asset.name}>
                <strong>{asset.title}</strong>{" "}
                <Badge tone={asset.selected ? "blue" : ""}>
                  {asset.selected ? "当前使用" : "可选模型"}
                </Badge>
                <p className="small">
                  {asset.purpose} · {asset.quantization} ·{" "}
                  {bytes(asset.size_bytes)}
                </p>
                <p className="small">
                  文件：
                  {
                    (
                      {
                        missing: "尚未下载",
                        incomplete: "文件大小不符",
                        changed: "文件发生变化，需重新检查",
                        checked: "最近完整性检查通过",
                        unchecked: "文件存在，待完整性检查",
                        invalid: "最近完整性检查未通过",
                      } as Record<string, string>
                    )[asset.file_status]
                  }
                </p>
                {asset.checked_at && (
                  <p className="muted small">
                    最近检查：
                    {new Date(asset.checked_at * 1000).toLocaleString("zh-CN")}
                  </p>
                )}
                <details>
                  <summary>来源与版本</summary>
                  <p className="model-path small">
                    {asset.source} · {asset.license} · {asset.revision}
                  </p>
                </details>
              </div>
            ))}
          </div>
          <dl className="fact-list">
            <div>
              <dt>工作台所在设备</dt>
              <dd>{m.runtime_plan.label}</dd>
            </div>
            <div>
              <dt>部署文件</dt>
              <dd>
                {m.deployment
                  ? m.deployment.ready
                    ? "最近检查通过"
                    : "尚未准备完成"
                  : "待检查"}
              </dd>
            </div>
            <div>
              <dt>模型驻留</dt>
              <dd>
                {m.connected && m.resident_checked_at && !m.health_error
                  ? m.loaded.length
                    ? "已加载到内存"
                    : "等待下次复核加载"
                  : "未知"}
              </dd>
            </div>
            {m.connected &&
              !m.stale &&
              !m.health_error &&
              m.loaded.map((model) => (
                <div key={model.name}>
                  <dt>当前模型 / 加速内存</dt>
                  <dd>
                    {bytes(model.size)} / {bytes(model.size_vram)}
                  </dd>
                </div>
              ))}
            <div>
              <dt>整机可用内存</dt>
              <dd>
                {resourcesStale
                  ? "待更新"
                  : bytes(m.resources.memory_available_bytes)}
              </dd>
            </div>
            <div>
              <dt>磁盘可用空间</dt>
              <dd>
                {resourcesStale ? "待更新" : bytes(m.resources.disk_free_bytes)}
              </dd>
            </div>
          </dl>
          <p className="muted small">
            设备资源采样：
            {m.resources_checked_at
              ? new Date(m.resources_checked_at * 1000).toLocaleTimeString(
                  "zh-CN",
                )
              : "等待首次探测"}
            {resourcesStale ? " · 已过期" : ""}。每 {m.health_interval_seconds}{" "}
            秒刷新；文件完整性与推理自检仅在执行检查时更新。
          </p>
          <p className="muted small">
            文件检查通过后，仍需启动服务并执行推理检查。内存数据包含设备上的其他应用。
          </p>
          <p className="muted small">
            模型大小与加速内存来自服务的当前驻留报告，不代表独显型号或整机内存占用。
          </p>
        </Panel>
        <Panel title="运行策略">
          <p className="muted small">
            已保存配置 · 应用于后续请求。修改后点击保存生效。
          </p>
          <label>
            运行方案
            <select
              aria-label="运行方案"
              value={policy.profile}
              disabled={busy}
              onChange={(e) =>
                setPolicy({
                  ...policy,
                  profile: e.target.value,
                  ...m.policy_presets[e.target.value],
                })
              }
            >
              <option value="resource">资源优先</option>
              <option value="balanced">均衡</option>
              <option value="responsive">频繁复核</option>
              <option value="custom">自定义</option>
            </select>
          </label>
          <p className="muted small">
            资源优先会在回答结束后释放模型；频繁复核延长驻留以减少重新加载。均不保证推理速度或设备资源充足。
          </p>
          <label>
            空闲驻留（分钟）
            <input
              aria-label="空闲驻留"
              type="number"
              min="0"
              max="60"
              disabled={busy}
              value={policy.keep_alive_minutes}
              onChange={(e) =>
                setPolicy({
                  ...policy,
                  profile: "custom",
                  keep_alive_minutes: Number(e.target.value),
                })
              }
            />
          </label>
          <label>
            推理等待时限（秒）
            <input
              aria-label="推理等待时限"
              type="number"
              min="30"
              max="600"
              disabled={busy}
              value={policy.timeout_seconds}
              onChange={(e) =>
                setPolicy({
                  ...policy,
                  profile: "custom",
                  timeout_seconds: Number(e.target.value),
                })
              }
            />
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              disabled={busy}
              checked={policy.autostart}
              onChange={(e) =>
                setPolicy({ ...policy, autostart: e.target.checked })
              }
            />
            随工作台启动模型服务
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              disabled={busy}
              checked={policy.auto_restart}
              onChange={(e) =>
                setPolicy({ ...policy, auto_restart: e.target.checked })
              }
            />
            服务故障后自动恢复
          </label>
          <button
            disabled={busy || JSON.stringify(policy) === savedPolicy}
            onClick={() =>
              void act(
                "/model/policy",
                policy,
                "运行策略已保存；推理设置用于下一次请求，自动启动在下次工作台启动时生效。",
                "POST",
              )
            }
          >
            保存运行策略
          </button>
          <p className="muted small">
            自动恢复仅处理工作台创建的服务，连续三次检查失败后尝试；10
            分钟内最多 3 次。失败复核须人工重试。浏览器关闭不等于退出工作台。
          </p>
          {m.recovery.message && <p role="status">{m.recovery.message}</p>}
        </Panel>
        <VisionPanel state={state} act={act} />
        <Panel title="维护详情">
          {m.task_error && (
            <p role="alert" className="notice danger">
              {m.task_error}
            </p>
          )}
          <details>
            <summary>最近操作记录</summary>
            {m.tasks.length ? (
              m.tasks.map((task) => (
                <div className="operation-record" key={task.id}>
                  <strong>
                    {(
                      {
                        check: "部署检查",
                        start: "启动服务",
                        stop: "停止服务",
                        restart: "重启服务",
                        connect: "核验连接",
                        prepare: "准备文件",
                        validate: "推理自检",
                        switch: "模型切换",
                        rollback: "模型回滚",
                      } as Record<string, string>
                    )[task.action] || task.action}
                  </strong>
                  <Badge
                    tone={
                      task.status === "failed" || task.status === "interrupted"
                        ? "orange"
                        : task.status === "succeeded"
                          ? "green"
                          : ""
                    }
                  >
                    {(
                      {
                        running: "进行中",
                        cancelling: "正在取消",
                        succeeded: "已完成",
                        failed: "失败",
                        cancelled: "已取消",
                        interrupted: "重启中断",
                      } as Record<string, string>
                    )[task.status] || task.status}
                  </Badge>
                  <p className="small">
                    {task.target.includes("4b") ? "4B" : "1.7B"} ·{" "}
                    {new Date(task.created * 1000).toLocaleString("zh-CN")} ·{" "}
                    {task.stage}
                  </p>
                  {task.error && (
                    <p className="small text-error">{task.error}</p>
                  )}
                </div>
              ))
            ) : (
              <p className="muted small">
                暂无维护操作。完成和失败结果将在此保留，切页不会丢失。
              </p>
            )}
          </details>
          <details>
            <summary>连接与运行时设置</summary>
            <label>
              本地服务
              <input
                value={endpoint}
                onChange={(e) => setEndpoint(e.target.value)}
                disabled={busy || m.owned}
              />
            </label>
            <label>
              运行时路径
              <input
                aria-label="运行时路径"
                value={executable}
                onChange={(e) => setExecutable(e.target.value)}
                disabled={busy || m.owned}
                placeholder="留空自动发现；或填写完整绝对路径"
              />
            </label>
            <p className="muted small">{m.runtime_plan.guidance}</p>
            <pre className="model-log">
              {m.runtime_plan.install_commands
                .concat(
                  `python scripts/download_model.py --size ${name.includes("4b") ? "4b" : "1.7b"}`,
                )
                .join("\n")}
            </pre>
          </details>
          <details>
            <summary>检查记录与故障原因</summary>
            <p>
              最近核验：
              {m.checked_at
                ? new Date(m.checked_at * 1000).toLocaleString("zh-CN")
                : "尚未执行"}
            </p>
            <p className="model-path">
              {m.fault?.detail || m.error || m.health_error || "暂无故障"}
            </p>
            <dl className="fact-list">
              <div>
                <dt>服务版本</dt>
                <dd>{m.details.runtime_version || "尚未核验"}</dd>
              </div>
              <div>
                <dt>模型规模</dt>
                <dd>{m.details.parameter_size || "尚未核验"}</dd>
              </div>
              <div>
                <dt>文件完整性</dt>
                <dd>
                  {m.deployment?.weight_verified
                    ? "最近校验通过"
                    : "尚未通过校验"}
                </dd>
              </div>
            </dl>
          </details>
          <button onClick={() => setShowLog(!showLog)} aria-expanded={showLog}>
            {showLog ? "收起服务日志" : "查看服务日志"}
          </button>
          {showLog && (
            <>
              <p className="text-error">{log.error}</p>
              <pre className="model-log" aria-label="服务日志">
                {log.text || "暂无本工作台服务日志。"}
              </pre>
              <p className="muted small">日志自动轮转，最多保留约 4 MiB。</p>
            </>
          )}
          <p>
            <a href="/api/diagnostics" download>
              下载诊断包
            </a>
          </p>
          <p className="muted small">
            包含本机模型配置、状态和近期日志，不包含图像或复核内容。分享前请检查其中的路径。
          </p>
        </Panel>
      </div>
      <DiagnosticsPanel />
    </>
  );
}
import { DiagnosticsPanel } from "./DiagnosticsPanel";
