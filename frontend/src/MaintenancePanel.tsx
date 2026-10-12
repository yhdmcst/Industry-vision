import { useEffect, useState } from "react";
import { Panel } from "./components";
import { api, downloadBackup } from "./api";

interface StorageInfo {
  database_bytes: number;
  wal_bytes: number;
  events: number;
  sessions: number;
  scope: string;
}
export function MaintenancePanel() {
  const [info, setInfo] = useState<StorageInfo>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [before, setBefore] = useState(
    new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10),
  );
  const [keep, setKeep] = useState(5);
  const [preview, setPreview] = useState<{
    token: string;
    events: number;
    payload_bytes: number;
    sessions: { session: string; count: number }[];
  }>();
  const [archives, setArchives] = useState<
    {
      id: string;
      created?: number;
      events?: number;
      bytes?: number;
      error?: string;
    }[]
  >([]);
  const refresh = async (signal?: AbortSignal) => {
    try {
      setInfo(
        await api<StorageInfo>(
          "/maintenance/storage",
          "GET",
          undefined,
          signal,
        ),
      );
      setError("");
      setArchives(
        await api<typeof archives>(
          "/maintenance/archives",
          "GET",
          undefined,
          signal,
        ),
      );
    } catch (reason) {
      if (!signal?.aborted) setError((reason as Error).message);
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, []);
  return (
    <Panel title="证据存储与备份">
      {info ? (
        <dl className="fact-list">
          <div>
            <dt>会话证据占用</dt>
            <dd>
              {((info.database_bytes + info.wal_bytes) / 1024 ** 2).toFixed(1)}{" "}
              MiB
            </dd>
          </div>
          <div>
            <dt>会话 / 记录</dt>
            <dd>
              {info.sessions} / {info.events}
            </dd>
          </div>
        </dl>
      ) : (
        <p className="muted small">正在读取存储概况…</p>
      )}
      <p className="muted small">
        {info?.scope || "备份会话证据数据库。"}。不会自动删除历史证据。
      </p>
      <div className="model-actions">
        <button
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setError("");
            setMessage("");
            void downloadBackup(true)
              .then(() =>
                setMessage("工作空间备份已交给浏览器下载，请确认文件已保存。"),
              )
              .catch((reason) => setError(reason.message))
              .finally(() => setBusy(false));
          }}
        >
          {busy ? "维护处理中…" : "下载工作空间备份"}
        </button>
        <button disabled={busy} onClick={() => void refresh()}>
          刷新存储概况
        </button>
        <button
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setMessage("");
            setError("");
            void downloadBackup()
              .then(() =>
                setMessage("备份已准备并交给浏览器下载，请确认文件已保存。"),
              )
              .catch((reason) => setError((reason as Error).message))
              .finally(() => setBusy(false));
          }}
        >
          {busy ? "正在生成备份…" : "下载会话证据备份"}
        </button>
      </div>
      <p className="muted small">
        工作空间备份含受管样本、留存、结果、视觉资产及配置；请暂停采集并等待模型任务结束。语言模型缓存、运行时、外部原始文件和浏览器草稿另行保留。
      </p>
      <details>
        <summary>旧会话归档与空间管理</summary>
        <p className="muted small">
          当前会话始终保留，旧会话先完整归档并核验，再从活动数据库释放。图像、人工记录和失败证据一同保留。样本和模型目录不删除。
        </p>
        <label>
          仅归档此日期前结束的会话
          <input
            aria-label="归档截止日期"
            type="date"
            value={before}
            onChange={(e) => {
              setBefore(e.target.value);
              setPreview(undefined);
            }}
          />
        </label>
        <label>
          至少保留最近会话数
          <input
            aria-label="保留会话数"
            type="number"
            min="1"
            max="10000"
            value={keep}
            onChange={(e) => {
              setKeep(Number(e.target.value));
              setPreview(undefined);
            }}
          />
        </label>
        <button
          disabled={busy || !before || keep < 1}
          onClick={async () => {
            setBusy(true);
            setError("");
            setPreview(undefined);
            try {
              setPreview(
                await api("/maintenance/retention-preview", "POST", {
                  before: new Date(before).getTime() / 1000,
                  keep_latest: keep,
                }),
              );
            } catch (reason) {
              setError((reason as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          预览保留范围
        </button>
        {preview && (
          <div className="notice">
            <p>
              将归档 {preview.sessions.length} 个会话 / {preview.events}{" "}
              条记录（载荷约 {(preview.payload_bytes / 1024 ** 2).toFixed(1)}{" "}
              MiB）。当前会话与最近 {keep} 个会话保留。
            </p>
            <ul>
              {preview.sessions.map((item) => (
                <li key={item.session}>
                  {item.session.slice(0, 12)} · {item.count} 条记录
                </li>
              ))}
            </ul>
            <button
              disabled={busy || !preview.sessions.length}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  const result = await api<{ scope: string }>(
                    "/maintenance/archive",
                    "POST",
                    {
                      before: new Date(before).getTime() / 1000,
                      keep_latest: keep,
                      token: preview.token,
                    },
                  );
                  setMessage(result.scope);
                  setPreview(undefined);
                  await refresh();
                } catch (reason) {
                  setError((reason as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              确认归档并释放旧会话
            </button>
          </div>
        )}
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              await api("/maintenance/compact", "POST");
              setMessage("活动数据库未使用空间已回收，原记录保留。");
              await refresh();
            } catch (reason) {
              setError((reason as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          回收数据库未使用空间
        </button>
        <p className="muted small">
          归档保存在本机，仍占磁盘。下载并验证后可由你转存到其他介质；本页不删除归档。恢复到新数据库即可查询归档事件。
        </p>
        {archives.map((item) => (
          <p key={item.id}>
            {item.error ? (
              <span role="alert">{item.error}</span>
            ) : (
              <a href={`/api/maintenance/archives/${item.id}`}>
                下载归档 ·{" "}
                {item.created
                  ? new Date(item.created * 1000).toLocaleString("zh-CN")
                  : ""}{" "}
                · {item.events} 条
              </a>
            )}
          </p>
        ))}
      </details>
      {message && <p role="status">{message}</p>}
      {error && (
        <p role="alert" className="notice danger">
          {error}
        </p>
      )}
      <details>
        <summary>如何恢复备份</summary>
        <p className="muted small">
          恢复为新的数据库，保留现有工作台。退出需要切换的工作台后，在终端执行；新工作台可查看历史事件，当前基线须重新建立。
        </p>
        <pre className="model-log">
          {
            "python scripts/restore_evidence.py --source <备份文件> --destination <新数据库>\npython run.py --database <新数据库>"
          }
        </pre>
        <p className="muted small">
          模型部署配置与外部数据目录需另外保留。此备份不是整个项目或设备备份。
        </p>
        <p className="muted small">
          工作空间 ZIP
          则恢复到不存在的新目录，模型保持未启动；目标设备的运行时和缓存需要重新检查。
        </p>
        <pre className="model-log">
          {
            "python scripts/restore_workspace.py --source <工作空间ZIP> --destination <新目录>\npython run.py --database <输出的数据库路径>"
          }
        </pre>
      </details>
    </Panel>
  );
}
