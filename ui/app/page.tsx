/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// Presentation only. Every number and status on this page is read from the ARGUS result;
// nothing is computed or reinterpreted here.
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

export default function Home() {
  const [url, setUrl] = useState("");
  const [deterministicOnly, setDeterministicOnly] = useState(false);
  const [job, setJob] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [evaluationId, setEvaluationId] = useState("");
  const [resultSource, setResultSource] = useState<Source>("demo");
  const [saved, setSaved] = useState<any[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [ready, setReady] = useState<any>(null);
  const [backendDown, setBackendDown] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const open = useCallback(async (id: string, source: Source) => {
    setError("");
    const r = await fetch(source === "demo" ? `${DEMO_BASE}/${id}.json` : `${API}/api/evaluate/${id}`).catch(() => null);
    if (!r || !r.ok) { setError("Could not load that evaluation."); return; }
    setResult(await r.json());
    setEvaluationId(id);
    setResultSource(source);
    setJob(null);
    window.scrollTo({ top: 0 });
  }, []);

  // Saved evaluations: from the local backend when one is configured and reachable, plus the bundled demo result.
  const refreshSaved = useCallback(async (): Promise<any[]> => {
    const demo: any[] = await fetch(`${DEMO_BASE}/index.json`).then((r) => (r.ok ? r.json() : [])).catch(() => []);
    const demoRows = demo.map((row) => ({ ...row, source: "demo" as Source }));
    if (DEMO_MODE) { setSaved(demoRows); return demoRows; }
    const live: any[] | null = await fetch(`${API}/api/evaluations`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const liveRows = (live ?? []).map((row) => ({ ...row, source: "api" as Source }));
    const ids = new Set(liveRows.map((row) => row.evaluation_id));
    const rows = [...liveRows, ...demoRows.filter((row) => !ids.has(row.evaluation_id))];
    setSaved(rows);
    return rows;
  }, []);

  useEffect(() => {
    (async () => {
      if (DEMO_MODE) {
        const rows = await refreshSaved();
        if (rows[0]) await open(rows[0].evaluation_id, "demo");  // the public demo opens straight onto the saved evaluation
        return;
      }
      const ok = await fetch(`${API}/api/health`).then((r) => r.json()).then((h) => { setHealth(h); return true; }).catch(() => false);
      setBackendDown(!ok);
      if (ok) fetch(`${API}/api/ready`).then((r) => r.json()).then(setReady).catch(() => setReady(null));
      await refreshSaved();
    })();
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [refreshSaved, open]);

  const evaluate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (DEMO_MODE) return;  // the public demo never starts (or imitates) an evaluation
    setError(""); setResult(null);
    const r = await fetch(`${API}/api/evaluate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: url.trim(), deterministic_only: deterministicOnly }) }).catch(() => null);
    if (!r) { setBackendDown(true); setError("Cannot reach the local ARGUS backend. Start it and reload this page."); return; }
    const body = await r.json();
    if (!r.ok) { setError(typeof body.detail === "string" ? body.detail : "The API rejected the request."); return; }
    setReady((x: any) => (x ? { ...x, accepting_evaluations: false } : x));
    setJob(body);
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(async () => {
      const s = await fetch(`${API}/api/jobs/${body.job_id}`).then((x) => x.json()).catch(() => null);
      if (!s) return;
      setJob(s);
      if (s.state !== "running") {
        if (timer.current) clearInterval(timer.current);
        if (s.state === "done") { await open(s.evaluation_id, "api"); refreshSaved(); }
        else setError(s.error ?? "Evaluation failed.");
        fetch(`${API}/api/ready`).then((x) => x.json()).then(setReady).catch(() => null);
      }
    }, 1500);
  };

  const liveDisabled = DEMO_MODE || backendDown;

  const running = job?.state === "running";

  return (
    <main className="min-h-screen bg-slate-950 text-slate-200">
      <header className="border-b border-slate-800 bg-slate-950">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-5">
          <div>
            <div className="font-mono text-2xl font-semibold tracking-[0.25em] text-slate-50">ARGUS</div>
            <div className="text-sm text-slate-400">Repository Forensics &amp; Engineering Integrity Agent</div>
          </div>
          <div className="text-right text-xs text-slate-500">
            {DEMO_MODE ? <>Public demo · saved real evaluation · no backend</>
              : health ? <>Local backend connected · AI reasoning {ready ? (ready.ai_reasoning_available ? "available" : "unavailable") : "unknown"}{ready && !ready.accepting_evaluations ? " · busy" : ""}</>
              : "Local backend not reachable"}
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl space-y-5 px-6 py-8">
        <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-6">
          <p className="text-sm text-slate-300">Deterministic repository evidence + AI-assisted reasoning + policy-controlled evaluation.</p>
          {DEMO_MODE && (
            <div className="mt-4 rounded-md border border-sky-500/30 bg-sky-500/10 px-4 py-3 text-sm text-sky-100">
              <span className="font-semibold">Public demo.</span> This page shows a saved, real ARGUS evaluation (Qwen3-8B on a public GitHub repository). Live evaluation is not available here: it needs the ARGUS backend and a local Qwen3 model, which run on your own machine. See the README section &ldquo;Local full evaluation&rdquo;.
            </div>
          )}
          {!DEMO_MODE && backendDown && (
            <div className="mt-4 rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
              The local ARGUS backend is not reachable, so live evaluation is disabled. Start it with <span className="font-mono">python -m uvicorn argus.server:app --port 8000</span> and reload. The bundled saved evaluation below is still available.
            </div>
          )}
          <form onSubmit={evaluate} className="mt-4 flex flex-col gap-3 md:flex-row">
            <label className="flex-1">
              <span className="mb-1 block text-xs uppercase tracking-wider text-slate-500">GitHub Repository URL</span>
              <input value={url} onChange={(e) => setUrl(e.target.value)} required placeholder="https://github.com/owner/repository" disabled={running || liveDisabled}
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2.5 font-mono text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-sky-500" />
            </label>
            <button type="submit" disabled={running || liveDisabled} title={DEMO_MODE ? "Live evaluation requires a local ARGUS backend" : undefined} className="self-end rounded-md bg-sky-500 px-5 py-2.5 text-sm font-semibold text-slate-950 hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50">
              {running ? "Evaluating…" : "Evaluate Repository"}
            </button>
          </form>
          <label className="mt-3 flex items-start gap-2 text-xs text-slate-400">
            <input type="checkbox" checked={deterministicOnly} onChange={(e) => setDeterministicOnly(e.target.checked)} disabled={running || liveDisabled} className="mt-0.5" />
            <span>Deterministic evidence only (skip AI reasoning). Finishes in seconds; the result is reported as INCOMPLETE_EVALUATION because the reasoning checks did not run. A full evaluation with the local model on CPU can take 20–45 minutes or more.</span>
          </label>
          <p className="mt-3 text-xs text-slate-500">Analyze repository history, contributors, code composition, CI/CD, security hygiene and engineering signals.</p>
          {error && <p className="mt-3 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">{error}</p>}
        </section>

        {job && job.state !== "done" && (
          <Section title="Evaluation in progress" hint={`${job.elapsed_s}s elapsed`}>
            <div className="grid gap-6 md:grid-cols-3">
              <div>
                <KV k="Repository" v={job.repository} />
                <KV k="Model" v={job.model ?? "…"} />
                <KV k="Status" v={job.state === "running" ? "Running…" : job.state.toUpperCase()} />
              </div>
              <ol className="space-y-2 text-sm">
                {job.stages.map((s: string, i: number) => {
                  const skipped = job.deterministic_only && i === 2;
                  const state = i < job.stage_index ? "done" : i === job.stage_index && job.state === "running" ? "active" : "pending";
                  return (
                    <li key={s} className={`flex items-center gap-2 ${state === "done" ? "text-emerald-300" : state === "active" ? "text-sky-300" : "text-slate-500"}`}>
                      <span className="w-4 font-mono">{state === "done" ? "✓" : state === "active" ? "→" : "·"}</span>{s}{skipped ? " (skipped)" : ""}
                    </li>
                  );
                })}
              </ol>
              <pre className="max-h-48 overflow-auto rounded-md border border-slate-800 bg-black/50 p-3 text-[11px] text-slate-400">{(job.log ?? []).join("\n")}</pre>
            </div>
          </Section>
        )}

        {result && <Dashboard r={result} links={reportLinks(evaluationId, resultSource)} source={resultSource} />}

        <Section title="Completed evaluations" hint={DEMO_MODE ? "Saved real ARGUS result bundled with this page" : "Real ARGUS results — nothing is re-run"}>
          {saved.length === 0 ? <p className="text-sm text-slate-400">No saved evaluations yet.</p> : (
            <ul className="divide-y divide-slate-800">
              {saved.map((s) => (
                <li key={s.evaluation_id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
                  <div>
                    <span className="font-mono text-sm text-slate-100">{s.repository}</span>
                    <span className="ml-3 text-xs text-slate-500">{s.timestamp} · {s.model ?? "no model"} · {s.findings} finding(s){s.source === "demo" ? " · bundled demo result" : ""}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge className={STATUS_STYLE[s.status]}>{s.status}</Badge>
                    <button onClick={() => open(s.evaluation_id, s.source)} className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:border-sky-500">Open</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </main>
  );
}
