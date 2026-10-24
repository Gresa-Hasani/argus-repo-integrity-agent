"use client";

import { useEffect, useState } from "react";

type Finding = { evidence?: unknown[]; confidence?: number; origin?: string; finding_id: string; title: string; severity: string; category: string; finding_type: string; finding: string; reasoning: string; llm_reasoning?: string; deterministic_basis?: string[]; evidence_ids?: string[]; possible_explanations?: string[]; requires_manual_review: boolean; status: string; outcome: string };
type Row = { categories?: Record<string, number>; finding_details?: Finding[]; repository: string; available: boolean; status?: string; state: string; flagged?: boolean; incomplete?: boolean; severity?: Record<string, number>; [key: string]: unknown };
type Distribution = { n: number; missing: number; mean: number | null; median: number | null; std_dev: number | null; max_x: number; bins: number[]; normal_fit: number[][] };
type Population = { id: string; rows: Row[]; excluded: number; incomplete: number; distributions: Record<string, Distribution> };
type Statistics = { rows: Row[]; populations: Population[] };
const METRICS: Record<string, string> = { findings: "Findings", source_loc: "Meaningful source lines", commits: "Commits", checks_passed_pct: "Passed checks (%)", evaluator_errors: "Evaluator errors" };
const number = (value: unknown) => typeof value === "number" ? value.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "Unavailable";
const populationLabel = (id: string) => id === "without_flagged" ? "Without flagged repositories" : "Including flagged repositories";

function PopulationChart({ population, metric, maxY, findingsMax }: { population: Population; metric: string; maxY: number; findingsMax: number }) {
  const dist = population.distributions[metric];
  const x = (v: number) => 48 + 600 * v / dist.max_x;
  const y = (v: number) => 210 - 170 * v / maxY;
  return <article className="min-w-0 rounded-xl border border-slate-800 bg-slate-950/35 p-4">
    <h3 className="text-sm font-semibold text-slate-100">{populationLabel(population.id)}</h3>
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
    <FindingsCharts population={population} max={findingsMax} />
  </article>;
}

const SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
const severityColor: Record<string, string> = { CRITICAL: "#f43f5e", HIGH: "#fb923c", MEDIUM: "#facc15", LOW: "#38bdf8", INFO: "#94a3b8" };

