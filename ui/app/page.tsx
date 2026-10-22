/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import RepositoryStatistics from "./repository-statistics";

// Presentation only. Every number and status on this page is read from the ARGUS result;
// statistical summaries are computed on the backend from measured report evidence.
// Set NEXT_PUBLIC_API_URL per environment (ui/.env.development for local work, the Vercel project settings in production).
const API = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/+$/, "");
// Two clearly separated modes:
//   PUBLIC DEMO  - no NEXT_PUBLIC_API_URL: the page is fully static and shows the saved real evaluation
//                  bundled under /demo. Nothing is evaluated, and no backend is contacted.
//   LOCAL FULL   - NEXT_PUBLIC_API_URL set: the page talks to a locally running ARGUS backend.
const DEMO_MODE = !API;
const DEMO_BASE = "/demo";
type Source = "demo" | "api";
const reportLinks = (id: string, source: Source) =>
  source === "demo" ? { report: `${DEMO_BASE}/${id}.md`, json: `${DEMO_BASE}/${id}.json` } : { report: `${API}/api/evaluate/${id}/report`, json: `${API}/api/evaluate/${id}/json` };

const STATUS_STYLE: Record<string, string> = {
  DONE_CLEAN: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  DONE_WITH_FINDINGS: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  FLAGGED: "bg-red-500/15 text-red-300 border-red-500/40",
  INCOMPLETE_EVALUATION: "bg-slate-500/20 text-slate-300 border-slate-500/40",
  EVALUATOR_ERROR: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/40",
};
const TYPE_STYLE: Record<string, string> = {
  ENGINEERING_WEAKNESS: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  ANOMALY: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  MATERIAL_INTEGRITY_CONCERN: "bg-red-500/15 text-red-300 border-red-500/30",
  SECURITY: "bg-rose-500/15 text-rose-300 border-rose-500/30",
};
const SEVERITY_STYLE: Record<string, string> = {
  LOW: "text-slate-300 border-slate-600",
  MEDIUM: "text-amber-300 border-amber-500/40",
  HIGH: "text-orange-300 border-orange-500/50",
  CRITICAL: "text-red-300 border-red-500/60",
};

const fmt = (n: any) => (typeof n === "number" ? n.toLocaleString("en-US") : n ?? "n/a");
const pct = (n: any) => (typeof n === "number" ? `${Math.round(n * 100)}%` : "n/a");

function Badge({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-[11px] tracking-wide ${className}`}>{children}</span>;
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-200">{title}</h2>
        {hint && <span className="text-xs text-slate-500">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

function Stat({ label, value, tone = "" }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/60 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 font-mono text-2xl ${tone || "text-slate-100"}`}>{value}</div>
    </div>
  );
}

function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-slate-800/70 py-1.5 text-sm last:border-0">
      <span className="text-slate-500">{k}</span>
      <span className="break-all text-right font-mono text-slate-200">{v}</span>
    </div>
  );
}

