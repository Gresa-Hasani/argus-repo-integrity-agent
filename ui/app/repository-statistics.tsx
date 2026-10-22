"use client";

import { useEffect, useState } from "react";

type Row = { repository: string; available: boolean; status?: string; state: string; flagged?: boolean; incomplete?: boolean; severity?: Record<string, number>; [key: string]: unknown };
type Distribution = { n: number; missing: number; mean: number | null; median: number | null; std_dev: number | null; max_x: number; bins: number[]; normal_fit: number[][] };
type Population = { id: string; rows: Row[]; excluded: number; incomplete: number; distributions: Record<string, Distribution> };
type Statistics = { rows: Row[]; populations: Population[] };
const METRICS: Record<string, string> = { findings: "Findings", source_loc: "Meaningful source lines", commits: "Commits", checks_passed_pct: "Passed checks (%)", evaluator_errors: "Evaluator errors" };
const number = (value: unknown) => typeof value === "number" ? value.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "Unavailable";
const populationLabel = (id: string) => id === "without_flagged" ? "Without flagged repositories" : "Including flagged repositories";

function PopulationChart({ population, metric, maxY }: { population: Population; metric: string; maxY: number }) {
  const dist = population.distributions[metric];
  const x = (v: number) => 48 + 600 * v / dist.max_x;
  const y = (v: number) => 210 - 170 * v / maxY;
  return <article className="min-w-0 rounded border border-slate-800 bg-slate-950/50 p-4">
    <h3 className="text-sm font-semibold text-slate-200">{populationLabel(population.id)}</h3>
    <p className="mt-1 text-xs text-slate-400">{population.rows.length} reports · {population.excluded} excluded · {population.incomplete} incomplete</p>
    <div className="mt-4 space-y-3" role="img" aria-label={`${METRICS[metric]} by repository, ${populationLabel(population.id)}`}>
      {population.rows.map(row => { const value = row[metric]; return <div key={row.repository}>
        <div className="mb-1 flex justify-between gap-3 text-xs"><span className="break-all text-slate-300">{row.repository}{row.flagged ? " · FLAGGED" : ""}{row.incomplete ? " · incomplete" : ""}</span><span className="shrink-0 font-mono">{number(value)}</span></div>
        <div className="h-3 rounded bg-slate-800">{typeof value === "number" && <div className={`h-full rounded ${row.flagged ? "bg-rose-400" : "bg-sky-400"}`} style={{ width: `${Math.max(0, Math.min(100, value / dist.max_x * 100))}%` }} />}</div>
      </div>; })}
      {!population.rows.length && <p className="text-xs text-slate-400">No reports in this population yet.</p>}
      <div className="flex justify-between text-[11px] text-slate-500"><span>0</span><span>{number(dist.max_x)} {METRICS[metric].toLowerCase()}</span></div>
    </div>
    <div className="mt-5 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-400"><span>n = {dist.n}</span><span>Mean {number(dist.mean)}</span><span>Median {number(dist.median)}</span><span>SD {number(dist.std_dev)}</span><span>Missing {dist.missing}</span></div>
    <svg viewBox="0 0 680 260" className="mt-2 w-full" role="img" aria-label={`Distribution of ${METRICS[metric]}, ${populationLabel(population.id)}`}>
      <title>{METRICS[metric]}: histogram and descriptive normal fit</title>
      {[0, .5, 1].map(f => <g key={f}><line x1="48" x2="648" y1={y(maxY * f)} y2={y(maxY * f)} stroke="#334155" /><text x="42" y={y(maxY * f) + 4} textAnchor="end" fill="#94a3b8" fontSize="11">{number(maxY * f)}</text></g>)}
      {dist.bins.map((count, i) => <rect key={i} x={48 + i * 60 + 2} y={y(count)} width="56" height={210 - y(count)} fill={population.id === "with_flagged" ? "#fb7185" : "#38bdf8"} opacity="0.7"><title>{number(i * dist.max_x / 10)}–{number((i + 1) * dist.max_x / 10)}: {count} repositories</title></rect>)}
      {!!dist.normal_fit.length && <path d={dist.normal_fit.map(([a, b], i) => `${i ? "L" : "M"}${x(a)},${y(b)}`).join(" ")} fill="none" stroke="#fbbf24" strokeWidth="3" />}
      {[0, .5, 1].map(f => <text key={f} x={x(dist.max_x * f)} y="229" textAnchor="middle" fill="#94a3b8" fontSize="11">{number(dist.max_x * f)}</text>)}
      <text x="348" y="251" textAnchor="middle" fill="#cbd5e1" fontSize="12">{METRICS[metric]}</text>
      <text transform="translate(13,125) rotate(-90)" textAnchor="middle" fill="#cbd5e1" fontSize="12">Repository count</text>
    </svg>
    <p className="text-xs text-slate-500">{dist.normal_fit.length ? "Yellow line: descriptive normal fit. This does not establish a normal distribution." : "A normal curve needs at least three non-identical measurements."}</p>
  </article>;
}