function FindingsCharts({ population, max }: { population: Population; max: number }) {
  const [filter, setFilter] = useState<{repository: string; field: "severity" | "category"; value: string} | null>(null);
  const selected = population.rows.find(row => row.repository === filter?.repository);
  const details = (selected?.finding_details ?? []).filter(finding => filter && finding[filter.field] === filter.value);
  return <div className="mt-5 border-t border-slate-800 pt-4">
    <h4 className="text-sm font-semibold">Full findings breakdown</h4>
    <p className="mt-1 text-xs text-slate-400">Select a segment or category to read its findings. Shared scale: 0–{max} findings.</p>
    <div className="my-3 flex flex-wrap gap-3 text-[10px] text-slate-400">{SEVERITIES.map(level => <span key={level}><span style={{color:severityColor[level]}}>●</span> {level}</span>)}</div>
    {population.rows.map(row => <div key={row.repository} className="mb-4">
      <p className="mb-1 break-all text-xs text-slate-300">{row.repository} · {number(row.findings)} findings</p>
      <div className="flex h-7 overflow-hidden rounded bg-slate-800" aria-label={`Findings by severity for ${row.repository}`}>
        {Object.entries(row.severity ?? {}).map(([level, count]) => count > 0 && <button type="button" key={level} onClick={() => setFilter({repository:row.repository,field:"severity",value:level})} aria-label={`${row.repository}: ${count} ${level} findings`} title={`${count} ${level}`} style={{width:`${count / max * 100}%`,background:severityColor[level] ?? "#94a3b8"}} className="shrink-0 text-xs font-semibold text-slate-950 hover:brightness-125">{count}</button>)}
      </div>
      <div className="mt-2 space-y-1">{Object.entries(row.categories ?? {}).map(([category,count]) => <button type="button" key={category} onClick={() => setFilter({repository:row.repository,field:"category",value:category})} className="flex w-full items-center gap-2 text-left text-[11px] text-slate-300 transition hover:text-white"><span className="w-36 shrink-0 break-words">{category.replaceAll("_", " ")}</span><span className="h-2 flex-1 rounded bg-slate-800"><span className="block h-full rounded bg-violet-400" style={{width:`${count / max * 100}%`}} /></span><span>{count}</span></button>)}</div>
    </div>)}
    {filter && <div className="mt-3 rounded border border-slate-700 bg-slate-900 p-3"><div className="flex justify-between gap-2 text-xs"><strong>{filter.repository} · {filter.value}</strong><button type="button" onClick={() => setFilter(null)} className="text-slate-400">Close findings</button></div>{details.map(f => <article key={f.finding_id} className="mt-3 border-t border-slate-700 pt-3 text-xs"><h5 className="font-semibold text-slate-100">{f.finding_id} · {f.title}</h5><p className="mt-1 text-slate-400">{f.severity} · {f.category} · {f.finding_type} · {f.status} · {f.outcome}{f.requires_manual_review ? " · Manual review required" : ""}</p><p className="mt-2 whitespace-pre-wrap text-slate-200">{f.finding}</p><p className="mt-2 whitespace-pre-wrap text-slate-300">{f.reasoning}</p>{!!f.deterministic_basis?.length && <p className="mt-2 text-slate-400">Measured basis: {f.deterministic_basis.join("; ")}</p>}{f.llm_reasoning && <p className="mt-2 whitespace-pre-wrap text-slate-400">AI interpretation: {f.llm_reasoning}</p>}{!!f.evidence_ids?.length && <p className="mt-2 text-sky-300">Evidence: {f.evidence_ids.join(", ")}</p>}{!!f.evidence?.length && <details className="mt-2"><summary className="cursor-pointer text-sky-300">Full evidence ({f.evidence.length})</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all text-[11px] text-slate-400">{JSON.stringify(f.evidence, null, 2)}</pre></details>}{!!f.possible_explanations?.length && <p className="mt-2 text-slate-400">Possible explanations: {f.possible_explanations.join("; ")}</p>}</article>)}</div>}
    {!population.rows.length && <p className="text-xs text-slate-500">No eligible reports in this population.</p>}
  </div>;
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
  if (error) return <p role="alert" className="rounded-lg border border-amber-500/25 bg-amber-500/10 p-3 text-sm text-amber-200">{error} <button type="button" onClick={() => setRetry(n => n + 1)} className="underline underline-offset-2">Retry statistics</button></p>;
  if (!data) return <p role="status" className="text-sm text-slate-400">Loading repository statistics…</p>;
  const maxY = Math.max(1, ...data.populations.flatMap(p => [...p.distributions[metric].bins, ...p.distributions[metric].normal_fit.map(point => point[1])])) * 1.1;
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><p className="max-w-xl text-xs leading-relaxed text-slate-400">Measured report evidence, not assignment grades. Flagged repositories are excluded from the first view. Missing reports and unavailable measurements are never treated as zero.</p><label className="text-xs text-slate-300">Graph metric<select aria-label="Graph metric" value={metric} onChange={e => setMetric(e.target.value)} className="ml-2 rounded-lg border border-slate-700/80 bg-slate-950/80 px-2.5 py-2 text-xs text-slate-200 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-400/20">{Object.entries(METRICS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
    <div className={`grid gap-4 ${data.populations.length > 1 ? "lg:grid-cols-2" : ""}`}>{data.populations.map(pop => <PopulationChart key={pop.id} population={pop} metric={metric} maxY={maxY} findingsMax={Math.max(1, ...data.rows.map(row => typeof row.findings === "number" ? row.findings : 0))} />)}</div>
    <details className="rounded-xl border border-slate-800 bg-slate-950/35 p-3"><summary className="cursor-pointer text-xs text-slate-300 transition hover:text-slate-100">All repository measurements and statuses</summary><div className="mt-3 overflow-auto rounded-lg border border-slate-800/80"><table className="w-full min-w-[760px] text-left text-xs"><thead className="bg-slate-950/50 text-[10px] uppercase tracking-[0.12em] text-slate-500"><tr><th className="px-3 py-2.5">Repository / status</th>{Object.values(METRICS).map(label => <th key={label} className="px-3 py-2.5">{label}</th>)}</tr></thead><tbody>{data.rows.map(row => <tr key={row.repository} className="border-t border-slate-800"><td className="max-w-[20rem] break-words px-3 py-2.5">{row.repository}<div className={row.flagged ? "text-rose-300" : "text-slate-500"}>{row.status ?? row.state}{row.similarity_flagged ? " · CODE OVERLAP FLAGGED" : ""}{!row.available ? " · report unavailable" : ""}</div></td>{Object.keys(METRICS).map(key => <td key={key} className="px-3 py-2.5">{number(row[key])}</td>)}</tr>)}</tbody></table></div></details>
    <p className="text-xs text-slate-500">Passed checks measure evaluation coverage, not software quality. Incomplete reports remain labeled. A grading curve requires a verified rubric and grades.</p>
  </div>;
}
