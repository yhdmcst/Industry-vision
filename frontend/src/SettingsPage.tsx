import { useEffect, useState } from "react";
import { PathInput } from "./PathInput";
import { Camera, FlaskConical, Cpu, Download, ShieldCheck } from "lucide-react";
import { Panel, Badge } from "./components";
import type { State } from "./types";
import { scenarios } from "./types";
import type { Act } from "./MonitorPage";
import { DatasetPanel } from "./DatasetPanel";
import { AcquisitionPanel } from "./AcquisitionPanel";
import { CompositionPanel } from "./CompositionPanel";
import { MaintenancePanel } from "./MaintenancePanel";

export function SettingsPage({ state: s, act }: { state: State; act: Act }) {
  const [mode, setMode] = useState(s.source),
    [device, setDevice] = useState(0),
    [video, setVideo] = useState("");
  const [scenario, setScenario] = useState(s.scenario),
    [intensity, setIntensity] = useState(s.intensity);
  useEffect(() => setMode(s.source), [s.source]);
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>设置与演示</h1>
          <p>连接本地采集与推理服务，清晰标识每一份证据的来源。</p>
        </div>
        <Badge>
          <ShieldCheck size={13} />
          本地工作站
        </Badge>
      </div>
      <div className="settings-grid">
        <Panel title="采集源" action={<Camera size={19} />}>
          <p className="muted small">
            连接后先在下方预检取景，再建立正常基线。未连接摄像头时可使用合成样本。
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void act(
                "/source",
                { mode, device, video },
                "采集源已连接，请先预检取景，再建立正常基线。",
              );
            }}
          >
            <label>
              采集源
              <select
                aria-label="采集源"
                value={mode}
                onChange={(e) => setMode(e.target.value)}
              >
                {mode === "dataset" && (
                  <option value="dataset" disabled>
                    数据集回放（由样本管理建立）
                  </option>
                )}
                <option value="synthetic">合成演示 · PCB</option>
                <option value="camera">本地摄像头</option>
                <option value="video">本地视频</option>
              </select>
            </label>
            {mode === "camera" && (
              <label>
                摄像头编号
                <input
                  type="number"
                  min={0}
                  max={16}
                  value={device}
                  onChange={(e) => setDevice(Number(e.target.value))}
                />
              </label>
            )}
            {mode === "video" && (
              <PathInput
                label="本地视频路径"
                value={video}
                onChange={setVideo}
                placeholder="/path/to/inspection.mp4"
              />
            )}
            <button type="submit" disabled={mode === "dataset"}>
              <Camera size={15} />
              连接采集源
            </button>
          </form>
        </Panel>
        <Panel title="扰动演示" action={<FlaskConical size={19} />}>
          <p className="muted small">
            软件扰动不改变设备参数。场景标签保留在证据中，不传给模型作为原因提示。
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void act(
                "/scenario",
                { scenario, intensity },
                "演示场景已应用，下一帧开始生效。",
              );
            }}
          >
            <label>
              演示场景
              <select
                aria-label="演示场景"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
              >
                {Object.entries(scenarios).map(([key, value]) => (
                  <option key={key} value={key}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label>
              扰动强度{" "}
              <span className="range-value">
                {Math.round(intensity * 100)}%
              </span>
              <input
                type="range"
                min="0"
                max="1"
                step=".1"
                value={intensity}
                onChange={(e) => setIntensity(Number(e.target.value))}
              />
            </label>
            {s.replay && (
              <p className="muted small">
                固定回放期间禁止叠加扰动，请先切换采集源。
              </p>
            )}
            <button
              type="submit"
              disabled={
                !!s.replay || s.inspection_source.kind === "local_visual"
              }
            >
              <FlaskConical size={15} />
              应用演示场景
            </button>
          </form>
        </Panel>
        <AcquisitionPanel state={s} act={act} />
        <CompositionPanel state={s} />
        <DatasetPanel state={s} act={act} />
        <Panel title="本地模型" action={<Cpu size={19} />}>
          <p className="muted">
            在模型管理页准备、运行和维护复核模型，连接或重载视觉检测模型。
          </p>
          <a className="button" href="#models">
            <Cpu size={15} />
            管理本地模型
          </a>
        </Panel>
        <Panel title="证据与运行边界" action={<ShieldCheck size={19} />}>
          <dl className="fact-list">
            <div>
              <dt>数据存储</dt>
              <dd>当前工作台设备</dd>
            </div>
            <div>
              <dt>证据内容</dt>
              <dd>图像指标、事件与人工记录</dd>
            </div>
            <div>
              <dt>模型输入</dt>
              <dd>结构化文本指标</dd>
            </div>
            <div>
              <dt>执行权限</dt>
              <dd>仅人工核验</dd>
            </div>
          </dl>
          <p className="muted">
            导出当前会话的测量、事件和核验记录。超过 1,000
            条记录时，导出包会明确标识截断。
          </p>
          <a className="button" href="/api/export" download>
            <Download size={15} />
            导出会话证据
          </a>
          <div className="boundary-note">
            <ShieldCheck size={18} />
            <p>
              模型假设不能替代现场核验。
              <br />
              <span>不自动停线、放行或剔除。</span>
            </p>
          </div>
        </Panel>
        <MaintenancePanel />
      </div>
    </>
  );
}
