import { useEffect, useState } from "react";
import { api } from "./api";
import { Panel } from "./components";

interface Diagnostic {
  environment: {
    system: string;
    architecture: string;
    python: string;
    packages: Record<string, { installed: boolean; version: string | null }>;
    visual_dependencies: {
      available: boolean;
      command: string;
      guidance: string;
    };
    runtime_plan: {
      guidance: string;
      install_url?: string;
      install_commands: string[];
    };
  };
}
export function DiagnosticsPanel() {
  const [info, setInfo] = useState<Diagnostic>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = async (signal?: AbortSignal) => {
    setBusy(true);
    try {
      const result = await api<Diagnostic>(
        "/diagnostics",
        "GET",
        undefined,
        signal,
      );
      if (!signal?.aborted) {
        setInfo(result);
        setError("");
      }
    } catch (e) {
      if (!signal?.aborted) setError((e as Error).message);
    } finally {
      if (!signal?.aborted) setBusy(false);
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, []);
  return (
    <Panel title="环境与部署帮助">
      {error && (
        <p role="alert" className="notice danger">
          {error}
        </p>
      )}
      {busy && (
        <p role="status" className="muted small">
          正在检查本机环境…
        </p>
      )}
      {info && (
        <>
          <p>
            {info.environment.system === "Darwin"
              ? "macOS"
              : info.environment.system}{" "}
            / {info.environment.architecture} · Python {info.environment.python}
          </p>
          <p className="muted small">
            {info.environment.runtime_plan.guidance}
          </p>
          {info.environment.runtime_plan.install_url && (
            <a
              href={info.environment.runtime_plan.install_url}
              target="_blank"
              rel="noreferrer"
            >
              官方运行时安装入口
            </a>
          )}
          <details>
            <summary>视觉依赖与终端诊断</summary>
            <p>
              {info.environment.visual_dependencies.available
                ? "视觉依赖已安装，加载时检查版本与可用性。"
                : "尚未安装完整视觉依赖。"}
            </p>
            <p className="muted small">
              {info.environment.visual_dependencies.guidance}
            </p>
            <pre className="model-log">
              {info.environment.visual_dependencies.command}
            </pre>
            {Object.entries(info.environment.packages).map(([name, status]) => (
              <p key={name} className="muted small">
                {name} · {status.version ?? "未安装"}
              </p>
            ))}
            <pre className="model-log">
              {
                "python scripts/diagnose_workstation.py --endpoint http://127.0.0.1:8501\npython scripts/diagnose_workstation.py"
              }
            </pre>
            <p className="muted small">
              有地址时获取与页面相同的当前诊断；不传地址仅检查环境，不推断服务已启动。
            </p>
          </details>
        </>
      )}
      <div className="actions">
        <button disabled={busy} onClick={() => void refresh()}>
          刷新环境检查
        </button>
        <a href="/api/diagnostics" download>
          下载工作台诊断包
        </a>
      </div>
      <p className="muted small">
        不含图像、人工记录或提示词；分享前检查包中的本机路径和日志。
      </p>
    </Panel>
  );
}
