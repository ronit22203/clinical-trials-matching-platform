"use client";

import type { MetricsSnapshot } from "@/lib/types/agent";
import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  value: string;
  subtext: string;
  trend: "up" | "stable" | "down";
  history: number[];
  color: string;
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const w = 64;
  const h = 24;
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MetricCard({ label, value, subtext, trend, history, color }: MetricCardProps) {
  const trendSymbol = trend === "up" ? "↑" : trend === "down" ? "↓" : "→";
  const trendClass =
    trend === "up" ? "text-status-eligible" : trend === "down" ? "text-status-excluded" : "text-on-surface-variant";

  return (
    <div className="rounded-2xl bg-surface-lowest ambient-shadow p-5">
      <p
        className="text-[10px] uppercase tracking-[0.08em] text-on-surface-variant mb-3"
        style={{ fontFamily: "var(--font-manrope)" }}
      >
        {label}
      </p>
      <div className="flex items-end justify-between">
        <div>
          <p className="text-3xl font-black text-on-surface" style={{ fontFamily: "var(--font-manrope)" }}>
            {value}
          </p>
          <p className="text-xs text-on-surface-variant mt-1">
            {subtext}{" "}
            <span className={cn("font-semibold", trendClass)}>
              {trendSymbol}
            </span>
          </p>
        </div>
        <Sparkline values={history} color={color} />
      </div>
    </div>
  );
}

interface MetricsPanelProps {
  metrics: MetricsSnapshot;
}

export default function MetricsPanel({ metrics }: MetricsPanelProps) {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1
          className="text-xl font-bold text-on-surface mb-1"
          style={{ fontFamily: "var(--font-manrope)" }}
        >
          Model + Retrieval Metrics
        </h1>
        <p className="text-sm text-on-surface-variant">
          Golden set: 20 queries · {metrics.history.length}-day window
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <MetricCard
          label="Recall@5"
          value={`${Math.round(metrics.recallAt5 * 100)}%`}
          subtext="vs 80% baseline"
          trend="up"
          history={metrics.history.map((h) => h.recallAt5)}
          color="#005050"
        />
        <MetricCard
          label="NDCG@5"
          value={`${Math.round(metrics.ndcgAt5 * 100)}%`}
          subtext="vs 72% baseline"
          trend="up"
          history={metrics.history.map((h) => h.ndcgAt5)}
          color="#00497d"
        />
        <MetricCard
          label="Latency / Query"
          value={`${(metrics.latencyMs / 1000).toFixed(2)}s`}
          subtext="p50 end-to-end"
          trend="up"
          history={metrics.history.map((h) => 10000 - h.latencyMs)}
          color="#84d4d3"
        />
        <MetricCard
          label="Cost / Run"
          value={`$${metrics.costPerRun.toFixed(4)}`}
          subtext="incl. API + compute"
          trend="stable"
          history={[0.003, 0.0032, 0.0031, 0.003, 0.0033, 0.003, 0.0031]}
          color="#3e4948"
        />
      </div>

      {/* History table */}
      <div>
        <h2
          className="text-[11px] uppercase tracking-[0.08em] text-on-surface-variant mb-3"
          style={{ fontFamily: "var(--font-manrope)" }}
        >
          7-Day History
        </h2>
        <div className="rounded-2xl bg-surface-lowest overflow-hidden ambient-shadow">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-surface-container">
                {["Date", "Recall@5", "NDCG@5", "Latency"].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-on-surface-variant font-semibold"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...metrics.history].reverse().map((row, i) => (
                <tr key={row.date} className={i % 2 === 0 ? "bg-surface-lowest" : "bg-surface"}>
                  <td className="px-4 py-2.5 text-xs text-on-surface-variant font-mono">
                    {row.date}
                  </td>
                  <td className="px-4 py-2.5 text-xs font-semibold text-status-eligible">
                    {Math.round(row.recallAt5 * 100)}%
                  </td>
                  <td className="px-4 py-2.5 text-xs font-semibold text-tertiary">
                    {Math.round(row.ndcgAt5 * 100)}%
                  </td>
                  <td className="px-4 py-2.5 text-xs text-on-surface font-mono">
                    {(row.latencyMs / 1000).toFixed(2)}s
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
