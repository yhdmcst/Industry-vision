import { useEffect, useRef, useState } from "react";
import { PathInput } from "./PathInput";
import { ScanEye } from "lucide-react";
import { Panel, Badge } from "./components";
import type { State } from "./types";
import type { Act } from "./MonitorPage";
import { api } from "./api";

interface VisualAsset {
  id: string;
  name: string;
  mode: string;
  file_status: string;
  created: number;
}
interface Selection {
  model_id: string;
  timeout_seconds: number;
  created: number;
}
interface Catalog {
  assets: VisualAsset[];
  selections: Selection[];
  error: string;
  retired?: {
    retirement_id: string;
    asset: VisualAsset;
    removed: number;
    files_present: boolean;
  }[];
}
const statusLabels = {
  disabled: "未连接",
  loading: "加载中",
  ready: "已就绪",
  processing: "推理中",
  failed: "服务不可用",
};
const fileLabels: Record<string, string> = {
  compatible: "登记时校验通过",
  changed: "文件变化，需恢复文件或更换版本",
  missing: "文件缺失",
  incompatible: "方法版本不兼容",
};

export function VisionPanel({ state: s, act }: { state: State; act: Act }) {
  const [catalog, setCatalog] = useState<Catalog>({
    assets: [],
    selections: [],
    error: "",
  });
  const [selected, setSelected] = useState("");
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [timeout, setTimeout] = useState(s.vision_runtime.timeout_seconds ?? 2);
  const initialized = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [repairPath, setRepairPath] = useState("");
  const [protocol, setProtocol] = useState("");
  const [weights, setWeights] = useState("");
  const [releaseName, setReleaseName] = useState("");
  const [message, setMessage] = useState("");
  const [removal, setRemoval] = useState<{
    model_id: string;
    name: string;
    bytes: number;
    historical_events: number;
    token: string;
    scope: string;
  }>();
  const runtime = s.vision_runtime;
  const refresh = async (signal?: AbortSignal) => {
    try {
      const next = await api<Catalog>(
        "/vision/models",
        "GET",
        undefined,
        signal,
      );
      if (signal?.aborted) return;
      setCatalog(next);
      const recent = next.selections.at(-1);
      if (!initialized.current) {
        setTimeout(runtime.timeout_seconds ?? recent?.timeout_seconds ?? 2);
        initialized.current = true;
      }
      setSelected(
        (value) =>
          (next.assets.some((item) => item.id === value) ? value : "") ||
          (next.assets.some((item) => item.id === runtime.model_id)
            ? runtime.model_id
            : "") ||
          recent?.model_id ||
          next.assets[0]?.id ||
          "",
      );
      setError("");
      setRemoval(undefined);
    } catch (reason) {
      if (!signal?.aborted) setError((reason as Error).message);
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [runtime.model_id]);
  const blocked =
    busy ||
    s.running ||
    !!s.replay ||
    runtime.pending ||
    runtime.status === "loading" ||
    s.model.pending;
  const asset = catalog.assets.find((item) => item.id === selected);
  const inactive =
    runtime.model_id !== selected || runtime.status === "disabled";
  const current = catalog.assets.find((item) => item.id === runtime.model_id);
  const previous = [...catalog.selections]
    .reverse()
    .find(
      (item) =>
        item.model_id !== runtime.model_id ||
        item.timeout_seconds !== runtime.timeout_seconds,
    );
  const connect = async (model_id: string, timeout_seconds: number) => {
    if (
      await act(
        "/vision/connect",
        { model_id, timeout_seconds },
        "视觉模型已加载，请重新建立基线。",
      )
    )
      await refresh();
  };
  return (
    <Panel title="本地视觉检测" action={<ScanEye size={19} />}>
      <Badge tone={runtime.status === "failed" ? "orange" : "blue"}>
        {statusLabels[runtime.status]}
      </Badge>
      <p className="muted small">
        视觉模型读取图像，复核模型读取文本指标。加载、重载或停用视觉模型会清空当前基线，历史事件保留。
      </p>
      <p className="small">
        当前模型：
        {current?.name ||
          (runtime.model_id ? "从目录直接连接的模型" : "未加载")}
      </p>
      {runtime.timeout_seconds != null && (
        <p className="muted small">
          当前单帧时限：{runtime.timeout_seconds} 秒。下方设置用于下一次加载。
        </p>
      )}
      {catalog.assets.length ? (
        <>
          <label>
            已登记视觉模型
            <select
              aria-label="已登记视觉模型"
              value={selected}
              disabled={blocked}
              onChange={(event) => setSelected(event.target.value)}
            >
              <option value="" disabled>
                选择模型版本
              </option>
              {catalog.assets.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · {item.mode === "aligned" ? "姿态对齐" : "原图"}
                </option>
              ))}
            </select>
          </label>
          {asset && (
            <p className="muted small">
              {fileLabels[asset.file_status]} · 登记于{" "}
              {new Date(asset.created * 1000).toLocaleString("zh-CN")}
              。加载时重新核验文件与兼容性。
            </p>
          )}
          <label>
            单帧推理时限（秒）
            <input
              aria-label="单帧推理时限"
              type="number"
              min="0.1"
              max="10"
              step="0.1"
              disabled={blocked}
              value={timeout}
              onChange={(event) => setTimeout(Number(event.target.value))}
            />
          </label>
        </>
      ) : (
        <p className="muted small">
          还没有登记视觉模型。展开下方入口，导入已有的固定配方目录；登记不会启动推理或改变基线。
        </p>
      )}
      <div className="model-actions">
        <button disabled={busy} onClick={() => void refresh()}>
          刷新视觉资产
        </button>
        <button
          disabled={blocked || !asset || asset.file_status !== "compatible"}
          onClick={() => void connect(selected, timeout)}
        >
          连接／重载视觉模型
        </button>
        <button
          disabled={blocked || runtime.status === "disabled"}
          className="secondary"
          onClick={() =>
            void act(
              "/vision",
              undefined,
              "已停用视觉模型，切回演示检测，请重新建立基线。",
              "DELETE",
            )
          }
        >
          停用视觉模型，切回演示检测
        </button>
        <button
          disabled={
            blocked ||
            !previous ||
            catalog.assets.find((item) => item.id === previous.model_id)
              ?.file_status !== "compatible"
          }
          onClick={() => {
            if (previous) {
              setSelected(previous.model_id);
              setTimeout(previous.timeout_seconds);
              void connect(previous.model_id, previous.timeout_seconds);
            }
          }}
        >
          恢复最近保存的视觉配置
        </button>
      </div>
      {blocked && (
        <p className="muted small">
          请先暂停监测、结束回放并等待当前加载／推理或复核完成，再维护视觉模型。
        </p>
      )}
      <details>
        <summary>登记视觉模型目录</summary>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            void api<VisualAsset>("/vision/models/import", "POST", {
              path,
              name,
            })
              .then(async (item) => {
                setSelected(item.id);
                await refresh();
                setPath("");
                setName("");
              })
              .catch((reason) => setError((reason as Error).message))
              .finally(() => setBusy(false));
          }}
        >
          <label>
            显示名称
            <input
              aria-label="视觉模型显示名称"
              required
              maxLength={100}
              value={name}
              disabled={busy}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如 PCB4 正常参考模型"
            />
          </label>
          <PathInput
            label="视觉模型目录"
            value={path}
            onChange={setPath}
            directory
            disabled={busy}
            placeholder="填写后端设备上的固定配方目录"
          />
          <button disabled={busy} type="submit">
            {busy ? "正在登记…" : "校验并登记视觉模型"}
          </button>
        </form>
        <p className="muted small">
          完整校验后复制到工作台管理目录，原文件保持原样。这里只管理导出的 PaDiM
          固定配方，不能导入任意训练模型。
        </p>
      </details>
      <details>
        <summary>从研发封存协议登记</summary>
        <p className="muted small">
          选择完整封存协议目录及官方 ResNet18
          权重。保留原阈值、ROI、统计和封存回执；不训练、不重新标定、不读取最终集。当前只支持封存
          PaDiM 系列，登记后仍需显式加载。
        </p>
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            setMessage("");
            try {
              const item = await api<VisualAsset>(
                "/vision/models/import-release",
                "POST",
                { protocol, weights, name: releaseName },
              );
              setSelected(item.id);
              await refresh();
              setMessage(
                "封存模型已登记，原协议与阈值保留。请显式加载并重新建立基线。",
              );
            } catch (reason) {
              setError((reason as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            封存模型显示名称
            <input
              aria-label="封存模型显示名称"
              required
              maxLength={100}
              value={releaseName}
              onChange={(e) => setReleaseName(e.target.value)}
            />
          </label>
          <PathInput
            label="研发封存协议目录"
            value={protocol}
            onChange={setProtocol}
            directory
            disabled={busy}
          />
          <PathInput
            label="官方视觉权重文件"
            value={weights}
            onChange={setWeights}
            disabled={busy}
          />
          <button disabled={blocked}>校验封存协议并登记</button>
        </form>
      </details>
      {asset && (
        <details>
          <summary>修复与卸载所选视觉版本</summary>
          <p className="muted small">
            修复仅接收同一版本的完整部署配方，不能替换阈值或模型身份。原受损目录保留在修复备份区。卸载移至本机回收区，历史证据与原导入目录保留。
          </p>
          <PathInput
            label="同版本修复配方目录"
            value={repairPath}
            onChange={setRepairPath}
            directory
            disabled={busy}
          />
          <div className="actions">
            <button
              disabled={blocked || !inactive || !repairPath}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  await api(`/vision/models/${selected}/repair`, "POST", {
                    path: repairPath,
                  });
                  await refresh();
                  setMessage(
                    "视觉资产已按原身份修复，受损副本保留。请显式加载。",
                  );
                } catch (reason) {
                  setError((reason as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              校验并修复此版本
            </button>
            <button
              disabled={blocked || !inactive}
              onClick={async () => {
                setBusy(true);
                setError("");
                setRemoval(undefined);
                try {
                  setRemoval(
                    await api(`/vision/models/${selected}/removal-preview`),
                  );
                } catch (reason) {
                  setError((reason as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              预览卸载此版本
            </button>
          </div>
          {!inactive && (
            <p className="muted small">所选模型正在使用，请先停用或切换。</p>
          )}
          {removal && removal.model_id === selected && (
            <div className="notice">
              <p>
                {removal.name} · {(removal.bytes / 1024 ** 2).toFixed(1)} MiB ·
                当前证据库关联记录 {removal.historical_events} 条。
              </p>
              <p>{removal.scope}</p>
              <button
                disabled={blocked || !inactive}
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  try {
                    await api(`/vision/models/${selected}/remove`, "POST", {
                      token: removal.token,
                    });
                    setSelected("");
                    setRemoval(undefined);
                    await refresh();
                    setMessage(
                      "版本已移至本机回收区，历史证据保留。可在下方恢复。",
                    );
                  } catch (reason) {
                    setError((reason as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                确认移至回收区
              </button>
            </div>
          )}
        </details>
      )}
      {!!catalog.retired?.length && (
        <details>
          <summary>视觉版本回收区 · {catalog.retired.length}</summary>
          <p className="muted small">
            回收版本仍占本机空间，不自动删除。恢复会再次核验文件和版本，不自动加载。
          </p>
          {catalog.retired.map((item) => (
            <div key={item.retirement_id} className="operation-record">
              <p>
                {item.asset.name} ·{" "}
                {new Date(item.removed * 1000).toLocaleString("zh-CN")}
              </p>
              <button
                disabled={blocked || !item.files_present}
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  try {
                    const restored = await api<VisualAsset>(
                      `/vision/models/retired/${item.retirement_id}/restore`,
                      "POST",
                    );
                    setSelected(restored.id);
                    await refresh();
                    setMessage("视觉版本已恢复到可选目录，尚未加载。");
                  } catch (reason) {
                    setError((reason as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                恢复此视觉版本
              </button>
            </div>
          ))}
        </details>
      )}
      {message && <p role="status">{message}</p>}
      {(error ||
        catalog.error ||
        s.vision_management_error ||
        runtime.error) && (
        <p className="notice danger" role="alert">
          {error || catalog.error || s.vision_management_error || runtime.error}
        </p>
      )}
      {catalog.selections.length > 0 && (
        <details>
          <summary>最近保存的视觉配置</summary>
          <p className="muted small">
            配置记录用于显式重新加载；重启工作台不会自动启用视觉模型。已保存配置不代表当前模型运行中。
          </p>
          {[...catalog.selections]
            .reverse()
            .slice(0, 5)
            .map((item) => (
              <p className="small" key={item.created}>
                {
                  catalog.assets.find((asset) => asset.id === item.model_id)
                    ?.name
                }{" "}
                · {item.timeout_seconds} 秒 ·{" "}
                {new Date(item.created * 1000).toLocaleString("zh-CN")}
              </p>
            ))}
        </details>
      )}
      {runtime.last_ms != null && (
        <p className="muted small">
          上次推理观测耗时 {runtime.last_ms.toFixed(1)} ms
        </p>
      )}
      <p className="muted small">
        当前公开数据配置仍有误报与漏检，判定供人工核验。
      </p>
    </Panel>
  );
}
