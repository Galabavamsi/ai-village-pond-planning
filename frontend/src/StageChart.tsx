import { useId, useMemo, useState } from "react";
import type { StageRow } from "./types";

const WIDTH = 320;
const HEIGHT = 178;
const PAD = { top: 14, right: 16, bottom: 30, left: 50 };
const fmt = (value: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value);
const short = (value: number) =>
  value >= 1_000_000 ? `${(value / 1_000_000).toFixed(1)}M` : value >= 1000 ? `${Math.round(value / 1000)}k` : String(Math.round(value));

function niceMax(value: number) {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((item) => item * power >= value) ?? 10;
  return step * power;
}

/** Screening stage–storage curve with the scenario runoff as a threshold. */
export default function StageChart({ curve, selectedStage, runoff }: { curve: StageRow[]; selectedStage: number; runoff: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const titleId = useId();
  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const maxStage = Math.max(...curve.map((row) => row.stage_m));
  const maxStorage = Math.max(...curve.map((row) => row.storage_m3), 1);
  // Keep the storage curve readable: very large runoff is marked off-scale
  // rather than squashing the curve against the baseline.
  const runoffOffScale = runoff > maxStorage * 2;
  const yMax = niceMax((runoffOffScale ? maxStorage : Math.max(runoff, maxStorage)) * 1.08);
  const x = (stage: number) => PAD.left + (stage / maxStage) * plotW;
  const y = (volume: number) => PAD.top + plotH - (volume / yMax) * plotH;
  const points = useMemo(() => [{ stage_m: 0, storage_m3: 0 }, ...curve], [curve]);
  const path = points.map((row, index) => `${index ? "L" : "M"}${x(row.stage_m).toFixed(1)},${y(row.storage_m3).toFixed(1)}`).join(" ");
  const area = `${path} L${x(maxStage).toFixed(1)},${y(0)} L${x(0)},${y(0)} Z`;
  const selected = curve.find((row) => row.stage_m === selectedStage);
  const ticks = [0, yMax / 2, yMax];
  const stageTicks = Array.from(new Set([0, ...curve.map((row) => row.stage_m).filter((stage) => Number.isInteger(stage))]));
  const active = hover === null ? null : curve[hover];
  const fillStage = curve.find((row) => row.storage_m3 >= runoff);

  const onMove = (event: React.PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const stage = ((event.clientX - box.left) / box.width) * maxStage;
    let best = 0;
    curve.forEach((row, index) => { if (Math.abs(row.stage_m - stage) < Math.abs(curve[best].stage_m - stage)) best = index; });
    setHover(best);
  };

  return (
    <figure className="stage-chart" aria-labelledby={titleId}>
      <figcaption id={titleId}>
        <span className="eyebrow">STAGE–STORAGE</span>
        <strong>How much would a higher bund hold?</strong>
      </figcaption>
      <div className="chart-legend">
        <span><i className="line-key line-key--storage" /> Pond storage</span>
        <span><i className="line-key line-key--runoff" /> Scenario runoff <span className="chart-legend-value">{fmt(runoff)} m³</span></span>
      </div>
      <div className="stage-chart-plot">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`Storage rises from ${fmt(curve[0]?.storage_m3 ?? 0)} m³ at ${curve[0]?.stage_m} m to ${fmt(curve[curve.length - 1]?.storage_m3 ?? 0)} m³ at ${maxStage} m; scenario runoff is ${fmt(runoff)} m³.`}>
          {ticks.map((tick) => (
            <g key={tick}>
              <line x1={PAD.left} x2={WIDTH - PAD.right} y1={y(tick)} y2={y(tick)} className="chart-grid" />
              <text x={PAD.left - 7} y={y(tick) + 3.5} textAnchor="end" className="chart-tick">{short(tick)}</text>
            </g>
          ))}
          {stageTicks.map((stage) => (
            <text key={stage} x={x(stage)} y={HEIGHT - 12} textAnchor="middle" className="chart-tick">{stage}</text>
          ))}
          <text x={WIDTH - PAD.right} y={HEIGHT - 1} textAnchor="end" className="chart-axis-title">water stage above outlet (m)</text>
          <text x={4} y={PAD.top - 3} className="chart-axis-title">m³</text>
          <path d={area} className="chart-area" />
          {runoffOffScale ? (
            <text x={WIDTH - PAD.right} y={PAD.top - 3} textAnchor="end" className="chart-offscale">runoff {short(runoff)} m³ ↑ above chart</text>
          ) : (
            <line x1={PAD.left} x2={WIDTH - PAD.right} y1={y(runoff)} y2={y(runoff)} className="chart-threshold" />
          )}
          <path d={path} className="chart-line" />
          {selected ? (
            <g>
              <line x1={x(selected.stage_m)} x2={x(selected.stage_m)} y1={PAD.top} y2={y(0)} className="chart-selected-rule" />
              <circle cx={x(selected.stage_m)} cy={y(selected.storage_m3)} r={5} className="chart-marker" />
            </g>
          ) : null}
          {active ? (
            <g pointerEvents="none">
              <line x1={x(active.stage_m)} x2={x(active.stage_m)} y1={PAD.top} y2={y(0)} className="chart-crosshair" />
              <circle cx={x(active.stage_m)} cy={y(active.storage_m3)} r={4.5} className="chart-marker chart-marker--hover" />
            </g>
          ) : null}
          <rect
            x={PAD.left} y={PAD.top} width={plotW} height={plotH} fill="transparent"
            tabIndex={0}
            aria-label="Inspect stage values"
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
            onFocus={() => setHover(curve.findIndex((row) => row.stage_m === selectedStage))}
            onBlur={() => setHover(null)}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight") setHover((value) => Math.min(curve.length - 1, (value ?? 0) + 1));
              if (event.key === "ArrowLeft") setHover((value) => Math.max(0, (value ?? 0) - 1));
            }}
          />
        </svg>
        {active ? (
          <div className="chart-tooltip" style={{ left: `${(x(active.stage_m) / WIDTH) * 100}%` }}>
            <strong>{fmt(active.storage_m3)} m³</strong>
            <span>at {active.stage_m} m stage</span>
            <span>{fmt(active.area_m2)} m² water · {fmt(active.embankment_length_m)} m bund</span>
          </div>
        ) : null}
      </div>
      <p className="chart-note">
        {fillStage
          ? `This scenario's runoff would fill the pond up to about ${fillStage.stage_m} m.`
          : "This scenario's runoff exceeds storage at every stage shown; surplus must spill safely."}
      </p>
      <button type="button" className="chart-table-toggle" onClick={() => setTable((value) => !value)} aria-expanded={table}>
        {table ? "Hide table" : "Show as table"}
      </button>
      {table ? (
        <table className="chart-table">
          <thead><tr><th>Stage (m)</th><th>Water area (m²)</th><th>Storage (m³)</th><th>Bund (m)</th></tr></thead>
          <tbody>
            {curve.map((row) => (
              <tr key={row.stage_m} className={row.stage_m === selectedStage ? "is-selected" : ""}>
                <td>{row.stage_m}</td><td>{fmt(row.area_m2)}</td><td>{fmt(row.storage_m3)}</td><td>{fmt(row.embankment_length_m)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </figure>
  );
}

/** Monthly CHIRPS totals as small columns (one series, one colour). */
export function RainBars({ monthly }: { monthly: Record<string, number> }) {
  const entries = Object.entries(monthly);
  if (entries.length < 2) return null;
  const max = Math.max(...entries.map(([, value]) => value), 1);
  const peak = entries.reduce((best, item) => (item[1] > best[1] ? item : best), entries[0]);
  const label = (month: string) => new Date(`${month}-01T00:00:00`).toLocaleString("en", { month: "short" });
  return (
    <div className="rain-bars" role="img" aria-label={`Monthly rainfall: ${entries.map(([month, value]) => `${label(month)} ${Math.round(value)} mm`).join(", ")}`}>
      {entries.map(([month, value]) => (
        <div key={month} className="rain-bar" title={`${label(month)} ${month.slice(0, 4)}: ${Math.round(value)} mm`}>
          <span className="rain-bar-value">{month === peak[0] || entries.length <= 4 ? Math.round(value) : ""}</span>
          <i style={{ height: `${Math.max(3, (value / max) * 100)}%` }} />
          <span className="rain-bar-month">{entries.length > 6 ? label(month).charAt(0) : label(month)}</span>
        </div>
      ))}
    </div>
  );
}