function Finding({ f, candidates }: { f: any; candidates: any[] }) {
  const [open, setOpen] = useState(false);
  const security = f.category === "SECRET_EXPOSURE";
  const related = candidates.filter((c) => c.finding_id === f.finding_id);
  // Reports written before the statement became policy-generated carry the model's wording in `finding`.
  const statementIsDeterministic = f.text_origin === "deterministic" || f.origin === "deterministic";
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/50">
      <button onClick={() => setOpen(!open)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 text-left hover:bg-slate-900/70">
        <span className="font-mono text-xs text-slate-400">{f.finding_id}</span>
        <span className="min-w-0 flex-1 text-sm font-medium text-slate-100">{f.title}</span>
        <Badge className={TYPE_STYLE[security ? "SECURITY" : f.finding_type]}>{security ? "SECURITY" : f.finding_type.replaceAll("_", " ")}</Badge>
        <Badge className={SEVERITY_STYLE[f.severity]}>{f.severity}</Badge>
        <Badge className="border-slate-700 text-slate-300">{f.material ? "MATERIAL" : "NON-MATERIAL"}</Badge>
        <Badge className="border-slate-700 text-slate-300">OUTCOME {f.outcome}</Badge>
        <Badge className={f.requires_manual_review ? "border-red-500/50 bg-red-500/15 text-red-300" : "border-slate-700 text-slate-400"}>
          MANUAL REVIEW: {f.requires_manual_review ? "YES" : "NO"}
        </Badge>
        <span className="text-slate-500">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="grid gap-4 border-t border-slate-800 p-4 md:grid-cols-2">
          <div className="rounded-md border border-emerald-500/25 bg-emerald-500/5 p-3">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-emerald-300">Deterministic evidence · authoritative</div>
            {statementIsDeterministic && <p className="text-sm text-slate-200">{f.finding}</p>}
            <div className="mt-3 text-xs text-slate-400">Deterministic basis</div>
            <ul className="mt-1 list-disc pl-5 text-sm text-slate-300">
              {(f.deterministic_basis ?? []).map((b: string, i: number) => <li key={i}>{b}</li>)}
            </ul>
            {f.reasoning && <p className="mt-2 text-sm text-slate-300">{f.reasoning}</p>}
            <div className="mt-3 text-xs text-slate-400">Evidence</div>
            <ul className="mt-1 space-y-1 text-xs">
              {(f.evidence ?? []).map((e: any) => (
                <li key={e.id} className="text-slate-300"><span className="font-mono text-emerald-300">{e.id}</span> <span className="text-slate-500">({e.type})</span> {e.summary}</li>
              ))}
            </ul>
          </div>
          <div className="space-y-3">
            <div className="rounded-md border border-violet-500/25 bg-violet-500/5 p-3">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-violet-300">AI reasoning · advisory only</div>
              {!statementIsDeterministic && <p className="mb-2 text-sm text-slate-300">{f.finding}</p>}
              <p className="text-sm text-slate-300">{f.llm_reasoning || "No model reasoning attached."}</p>
              {(f.llm_reasoning_removed ?? []).length > 0 && (
                <p className="mt-2 text-xs text-slate-500">Model sentences removed by policy for contradicting authoritative fields: {f.llm_reasoning_removed.join(", ")}</p>
              )}
              {(f.possible_explanations ?? []).length > 0 && (
                <p className="mt-2 text-xs text-slate-400">Possible explanations: {f.possible_explanations.join("; ")}</p>
              )}
            </div>
            <div className="rounded-md border border-slate-700 bg-slate-900/60 p-3">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-300">Policy decision</div>
              <p className="text-sm text-slate-300">
                Classified <span className="font-mono">{f.finding_type}</span>, severity <span className="font-mono">{f.severity}</span>, outcome{" "}
                <span className="font-mono">{f.outcome}</span>, proposed by <span className="font-mono">{f.origin}</span>
                {f.source_step ? <> in step <span className="font-mono">{f.source_step}</span></> : null}. Type, severity, materiality and the review requirement are set by the deterministic policy layer.
              </p>
              {related.map((c) => (
                <p key={c.candidate_id} className="mt-2 text-xs text-slate-400">
                  <span className="font-mono text-slate-300">{c.candidate_id}</span> proposed {c.proposed_category}/{c.proposed_severity}
                  {c.proposed_manual_review ? "/review" : ""} → <span className="font-mono text-slate-300">{c.decision}</span>: {c.reason}
                </p>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-28 shrink-0 text-slate-400">{label}</span>
      <div className="h-2 flex-1 rounded bg-slate-800"><div className="h-2 rounded bg-sky-400/80" style={{ width: `${max ? Math.max(1, (value / max) * 100) : 0}%` }} /></div>
      <span className="w-16 shrink-0 text-right font-mono text-slate-200">{fmt(value)}</span>
    </div>
  );
}

function Dashboard({ r, links, source }: { r: any; links: { report: string; json: string }; source: Source }) {
  const [showJson, setShowJson] = useState(false);
  const m = r.deterministic_metrics ?? {};
  const counts = r.definition_of_done?.counts ?? {};
  const repo = r.repository ?? {};
  const stats = m.statistics;
  const scc = m.scc;
  const cats = scc?.categories ?? {};
  const tl = m.timeline;
  const gh = m.github ?? {};
  const ci = m.ci ?? {};
  const hy = m.hygiene;
  const contributors = (m.contributors?.contributors ?? []).filter((c: any) => c.kind !== "platform" && c.total_commit_appearances);
  const findings: any[] = r.findings ?? [];
  const candidates: any[] = r.candidate_decisions ?? [];
  const runs = gh.workflow_runs;
  const perDay: any[] = tl?.per_day ?? [];
  const maxDay = Math.max(1, ...perDay.map((d) => d.commits));
  const name = repo.owner ? `${repo.owner}/${repo.name}` : repo.name;
  const anomalyByContributor = (id: string) => findings.filter((f) => (f.evidence ?? []).some((e: any) => e.type === "contributor" && e.data?.id === id));

  return (
    <div className="space-y-5">
      <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-wider text-slate-500">Evaluation result{source === "demo" ? " · saved real evaluation (bundled with this page)" : ""}</div>
            <div className="mt-1 font-mono text-lg text-slate-100">{name}</div>
            <div className="mt-1 text-xs text-slate-500">{r.evaluation_id} · {r.timestamp} · model {r.model?.model ?? "none"}{r.model?.fallback_used ? " (fallback)" : ""}</div>
          </div>
          <span className={`rounded-md border px-4 py-2 font-mono text-xl font-semibold ${STATUS_STYLE[r.completion_status] ?? ""}`}>{r.completion_status}</span>
        </div>
        <p className="mt-4 text-sm leading-relaxed text-slate-300">{r.executive_summary?.text}</p>
        <p className="mt-2 text-xs text-slate-500">
          Authoritative summary: deterministic · Definition of Done: {r.definition_of_done?.satisfied ? "SATISFIED" : "NOT SATISFIED"} · model narrative: {r.executive_summary?.llm_narrative_status ?? "NOT_PRODUCED"}
        </p>
        <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
          <Stat label="Findings" value={fmt(counts.open_findings)} />
          <Stat label="Integrity flags" value={fmt(counts.integrity_flags)} tone={counts.integrity_flags ? "text-red-300" : ""} />
          <Stat label="Manual review" value={r.manual_review?.required ? "YES" : "NO"} tone={r.manual_review?.required ? "text-red-300" : ""} />
          <Stat label="Engineering weaknesses" value={fmt(counts.engineering_weaknesses)} />
          <Stat label="Security findings" value={fmt(counts.security_findings)} tone={counts.security_findings ? "text-red-300" : ""} />
          <Stat label="Evaluator errors" value={fmt(counts.evaluator_errors)} tone={counts.evaluator_errors ? "text-fuchsia-300" : ""} />
        </div>
      </section>

      {(r.errors ?? []).length > 0 && (
        <Section title="Evaluator errors" hint="ARGUS failures, not project failures">
          <ul className="space-y-1 text-sm text-fuchsia-200">{r.errors.map((e: any, i: number) => <li key={i}><span className="font-mono">{e.stage}</span> — {e.kind}: {e.message}</li>)}</ul>
        </Section>
      )}

      <Section title="Findings" hint={`${findings.length} finding(s) · observations are not findings`}>
        {findings.length === 0 ? <p className="text-sm text-slate-400">No findings.</p> : (
          <div className="space-y-2">{findings.map((f) => <Finding key={f.finding_id} f={f} candidates={candidates} />)}</div>
        )}
        <div className="mt-4 text-xs text-slate-500">
          Manual review requirements: {(r.manual_review?.requirements ?? []).length === 0 ? "none" : r.manual_review.requirements.map((x: any) => `${x.finding_id} (${x.reason})`).join("; ")}
        </div>
      </Section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Section title="Repository overview">
          <KV k="Owner" v={repo.owner ?? "n/a"} />
          <KV k="Repository" v={repo.name} />
          <KV k="Default branch" v={repo.default_branch ?? "n/a"} />
          <KV k="HEAD" v={repo.evaluated_head ?? "n/a"} />
          <KV k="Commits" v={fmt(stats?.commits)} />
          <KV k="Human identities" v={fmt(stats?.contributors)} />
          <KV k="Branches" v={fmt(stats?.branches)} />
          <KV k="Tracked files" v={fmt(stats?.files)} />
          <KV k="Acquisition" v={repo.acquisition ? `${repo.acquisition.success ? "cloned" : "failed"} in ${repo.acquisition.runtime_s}s` : "n/a"} />
        </Section>

        <Section title="Code composition" hint={scc ? `counter: ${scc.tool} · meaningful LOC is an estimate` : undefined}>
          {scc ? (
            <div className="space-y-2">
              <div className="mb-3 grid grid-cols-2 gap-3">
                <Stat label="Raw LOC" value={fmt(scc.raw_code_loc)} />
                <Stat label="Meaningful estimate" value={fmt(scc.meaningful_source_loc_estimate)} />
              </div>
              {[["Source", "source"], ["Tests", "tests"], ["Config", "config"], ["Documentation", "docs"], ["CI", "ci"], ["Lockfiles", "lockfile"], ["Generated", "generated"]]
                .filter(([, k]) => cats[k]).map(([label, k]) => <Bar key={k} label={label} value={cats[k].code} max={scc.raw_code_loc} />)}
            </div>
          ) : <p className="text-sm text-slate-400">Not collected.</p>}
        </Section>
      </div>

      <Section title="Contributors" hint="Commit counts and LOC are forensic signals, not measures of quality · not ranked">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-slate-500">
              <tr><th className="py-2 pr-4">Identity</th><th className="pr-4">Authored</th><th className="pr-4">Co-authored</th><th className="pr-4">Raw +LOC</th><th className="pr-4">Meaningful +LOC (est.)</th><th className="pr-4">Active days</th><th>Policy</th></tr>
            </thead>
            <tbody>
              {contributors.map((c: any) => {
                const hits = anomalyByContributor(c.id);
                return (
                  <tr key={c.id} className="border-t border-slate-800">
                    <td className="py-2 pr-4 text-slate-200">{c.name} <span className="text-xs text-slate-500">{c.kind !== "human" ? `(${c.kind})` : ""}</span></td>
                    <td className="pr-4 font-mono">{fmt(c.authored_commits)}</td>
                    <td className="pr-4 font-mono">{fmt(c.coauthored_commits)}</td>
                    <td className="pr-4 font-mono">{fmt(c.raw_additions)}</td>
                    <td className="pr-4 font-mono">{fmt(c.meaningful_additions_estimate)}</td>
                    <td className="pr-4 font-mono">{fmt(c.active_days)}</td>
                    <td>{hits.length === 0 ? <span className="text-xs text-slate-600">—</span> : hits.map((f) => (
                      <Badge key={f.finding_id} className={TYPE_STYLE[f.finding_type]}>{f.finding_type.replaceAll("_", " ")} · {f.finding_id}</Badge>
                    ))}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {m.contributors && (
          <p className="mt-3 text-xs text-slate-500">
            Co-authored commits: {fmt(m.contributors.coauthorship?.total_coauthored_commits)} ({pct(m.contributors.coauthorship?.share_of_non_merge_commits)} of non-merge commits). Co-authorship alone is never evidence of misconduct. An anomaly label means a measured pattern, shown with its evidence under Findings.
          </p>
        )}
      </Section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Section title="Timeline">
          {tl ? (
            <>
              <KV k="First activity" v={tl.first_commit} />
              <KV k="Last activity" v={tl.last_commit} />
              <KV k="Active days" v={fmt(tl.active_days)} />
              <KV k="Commits per active day" v={fmt(tl.commits_per_active_day)} />
              <KV k="Deadline configured" v={tl.deadline ?? "none"} />
              <div className="mt-4 flex h-20 items-end gap-1" title="commits per active day (UTC)">
                {perDay.map((d) => <div key={d.date} title={`${d.date}: ${d.commits} commit(s)`} className="flex-1 rounded-t bg-sky-400/70" style={{ height: `${(d.commits / maxDay) * 100}%` }} />)}
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-slate-500"><span>{perDay[0]?.date}</span><span>commits per active day</span><span>{perDay[perDay.length - 1]?.date}</span></div>
            </>
          ) : <p className="text-sm text-slate-400">Not collected.</p>}
        </Section>

        <Section title="CI/CD" hint="Collected CI data — not a policy finding">
          <KV k="Workflow files" v={fmt((ci.workflow_files ?? []).length)} />
          <KV k="Capabilities detected" v={(ci.capabilities ?? []).join(", ") || "none"} />
          <KV k="Runs" v={runs ? fmt(runs.total_count) : gh.applicable ? "unavailable" : "not applicable"} />
          <KV k="Successful" v={runs ? fmt(runs.by_conclusion?.success ?? 0) : "n/a"} />
          <KV k="Failed" v={runs ? fmt(runs.by_conclusion?.failure ?? 0) : "n/a"} />
          <KV k="Cancelled" v={runs ? fmt(runs.by_conclusion?.cancelled ?? 0) : "n/a"} />
          <KV k="Pull requests" v={gh.pull_requests ? `${gh.pull_requests.count} (${gh.pull_requests.merged} merged)` : gh.applicable ? "unavailable" : "not applicable"} />
          <p className="mt-3 text-xs text-slate-500">
            Policy findings from CI: {findings.filter((f) => f.category === "CI_CD").length}. Run outcomes are reported as collected data; failed runs are not treated as integrity concerns.
            {(ci.consistency_findings ?? []).length > 0 && ` Workflow/repository mismatches: ${ci.consistency_findings.length}.`}
          </p>
        </Section>
      </div>

      <Section title="Security & hygiene" hint="Secret values are never stored or displayed">
        {hy ? (
          <div className="grid gap-x-8 md:grid-cols-2">
            <div>
              <KV k="Credential indicators" v={`${(hy.secrets?.indicators ?? []).filter((x: any) => x.severity !== "LOW").length} detected`} />
              <KV k="Environment files tracked" v={fmt((hy.environment?.real_env_files_tracked ?? []).length)} />
              <KV k="Example env file" v={hy.environment?.example_env_present ? "present" : "absent"} />
              <KV k=".gitignore" v={hy.gitignore?.present ? "present" : "missing"} />
              <KV k="Dependency issues" v={fmt((hy.dependencies?.issues ?? []).length)} />
            </div>
            <div className="mt-3 md:mt-0">
              {(hy.environment?.credential_variables ?? []).length > 0 && (
                <>
                  <div className="text-xs text-slate-400">Credential-named variables (classification only)</div>
                  <ul className="mt-1 space-y-1 text-xs">
                    {hy.environment.credential_variables.map((v: any, i: number) => (
                      <li key={i} className="text-slate-300"><span className="font-mono">{v.file}:{v.line}</span> {v.variable} → <span className="font-mono">{v.classification}</span></li>
                    ))}
                  </ul>
                </>
              )}
              <div className="mt-3 text-xs text-slate-400">Related findings</div>
              <ul className="mt-1 space-y-1 text-sm">
                {findings.filter((f) => ["REPOSITORY_HYGIENE", "SECRET_EXPOSURE"].includes(f.category)).map((f) => (
                  <li key={f.finding_id} className="text-slate-300"><span className="font-mono text-xs text-slate-400">{f.finding_id}</span> {f.title}</li>
                ))}
                {findings.filter((f) => ["REPOSITORY_HYGIENE", "SECRET_EXPOSURE"].includes(f.category)).length === 0 && <li className="text-slate-500">none</li>}
              </ul>
            </div>
          </div>
        ) : <p className="text-sm text-slate-400">Not collected.</p>}
      </Section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Section title="Repository observations" hint="Plain facts · not findings">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-300">
            {(r.observations ?? []).map((o: any) => <li key={o.id}>{o.text}{o.source === "llm" ? <span className="text-xs text-violet-300"> (noted by the model)</span> : null}</li>)}
          </ul>
        </Section>
        <Section title="Definition of Done" hint={`${fmt(counts.completed_checks)}/${fmt(counts.required_checks)} checks · ${fmt(counts.unverifiable)} unverifiable`}>
          <div className="flex flex-wrap gap-1.5">
            {(r.coverage ?? []).map((c: any) => (
              <span key={c.module} title={c.detail} className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${c.status === "PASS" ? "border-emerald-500/30 text-emerald-300" : c.status === "FAIL" ? "border-amber-500/40 text-amber-300" : c.status === "UNVERIFIABLE" ? "border-fuchsia-500/40 text-fuchsia-300" : "border-slate-700 text-slate-500"}`}>
                {c.module}: {c.status}
              </span>
            ))}
          </div>
        </Section>
      </div>

      <Section title="AI candidate disposition" hint={`${candidates.length} candidate(s) proposed by the model · every one decided by deterministic policy`}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="uppercase tracking-wider text-slate-500"><tr><th className="py-2 pr-3">ID</th><th className="pr-3">Step</th><th className="pr-3">Model claim</th><th className="pr-3">Proposed</th><th className="pr-3">Policy type</th><th className="pr-3">Disposition</th><th>Reason</th></tr></thead>
            <tbody>
              {candidates.map((c) => (
                <tr key={c.candidate_id} className="border-t border-slate-800 align-top">
                  <td className="py-1.5 pr-3 font-mono text-slate-400">{c.candidate_id}</td>
                  <td className="pr-3 text-slate-400">{c.step}</td>
                  <td className="pr-3 text-slate-200">{c.title}</td>
                  <td className="pr-3 font-mono text-slate-400">{c.proposed_category}/{c.proposed_severity}{c.proposed_manual_review ? "/review" : ""}</td>
                  <td className="pr-3 font-mono text-slate-300">{c.finding_type}</td>
                  <td className="pr-3 font-mono text-slate-300">{c.decision}{c.finding_id ? ` → ${c.finding_id}` : ""}</td>
                  <td className="text-slate-500">{c.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Reports">
        <div className="flex flex-wrap gap-3">
          <a className="rounded-md border border-slate-700 bg-slate-950 px-4 py-2 text-sm text-slate-200 hover:border-sky-500" href={links.report} target="_blank" rel="noreferrer">Markdown report</a>
          <a className="rounded-md border border-slate-700 bg-slate-950 px-4 py-2 text-sm text-slate-200 hover:border-sky-500" href={links.json} target="_blank" rel="noreferrer">JSON report</a>
          <button className="rounded-md border border-slate-700 bg-slate-950 px-4 py-2 text-sm text-slate-200 hover:border-sky-500" onClick={() => setShowJson(!showJson)}>{showJson ? "Hide" : "View"} Raw Evaluation JSON</button>
        </div>
        {showJson && <pre className="mt-4 max-h-[32rem] overflow-auto rounded-md border border-slate-800 bg-black/60 p-4 text-xs text-slate-300">{JSON.stringify(r, null, 2)}</pre>}
      </Section>
    </div>
  );
}

const PUBLIC_TEST_REPOS = [
  { repository: "shah314/graphcoloring", url: "https://github.com/shah314/graphcoloring", description: "Graph coloring · Java heuristics and DIMACS benchmarks" },
  { repository: "Docheinstein/itc2007-cct", url: "https://github.com/Docheinstein/itc2007-cct", description: "Timetabling · ITC2007 datasets and saved solutions" },
  { repository: "githubjonas/social-golfer", url: "https://github.com/githubjonas/social-golfer", description: "Social golfer · group scheduling and socialisation" },
  { repository: "ADDALemos/MPPTimetables", url: "https://github.com/ADDALemos/MPPTimetables", description: "Timetabling · MaxSAT and minimal perturbation" },
];

function repositorySelection(text: string) {
  const urls: string[] = [], invalid: string[] = [];
  let duplicates = 0;
  const seen = new Set<string>();
  for (const token of text.split(/[\s,;]+/).filter(Boolean)) {
    const match = token.match(/^https:\/\/github\.com\/([A-Za-z0-9][A-Za-z0-9-]{0,38})\/([A-Za-z0-9._-]{1,100}?)\/?$/);
    if (!match) { invalid.push(token); continue; }
    const name = match[2].replace(/\.git$/, "");
    if (!name || name === "." || name === "..") { invalid.push(token); continue; }
    const url = `https://github.com/${match[1]}/${name}`;
    if (seen.has(url.toLowerCase())) { duplicates++; continue; }
    seen.add(url.toLowerCase()); urls.push(url);
  }
  return { urls, invalid, duplicates };
}

export default function Home() {
  const [repositoryText, setRepositoryText] = useState("");
  const [query, setQuery] = useState("graph coloring");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [deterministicOnly, setDeterministicOnly] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [batch, setBatch] = useState<any>(null);
  const [savedBatches, setSavedBatches] = useState<any[]>([]);
  const [job, setJob] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [evaluationId, setEvaluationId] = useState("");
  const [resultSource, setResultSource] = useState<Source>("demo");
  const [saved, setSaved] = useState<any[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [ready, setReady] = useState<any>(null);
  const [providers, setProviders] = useState<any[]>([]);
  const [provider, setProvider] = useState("configured");
  const [backendDown, setBackendDown] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollingGeneration = useRef(0);
  const selection = repositorySelection(repositoryText);
  const running = submitting || ["running", "comparing", "stopping"].includes(batch?.state);
  const liveDisabled = DEMO_MODE || backendDown;
  const selectedProvider = providers.find(p => p.id === provider);
  const providerUnavailable = provider === "configured" ? ready?.ai_reasoning_available === false : !selectedProvider?.configured;

  const open = useCallback(async (id: string, source: Source) => {
    setError("");
    const r = await fetch(source === "demo" ? `${DEMO_BASE}/${id}.json` : `${API}/api/evaluate/${id}`).catch(() => null);
    if (!r || !r.ok) { setError("Could not load that evaluation."); return; }
    setResult(await r.json()); setEvaluationId(id); setResultSource(source);
  }, []);

  const refreshSaved = useCallback(async (): Promise<any[]> => {
    const demo: any[] = await fetch(`${DEMO_BASE}/index.json`).then((r) => r.ok ? r.json() : []).catch(() => []);
    const demoRows = demo.map((row) => ({ ...row, source: "demo" as Source }));
    if (DEMO_MODE) { setSaved(demoRows); return demoRows; }
    const live: any[] = await fetch(`${API}/api/evaluations`).then((r) => r.ok ? r.json() : []).catch(() => []);
    fetch(`${API}/api/batches`).then(r => r.ok ? r.json() : []).then(setSavedBatches).catch(() => null);
    const liveRows = live.map((row) => ({ ...row, source: "api" as Source }));
    const ids = new Set(liveRows.map((row) => row.evaluation_id));
    const rows = [...liveRows, ...demoRows.filter((row) => !ids.has(row.evaluation_id))];
    setSaved(rows); return rows;
  }, []);

  const stopPolling = useCallback(() => {
    pollingGeneration.current++;
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  }, []);

  const trackBatch = useCallback((id: string) => {
    stopPolling();
    const generation = pollingGeneration.current;
    let inFlight = false;
    let firstPoll = true;
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const response = await fetch(`${API}/api/batches/${id}`).catch(() => null);
        if (generation !== pollingGeneration.current || !response) return;
        if (!response.ok) {
          if (timer.current) clearInterval(timer.current);
          setBatch(null); setJob(null);
          setError("This batch is no longer available. Completed reports are listed below.");
          try { localStorage.removeItem("argus.latestBatch"); } catch {}
          return;
        }
        const value = await response.json();
        if (generation !== pollingGeneration.current) return;
        if (firstPoll) {
          if (!value.fixture) setRepositoryText((text) => text.trim() ? text : value.items.map((item: any) => `https://github.com/${item.repository}`).join("\n"));
          if (["running", "comparing", "stopping"].includes(value.state)) { setDeterministicOnly(value.items.every((item: any) => item.deterministic_only)); setProvider(value.provider ?? "configured"); }
          firstPoll = false;
        }
        setBatch(value); setJob(value.items.find((item: any) => item.state === "running") ?? null);
        if (!["running", "comparing", "stopping"].includes(value.state)) {
          if (timer.current) clearInterval(timer.current);
          await refreshSaved();
          fetch(`${API}/api/ready`).then((r) => r.json()).then(setReady).catch(() => null);
        }
      } catch {
        if (generation === pollingGeneration.current) setError("Could not update batch status. Retrying…");
      } finally { inFlight = false; }
    };
    timer.current = setInterval(poll, 1500);
    void poll();
  }, [refreshSaved, stopPolling]);

  useEffect(() => {
    (async () => {
      if (DEMO_MODE) {
        const rows = await refreshSaved();
        if (rows[0]) await open(rows[0].evaluation_id, "demo");
        return;
      }
      const ok = await fetch(`${API}/api/health`).then((r) => r.json()).then((h) => { setHealth(h); return true; }).catch(() => false);
      setBackendDown(!ok);
      if (ok) {
        fetch(`${API}/api/providers`).then(r => r.ok ? r.json() : []).then(setProviders).catch(() => setProviders([]));
        fetch(`${API}/api/ready`).then((r) => r.json()).then(setReady).catch(() => setReady(null));
        try { const id = localStorage.getItem("argus.latestBatch"); if (id) trackBatch(id); } catch {}
      }
      await refreshSaved();
    })();
    return stopPolling;
  }, [refreshSaved, open, trackBatch, stopPolling]);

  const addRepository = (url: string) => setRepositoryText((text) => repositorySelection(text).urls.some((u) => u.toLowerCase() === url.toLowerCase()) ? text : `${text.trim()}${text.trim() ? "\n" : ""}${url}`);

  const search = async () => {
    if (liveDisabled || query.trim().length < 2) return;
    setSearching(true); setSearchError(""); setSearched(false);
    try {
      const r = await fetch(`${API}/api/repositories/search?q=${encodeURIComponent(query.trim())}`);
      const body = await r.json();
      if (!r.ok) { setSearchError(typeof body.detail === "string" ? body.detail : "Search unavailable."); return; }
      setSearchResults(body); setSearched(true);
    } catch { setSearchError("Cannot reach GitHub search. Paste links or use the public test repositories."); }
    finally { setSearching(false); }
  };

  const evaluate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (DEMO_MODE) return;
    if (!selection.urls.length || selection.invalid.length || selection.urls.length > 50) return;
    setSubmitting(true); setError(""); setResult(null);
    try {
      const r = await fetch(`${API}/api/batches`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ urls: selection.urls, deterministic_only: deterministicOnly, provider }) });
      const body = await r.json();
      if (!r.ok) { setError(typeof body.detail === "string" ? body.detail : "The API rejected the repository list."); return; }
      setBatch(body); setJob(body.items.find((item: any) => item.state === "running") ?? null);
      try { localStorage.setItem("argus.latestBatch", body.batch_id); } catch {}
      trackBatch(body.batch_id);
    } catch { setBackendDown(true); setError("Cannot reach the local ARGUS backend. Start it and reload this page."); }
    finally { setSubmitting(false); }
  };

  const stopEvaluation = async () => {
    if (!batch || stopping) return;
    setStopping(true); setError("");
    try {
      const response = await fetch(`${API}/api/batches/${batch.batch_id}/stop`, {method: "POST"});
      if (!response.ok) throw new Error();
      setBatch(await response.json());
    } catch { setError("Could not stop the evaluation. Retry Stop evaluation."); }
    finally { setStopping(false); }
  };

  const repositoryCards = (rows: any[]) => rows.map((repo) => {
    const added = selection.urls.some((url) => url.toLowerCase() === repo.url.toLowerCase());
    return <li key={repo.url} className="flex items-start justify-between gap-3 rounded-md border border-slate-800 bg-slate-950/60 p-3">
      <div className="min-w-0"><a href={repo.url} target="_blank" rel="noreferrer" className="break-all font-mono text-xs text-sky-200 hover:underline">{repo.repository}</a><p className="mt-1 text-xs text-slate-400">{repo.description}</p></div>
      <button type="button" onClick={() => addRepository(repo.url)} disabled={running || added} aria-label={`Add ${repo.repository}`} className="rounded border border-slate-600 px-3 py-1 text-xs text-slate-200 hover:border-sky-500 disabled:opacity-40">{added ? "Added" : "Add"}</button>
    </li>;
  });

  return (
    <main className="min-h-screen bg-slate-950 text-slate-200">
      <header className="border-b border-slate-800 bg-slate-950"><div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-5">
        <div><div className="font-mono text-2xl font-semibold tracking-[0.25em] text-slate-50">ARGUS</div><div className="text-sm text-slate-400">Repository Forensics &amp; Engineering Integrity Agent</div></div>
        <div className="text-right text-xs text-slate-500">{DEMO_MODE ? "Public demo · saved real evaluation · no backend" : health ? <>Local backend connected · AI reasoning {ready?.ai_reasoning_available ? "available" : "unavailable"}</> : "Connecting to local backend…"}</div>
      </div></header>
      <div className="mx-auto max-w-6xl space-y-5 px-6 py-8">
        <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-6">
          <h1 className="text-2xl font-semibold text-slate-50">Evaluate multiple repositories</h1>
          <p className="mt-2 text-sm text-slate-400">Build a repository list, get a report for each project, and cross-check code and README similarity across the batch.</p>
          {!DEMO_MODE && ready?.model && <p className="mt-2 text-sm text-slate-400">Configured reasoning model: <span className="font-mono text-sky-200">{ready.model}</span> · {ready.ai_reasoning_available ? "ready" : "unavailable"}</p>}
          {DEMO_MODE && <div className="mt-4 rounded-md border border-sky-500/30 bg-sky-500/10 p-3 text-sm text-sky-100"><strong>Public demo.</strong> This page shows a saved, real Qwen3-8B evaluation. Live evaluation is not available here: start the local ARGUS backend to evaluate a batch.</div>}
          {!DEMO_MODE && backendDown && <p className="mt-4 text-sm text-amber-200">The local backend is not reachable. Start ARGUS and reload to evaluate repositories.</p>}
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <form onSubmit={evaluate} className="space-y-3">
              <label className="block"><span className="mb-2 block text-sm font-medium">Repository links</span>
                <textarea value={repositoryText} onChange={(e) => setRepositoryText(e.target.value)} required rows={8} maxLength={20000} disabled={running || liveDisabled} placeholder={"https://github.com/owner/first-repository\nhttps://github.com/owner/second-repository"} className="w-full rounded-md border border-slate-700 bg-slate-950 p-3 font-mono text-xs text-slate-100 outline-none focus:border-sky-500" />
              </label>
              <p className="text-xs text-slate-400">Paste repository home-page URLs, one per line. You can also use commas or spaces. Up to 50 repositories per batch.</p>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <label className="cursor-pointer text-xs text-sky-200">Import a .txt link list<input aria-label="Import repository links" type="file" accept=".txt,text/plain" disabled={running || liveDisabled} className="mt-1 block max-w-full text-xs text-slate-400" onChange={async (e) => {
                  const input = e.currentTarget, file = input.files?.[0];
                  if (!file) return;
                  if (file.size > 100000) { setError("Use a text file smaller than 100 KB."); input.value = ""; return; }
                  try { setRepositoryText(await file.text()); setError(""); } catch { setError("Could not read that text file."); }
                  input.value = "";
                }} /></label>
                <button type="button" onClick={() => { setRepositoryText(""); setError(""); }} disabled={running} className="text-xs text-slate-400 hover:text-white">Clear links</button>
              </div>
              <p className="text-sm text-sky-200">{selection.urls.length} {selection.urls.length === 1 ? "repository" : "repositories"} selected{selection.duplicates > 0 ? ` · ${selection.duplicates} duplicate(s) ignored` : ""}</p>
              {selection.invalid.length > 0 && <p className="break-all text-xs text-red-300">Fix these links: {selection.invalid.slice(0, 3).join(", ")}{selection.invalid.length > 3 ? "…" : ""}</p>}
              {selection.urls.length > 50 && <p className="text-xs text-red-300">Select at most 50 repositories.</p>}
              {!DEMO_MODE && <div className="space-y-2"><label className="block text-xs text-slate-300">AI provider<select aria-label="AI provider" value={provider} onChange={e => setProvider(e.target.value)} disabled={running || liveDisabled} className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2">{providers.length ? providers.map(p => <option key={p.id} value={p.id}>{p.id === "configured" ? "Server default" : p.id === "openai" ? "OpenAI API" : "Claude API"} · {p.model}{p.configured ? "" : " · API key required"}</option>) : <option value="configured">Server default</option>}</select></label>{selectedProvider && <p className="text-xs text-slate-400">{selectedProvider.provider} · {selectedProvider.model}{provider !== "configured" ? " · Sends evaluation evidence to the selected API; usage is billed to your API account." : ""}</p>}<details className="text-xs text-slate-400"><summary className="cursor-pointer">Configure OpenAI or Claude</summary><p className="mt-2">Set OPENAI_API_KEY or ANTHROPIC_API_KEY in the backend environment and restart the backend. Optional model overrides: ARGUS_OPENAI_MODEL and ARGUS_ANTHROPIC_MODEL. Keys stay on the server.</p></details></div>}
              <label className="flex items-start gap-2 text-xs text-slate-400"><input type="checkbox" checked={deterministicOnly} onChange={(e) => setDeterministicOnly(e.target.checked)} disabled={running || liveDisabled} className="mt-0.5" /><span>Deterministic evidence only (skip AI reasoning). These reports are INCOMPLETE_EVALUATION because model checks do not run.</span></label>
              {!DEMO_MODE && providerUnavailable && !deterministicOnly && <p className="text-xs text-amber-200">The selected provider is unavailable. Start its runtime or configure its API key, or select deterministic evidence only.</p>}
              <button type="submit" disabled={running || liveDisabled || !selection.urls.length || !!selection.invalid.length || selection.urls.length > 50 || (!deterministicOnly && providerUnavailable)} className="w-full rounded-md bg-sky-500 px-5 py-3 font-semibold text-slate-950 hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40">{running ? `Evaluating batch · ${batch?.completed ?? 0}/${batch?.total ?? selection.urls.length}` : `Evaluate ${selection.urls.length || "selected"} ${selection.urls.length === 1 ? "repository" : "repositories"}`}</button>
              <p className="text-xs text-slate-500">Repositories are queued one at a time. Closing this page does not cancel the batch.</p>
              {error && <p role="alert" className="rounded border border-red-500/30 p-3 text-sm text-red-200">{error}</p>}
            </form>
            <div className="space-y-4">
              <div><h2 className="text-sm font-semibold text-slate-100">Find public repositories</h2><div className="mt-2 flex gap-2"><input aria-label="Search public GitHub repositories" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void search(); } }} maxLength={120} placeholder="graph coloring, social golfer, timetabling…" className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm" /><button type="button" onClick={search} disabled={searching || liveDisabled || query.trim().length < 2} className="rounded border border-sky-500/40 px-3 py-2 text-sm text-sky-200 disabled:opacity-40">{searching ? "Searching…" : "Search GitHub"}</button></div>
                {searchError && <p role="alert" className="mt-2 text-xs text-amber-200">{searchError}</p>}
                {searched && !searchResults.length && <p className="mt-2 text-xs text-slate-400">No public repositories found. Try another search.</p>}
                {!!searchResults.length && <ul className="mt-3 max-h-64 space-y-2 overflow-auto">{repositoryCards(searchResults)}</ul>}
              </div>
              <div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold text-slate-100">Public test repositories</h2><button type="button" disabled={running} onClick={() => PUBLIC_TEST_REPOS.forEach((repo) => addRepository(repo.url))} className="text-xs text-sky-200 hover:underline">Add all 4 test repositories</button></div>
              <ul className="space-y-2">{repositoryCards(PUBLIC_TEST_REPOS)}</ul>
            </div>
          </div>
        </section>

        {!DEMO_MODE && !!savedBatches.length && <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4"><label className="text-sm text-slate-300">View saved batch results<select aria-label="View saved batch results" value={batch?.batch_id ?? ""} disabled={running} onChange={e => { if (e.target.value) { setError(""); setRepositoryText(""); trackBatch(e.target.value); try { localStorage.setItem("argus.latestBatch", e.target.value); } catch {} } }} className="mt-2 w-full rounded border border-slate-700 bg-slate-950 p-2 text-xs"><option value="">Choose a completed batch to display its graphs</option>{batch && !savedBatches.some(b => b.batch_id === batch.batch_id) && <option value={batch.batch_id}>Current batch · {batch.total} repositories</option>}{savedBatches.map(b => <option key={b.batch_id} value={b.batch_id}>{b.batch_id} · {b.total} repositories · {b.model} · {b.state.replaceAll("_", " ")}</option>)}</select></label></div>}
        {batch && <Section title="Repository statistics" hint="Per-repository measurements · shared comparison scales"><RepositoryStatistics key={batch.batch_id} api={API} batchId={batch.batch_id} revision={`${batch.completed}:${batch.state}`} /></Section>}
        {batch && <Section title="Batch evaluation" hint={`${batch.completed}/${batch.total} finished · ${batch.state.replaceAll("_", " ")} · ${batch.elapsed_s}s`}>
          {running && <button type="button" onClick={stopEvaluation} disabled={stopping || batch.state === "stopping"} className="mb-4 rounded border border-red-500/60 bg-red-500/15 px-4 py-2 text-sm font-semibold text-red-200 disabled:opacity-50">{stopping || batch.state === "stopping" ? "Stopping evaluation…" : "Stop evaluation"}</button>}
          {batch.state === "cancelled" && <p role="status" className="mb-3 text-sm text-amber-200">Evaluation stopped. {batch.cancelled ?? 0} repositories cancelled. Completed reports remain available.</p>}
          {batch.state === "stopping" && <p role="status" className="mb-3 text-sm text-amber-200">Stopping the active worker and cancelling the remaining queue…</p>}
          <p className="mb-3 text-xs text-slate-400">{batch.fixture && <strong className="mr-2 text-sky-200">Controlled local test · generated repositories, not public GitHub links.</strong>}Model: {batch.model} · Each result keeps its own integrity status.</p>
          <div className="max-h-96 overflow-auto"><table className="w-full text-left text-sm"><thead className="text-xs text-slate-500"><tr><th className="pb-2">Repository</th><th>Status</th><th>Report</th></tr></thead><tbody>
            {batch.items.map((item: any) => <tr key={item.job_id} className="border-t border-slate-800"><td className="py-3 pr-3">{batch.fixture ? <span className="break-all font-mono text-xs text-sky-200">{item.repository}</span> : <a href={`https://github.com/${item.repository}`} target="_blank" rel="noreferrer" className="break-all font-mono text-xs text-sky-200">{item.repository}</a>}{item.error && <p className="mt-1 text-xs text-red-300">{item.error}</p>}</td><td className="pr-3">{item.similarity_flagged && <div className="mb-1"><Badge className={STATUS_STYLE.FLAGGED}>CODE OVERLAP · REVIEW REQUIRED</Badge></div>}{item.completion_status ? <Badge className={STATUS_STYLE[item.completion_status]}>{item.completion_status}</Badge> : <span className={item.state === "failed" ? "text-red-300" : "text-slate-300"}>{item.state === "running" ? item.stages[item.stage_index] ?? "Running" : item.state === "queued" ? "Queued" : item.state === "failed" ? "Failed" : item.state === "cancelled" ? "Stopped" : "Report ready"}</span>}</td><td>{item.evaluation_id && <button onClick={() => open(item.evaluation_id, "api")} className="rounded border border-slate-600 px-3 py-1 text-xs hover:border-sky-500">Open report</button>}</td></tr>)}
          </tbody></table></div>
          {batch.state === "comparing" && <p className="mt-3 text-sm text-sky-200">Comparing repository code and README patterns…</p>}
          {batch.cross_validation_error && <p role="alert" className="mt-3 text-sm text-amber-200">{batch.cross_validation_error}</p>}
          {batch.persistence_error && <p role="alert" className="mt-3 text-sm text-amber-200">{batch.persistence_error}</p>}
        </Section>}

        {job && <Section title="Current evaluation" hint={job.repository}><ol className="mb-3 flex flex-wrap gap-4 text-xs text-slate-400">{job.stages.map((stage: string, i: number) => <li key={stage} className={i === job.stage_index ? "text-sky-200" : ""}>{i < job.stage_index ? "✓ " : ""}{stage}{job.deterministic_only && i === 2 ? " (skipped)" : ""}</li>)}</ol><pre className="max-h-40 overflow-auto rounded border border-slate-800 bg-black/40 p-3 text-xs text-slate-400">{job.log.join("\n")}</pre></Section>}

        {!!batch?.cross_validation?.length && <Section title="Cross-repository checks" hint={`${batch.cross_validation.length} repository pairs · README structure is advisory`}>
          <div className="max-h-96 overflow-auto"><table className="w-full text-left text-xs"><thead className="text-slate-500"><tr><th className="pb-2">Repository pair</th><th className="pr-3">Code A → B</th><th className="pr-3">Code B → A</th><th className="pr-3">README text</th><th>README headings</th></tr></thead><tbody>{batch.cross_validation.map((pair: any) => <tr key={`${pair.a}:${pair.b}`} className="border-t border-slate-800"><td className="py-3 pr-3"><div>A: {pair.a}</div><div>B: {pair.b}</div>{pair.flagged && <div className="mt-2 text-rose-300">FLAGGED · code overlap ≥ {Math.round(pair.threshold * 100)}% · review required</div>}</td>{[pair.code_a_in_b, pair.code_b_in_a, pair.readme_text_similarity, pair.readme_heading_similarity].map((value: any, i: number) => <td key={i} className="pr-3">{typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "Unavailable"}</td>)}</tr>)}</tbody></table></div>
          <p className="mt-3 text-xs text-slate-500">Code overlap uses token-shingle containment in both directions. Code overlap at or above the configured threshold flags both participants for review and excludes them from the primary statistics. Shared templates, libraries and attribution still require review; overlap alone does not establish copying direction or intent.</p>
        </Section>}

        {result && <Dashboard r={result} links={reportLinks(evaluationId, resultSource)} source={resultSource} />}
        <Section title="Completed evaluations" hint={DEMO_MODE ? "Saved real ARGUS result bundled with this page" : "Saved reports are available without re-running evaluations"}>
          {saved.length === 0 ? <p className="text-sm text-slate-400">No saved evaluations yet.</p> : <ul className="divide-y divide-slate-800">{saved.map((s) => <li key={s.evaluation_id} className="flex flex-wrap items-center justify-between gap-3 py-3"><div><span className="font-mono text-sm">{s.repository}</span><span className="ml-3 text-xs text-slate-500">{s.timestamp} · {s.model ?? "no model"} · {s.findings} finding(s){s.source === "demo" ? " · bundled demo result" : ""}</span></div><div className="flex items-center gap-3"><Badge className={STATUS_STYLE[s.status]}>{s.status}</Badge><button onClick={() => open(s.evaluation_id, s.source)} className="rounded border border-slate-700 px-3 py-1 text-xs hover:border-sky-500">Open</button></div></li>)}</ul>}
        </Section>
      </div>
    </main>
  );
}
