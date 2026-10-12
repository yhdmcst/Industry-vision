import { Badge, Panel } from "./components";
import { driftLabels, inspectionStatuses } from "./types";
import type { Alert } from "./types";

const labels: Record<Alert["state"], string> = {
  warming: "预热证据不足",
  active: "告警持续",
  blocked: "恢复证据不足",
  recovering: "恢复确认中",
  recovered: "规则已恢复",
  clear: "未触发规则",
  unavailable: "采集不可用",
};

export function AlertEvidence({
  alert,
  ready,
}: {
  alert: Alert;
  ready: boolean;
}) {
  const episode = alert.episode;
  const warning = alert.active || alert.state === "unavailable";
  return (
    <Panel
      title="告警周期"
      action={
        <div data-testid="alert-state">
          <Badge tone={!ready || warning ? "orange" : "blue"}>
            {ready ? labels[alert.state] : "等待基线"}
          </Badge>
        </div>
      }
    >
      <dl className="fact-list">
        <div>
          <dt>连续异常</dt>
          <dd>{alert.abnormal_streak} 帧</dd>
        </div>
        <div>
          <dt>恢复确认</dt>
          <dd data-testid="recovery-streak">
            {alert.recovery_streak}/{alert.recovery_samples} 帧
          </dd>
        </div>
        {episode && (
          <div>
            <dt>关联事件</dt>
            <dd>
              #{episode.incident_id ?? "—"} · B{episode.baseline_generation}
            </dd>
          </div>
        )}
      </dl>
      {episode && (
        <p className="muted small">
          始于帧 {episode.started_frame}，最近异常帧{" "}
          {episode.last_abnormal_frame}。
          {episode.drift_types.map((type) => driftLabels[type]).join(" / ")}
          {episode.unavailable_statuses
            .map(
              (status) =>
                ` / 检测${inspectionStatuses[status as keyof typeof inspectionStatuses]}`,
            )
            .join("")}
        </p>
      )}
      <p className="muted small">
        首次异常立即留存；同一周期只建立一条自动事件。完整检测窗口内连续{" "}
        {alert.recovery_samples}{" "}
        帧无规则异常才确认恢复。采集失败、检测不可用与预热均不能计入恢复；规则恢复不代表产品合格。
      </p>
    </Panel>
  );
}
