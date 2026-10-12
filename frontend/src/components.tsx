import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Expand, X, ImageOff, ArrowUpRight } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  BarChart,
  Bar,
} from "recharts";
import type { Baseline, Frame, Quality } from "./types";

export function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function StatusFact({
  title,
  value,
  source,
  observedAt,
  stale = false,
  tone = "",
}: {
  title: string;
  value: string;
  source: string;
  observedAt?: number | null;
  stale?: boolean;
  tone?: string;
}) {
  return (
    <div className="status-fact">
      <span className="muted small">{title}</span>
      <Badge tone={stale ? "orange" : tone}>{value}</Badge>
      <small>
        {source}
        {observedAt
          ? ` · ${new Date(observedAt * 1000).toLocaleTimeString("zh-CN", { hour12: false })}`
          : ""}
        {stale ? " · 已过期" : ""}
      </small>
    </div>
  );
}
export function Panel({
  title,
  eyebrow,
  action,
  children,
  className = "",
}: {
  title: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <div>
          {eyebrow && <span className="eyebrow">{eyebrow}</span>}
          <h2>{title}</h2>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export function ImageView({
  src,
  label,
  meta,
  compact = false,
  transform,
}: {
  src?: string | null;
  label: string;
  meta?: string;
  compact?: boolean;
  transform?: { zoom: number; x: number; y: number };
}) {
  const [open, setOpen] = useState(false);
  const [failedSource, setFailedSource] = useState<string | null>(null);
  useEffect(() => setFailedSource(null), [src]);
  const failed = !!src && failedSource === src;
  const trigger = useRef<HTMLButtonElement>(null);
  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };
  return (
    <>
      <div className={`image-view ${compact ? "compact" : ""}`}>
        <div className="image-label">
          <span>
            <i />
            {label}
          </span>
          <small>{meta}</small>
        </div>
        {src && !failed ? (
          <div className="image-viewport">
            <img
              src={src}
              alt={label}
              onError={() => setFailedSource(src)}
              style={
                transform
                  ? {
                      transform: `scale(${transform.zoom})`,
                      transformOrigin: `${transform.x}% ${transform.y}%`,
                    }
                  : undefined
              }
            />
          </div>
        ) : (
          <div className="image-empty">
            <ImageOff size={30} />
            <span>{failed ? "图像不可用，请检查文件或服务" : "等待图像"}</span>
          </div>
        )}
        {src && !failed && (
          <button
            ref={trigger}
            className="icon-button expand-image"
            aria-label={`放大${label}`}
            onClick={() => setOpen(true)}
          >
            <Expand size={15} />
          </button>
        )}
      </div>
      {open && (
        <div className="modal-backdrop" onClick={close}>
          <section
            className="image-modal"
            role="dialog"
            aria-modal="true"
            aria-label={label}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Escape") close();
              if (e.key === "Tab") e.preventDefault();
            }}
          >
            <div className="panel-heading">
              <h2>{label}</h2>
              <button
                autoFocus
                className="icon-button"
                aria-label="关闭图像"
                onClick={close}
              >
                <X />
              </button>
            </div>
            <img src={src!} alt={`${label}放大`} />
            <p>原始色彩 · 按实际图像比例展示</p>
          </section>
        </div>
      )}
    </>
  );
}
export function Metric({
  title,
  value,
  change,
  active,
  onClick,
}: {
  title: string;
  value: string;
  change?: number;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button className={`metric ${active ? "selected" : ""}`} onClick={onClick}>
      <span className="metric-name">
        {title}
        <ArrowUpRight size={14} />
      </span>
      <strong>{value}</strong>
      <small>
        {change === undefined ? (
          "等待当前测量"
        ) : (
          <>
            <span
              className={Math.abs(change) > 0.2 ? "text-warning" : "text-muted"}
            >
              {change >= 0 ? "+" : ""}
              {(change * 100).toFixed(1)}%
            </span>{" "}
            较参考基线
          </>
        )}
      </small>
    </button>
  );
}
const tooltip = {
  background: "#252a30",
  border: "1px solid #343b44",
  borderRadius: 6,
  color: "#e8edf2",
  fontSize: 12,
};
export function Trend({
  history,
  baseline,
  metric,
  selectFrame,
}: {
  history: Frame[];
  baseline: Baseline | null;
  metric: string;
  selectFrame?: (frame: number) => void;
}) {
  const data = history.map((f) => ({
    frame: f.frame,
    value: f.rule_report.metrics.image_quality[metric],
    abnormal: f.rule_report.drift_detected
      ? f.rule_report.metrics.image_quality[metric]
      : null,
  }));
  return (
    <div className="chart" aria-label="指标趋势图">
      <ResponsiveContainer width="100%" height={200}>
        <LineChart
          data={data}
          onClick={(e) => {
            if (e?.activeLabel !== undefined)
              selectFrame?.(Number(e.activeLabel));
          }}
          margin={{ top: 12, right: 12, left: -20, bottom: 0 }}
        >
          <CartesianGrid stroke="#292e35" vertical={false} />
          <XAxis
            dataKey="frame"
            tick={{ fill: "#87929f", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "#87929f", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={64}
          />
          <Tooltip
            contentStyle={tooltip}
            labelFormatter={(v) => `采样帧 ${v}`}
          />
          {baseline && (
            <ReferenceLine
              ifOverflow="extendDomain"
              y={baseline.image_quality[metric]}
              stroke="#78a9ff"
              strokeDasharray="5 5"
            />
          )}
          <Line
            name="当前测量"
            type="linear"
            dataKey="value"
            stroke="#4cc9a4"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            name="触发规则"
            dataKey="abnormal"
            stroke="none"
            dot={{ fill: "#f2747d", r: 4, strokeWidth: 0 }}
            connectNulls={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
export function Distribution({
  reference,
  current,
  metric,
}: {
  reference: Quality[];
  current: Quality[];
  metric: string;
}) {
  const a = reference.map((x) => x[metric]),
    b = current.map((x) => x[metric]);
  const low = Math.min(...a, ...b),
    high = Math.max(...a, ...b);
  const step = Math.max(high - low, 1) / 12;
  const bins = Array.from({ length: 12 }, (_, i) => ({
    name: (low + step * (i + 0.5)).toFixed(1),
    reference: 0,
    current: 0,
  }));
  for (const [values, key] of [
    [a, "reference"],
    [b, "current"],
  ] as const)
    for (const value of values)
      bins[Math.min(11, Math.floor((value - low) / step))][key] +=
        100 / values.length;
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={bins}>
          <CartesianGrid stroke="#292e35" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: "#87929f", fontSize: 10 }} />
          <YAxis unit="%" tick={{ fill: "#87929f", fontSize: 10 }} width={42} />
          <Tooltip contentStyle={tooltip} />
          <Bar
            name="基线样本 %"
            dataKey="reference"
            fill="#78a9ff"
            radius={[2, 2, 0, 0]}
          />
          <Bar
            name="当前窗口 %"
            dataKey="current"
            fill="#4cc9a4"
            radius={[2, 2, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