export default function RepositoryStatistics({ api, batchId, revision }: { api: string; batchId: string; revision: string }) {
  const [data, setData] = useState<Statistics | null>(null);
  const [error, setError] = useState("");
  const [metric, setMetric] = useState("findings");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${api}/api/batches/${batchId}/statistics`, { signal: controller.signal })
      .then(async r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(value => { setData(value); setError(""); })
      .catch(e => { if (e.name !== "AbortError") setError("Could not load the batch statistics."); });
    return () => controller.abort();
  }, [api, batchId, revision, retry]);
  if (error) return <p role="alert" className="text-sm text-amber-200">{error} <button onClick={() => setRetry(n => n + 1)} className="underline">Retry statistics</button></p>;
  if (!data) return <p className="text-sm text-slate-400">Loading repository statistics…</p>;
  const maxY = Math.max(1, ...data.populations.flatMap(p => [...p.distributions[metric].bins, ...p.distributions[metric].normal_fit.map(point => point[1])])) * 1.1;
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><p className="max-w-xl text-xs text-slate-400">Measured report evidence, not assignment grades. Flagged repositories are excluded from the first view. Missing reports and unavailable measurements are never treated as zero.</p><label className="text-xs text-slate-300">Graph metric<select aria-label="Graph metric" value={metric} onChange={e => setMetric(e.target.value)} className="ml-2 rounded border border-slate-700 bg-slate-950 p-2">{Object.entries(METRICS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
    <div className={`grid gap-4 ${data.populations.length > 1 ? "lg:grid-cols-2" : ""}`}>{data.populations.map(pop => <PopulationChart key={pop.id} population={pop} metric={metric} maxY={maxY} />)}</div>
    <details className="rounded border border-slate-800 p-3"><summary className="cursor-pointer text-xs text-slate-300">All repository measurements and statuses</summary><div className="mt-3 overflow-auto"><table className="w-full text-left text-xs"><thead><tr><th className="pr-4 pb-2">Repository / status</th>{Object.values(METRICS).map(label => <th key={label} className="pr-4 pb-2">{label}</th>)}</tr></thead><tbody>{data.rows.map(row => <tr key={row.repository} className="border-t border-slate-800"><td className="py-2 pr-4">{row.repository}<div className={row.flagged ? "text-rose-300" : "text-slate-500"}>{row.status ?? row.state}{row.similarity_flagged ? " · CODE OVERLAP FLAGGED" : ""}{!row.available ? " · report unavailable" : ""}</div></td>{Object.keys(METRICS).map(key => <td key={key} className="pr-4">{number(row[key])}</td>)}</tr>)}</tbody></table></div></details>
    <p className="text-xs text-slate-500">Passed checks measure evaluation coverage, not software quality. Incomplete reports remain labeled. A grading curve requires a verified rubric and grades.</p>
  </div>;
}
