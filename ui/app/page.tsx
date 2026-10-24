/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import RepositoryStatistics from "./repository-statistics";
import { FadeContent, SplitText } from "./react-bits";
import { BatchResults, SavedEvaluations, TaskComparisonPanel } from "./results-explorer";
import { TaskResultPanel } from "./task-results";
import {
  Badge,
  Bar,
  EmptyState,
  KV,
  SEVERITY_STYLE,
  STATUS_STYLE,
  Section,
  Stat,
  TYPE_STYLE,
  buttonGhost,
  buttonPrimary,
  buttonSecondary,
  fmt,
  formatTimestamp,
  inputClass,
  pct,
  statusLabel,
} from "./ui-kit";

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

function Finding({ f, candidates }: { f: any; candidates: any[] }) {
  const [open, setOpen] = useState(false);
  const security = f.category === "SECRET_EXPOSURE";
  const related = candidates.filter((c) => c.finding_id === f.finding_id);
  // Reports written before the statement became policy-generated carry the model's wording in `finding`.
  const statementIsDeterministic = f.text_origin === "deterministic" || f.origin === "deterministic";
  return (
    <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-950/50 transition hover:border-slate-700">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`finding-${f.finding_id}`}
        onClick={() => setOpen(!open)}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 text-left transition hover:bg-slate-900/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-400/60"
      >
        <span className="font-mono text-xs text-slate-400">{f.finding_id}</span>
        <span className="min-w-0 flex-1 text-sm font-medium text-slate-100">{f.title}</span>
        <Badge className={TYPE_STYLE[security ? "SECURITY" : f.finding_type]}>{security ? "SECURITY" : f.finding_type.replaceAll("_", " ")}</Badge>
        <Badge className={SEVERITY_STYLE[f.severity]}>{f.severity}</Badge>
        <Badge className="border-slate-700 text-slate-300">{f.material ? "MATERIAL" : "NON-MATERIAL"}</Badge>
        <Badge className="border-slate-700 text-slate-300">OUTCOME {f.outcome}</Badge>
        <Badge className={f.requires_manual_review ? "border-red-500/50 bg-red-500/15 text-red-300" : "border-slate-700 text-slate-400"}>
          MANUAL REVIEW: {f.requires_manual_review ? "YES" : "NO"}
        </Badge>
        <span aria-hidden="true" className="text-slate-500">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div id={`finding-${f.finding_id}`} className="argus-expand grid gap-4 border-t border-slate-800 p-4 md:grid-cols-2">
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
    <div id="report" className="scroll-mt-24 space-y-5">
      <section className="relative overflow-hidden rounded-xl border border-slate-800 bg-slate-900/55 p-5 shadow-[0_24px_80px_-56px_rgba(56,189,248,0.65)] sm:p-6">
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-sky-400/70 to-transparent" />
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Evaluation result{source === "demo" ? " · saved real evaluation (bundled with this page)" : ""}</div>
            <div className="mt-1 break-all font-mono text-lg text-slate-100">{name}</div>
            <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-xs text-slate-500">
              <span>{r.evaluation_id}</span><span aria-hidden="true">·</span>
              <span title={r.timestamp}>{formatTimestamp(r.timestamp)}</span><span aria-hidden="true">·</span>
              <span>model {r.model?.model ?? "none"}{r.model?.fallback_used ? " (fallback)" : ""}</span>
            </div>
          </div>
          <Badge className={`px-3 py-1.5 text-sm font-semibold ${STATUS_STYLE[r.completion_status] ?? "border-slate-700 text-slate-300"}`} title={r.completion_status}>
            {statusLabel(r.completion_status)}
          </Badge>
        </div>
        <p className="mt-4 text-sm leading-relaxed text-slate-300">{r.executive_summary?.text}</p>
        <p className="mt-2 text-xs leading-relaxed text-slate-500">
          Authoritative summary: deterministic · Definition of Done: {r.definition_of_done?.satisfied ? "SATISFIED" : "NOT SATISFIED"} · model narrative: {r.executive_summary?.llm_narrative_status ?? "NOT_PRODUCED"}
        </p>
        <div className="mt-5 grid grid-cols-2 gap-2.5 md:grid-cols-3 lg:grid-cols-6">
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

      <FadeContent>
        <TaskResultPanel evaluation={r} />
      </FadeContent>

      <Section id="findings" title="Findings" hint={`${findings.length} finding(s) · observations are not findings`}>
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
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-slate-500">
              <tr><th className="py-2 pr-4">Identity</th><th className="pr-4">Authored</th><th className="pr-4">Co-authored</th><th className="pr-4">Raw +LOC</th><th className="pr-4">Meaningful +LOC (est.)</th><th className="pr-4">Active days</th><th>Policy</th></tr>
            </thead>
            <tbody>
              {contributors.map((c: any) => {
                const hits = anomalyByContributor(c.id);
                return (
                  <tr key={c.id} className="border-t border-slate-800">
                    <td className="max-w-[18rem] break-words py-2 pr-4 text-slate-200">{c.name} <span className="text-xs text-slate-500">{c.kind !== "human" ? `(${c.kind})` : ""}</span></td>
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
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="uppercase tracking-wider text-slate-500"><tr><th className="py-2 pr-3">ID</th><th className="pr-3">Step</th><th className="pr-3">Model claim</th><th className="pr-3">Proposed</th><th className="pr-3">Policy type</th><th className="pr-3">Disposition</th><th>Reason</th></tr></thead>
            <tbody>
              {candidates.map((c) => (
                <tr key={c.candidate_id} className="border-t border-slate-800 align-top">
                  <td className="py-1.5 pr-3 font-mono text-slate-400">{c.candidate_id}</td>
                  <td className="pr-3 text-slate-400">{c.step}</td>
                  <td className="max-w-[16rem] break-words pr-3 text-slate-200">{c.title}</td>
                  <td className="pr-3 font-mono text-slate-400">{c.proposed_category}/{c.proposed_severity}{c.proposed_manual_review ? "/review" : ""}</td>
                  <td className="pr-3 font-mono text-slate-300">{c.finding_type}</td>
                  <td className="pr-3 font-mono text-slate-300">{c.decision}{c.finding_id ? ` → ${c.finding_id}` : ""}</td>
                  <td className="break-words text-slate-500">{c.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section id="reports" title="Reports" hint="Markdown and JSON are generated from the same evaluated evidence">
        <div className="flex flex-wrap gap-3">
          <a className={buttonSecondary} href={links.report} target="_blank" rel="noreferrer">Markdown report</a>
          <a className={buttonSecondary} href={links.json} target="_blank" rel="noreferrer">JSON report</a>
          <button type="button" className={buttonSecondary} onClick={() => setShowJson(!showJson)} aria-expanded={showJson}>{showJson ? "Hide" : "View"} raw evaluation JSON</button>
        </div>
        {showJson && <pre className="mt-4 max-h-[32rem] overflow-auto rounded-lg border border-slate-800 bg-black/60 p-4 text-xs text-slate-300">{JSON.stringify(r, null, 2)}</pre>}
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

function taskSlug(text: string) {
  const value = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
  return value || "batch-task";
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
  const [taskEnabled, setTaskEnabled] = useState(false);
  const [taskId, setTaskId] = useState("");
  const [taskTitle, setTaskTitle] = useState("");
  const [taskCategory, setTaskCategory] = useState("");
  const [taskDescription, setTaskDescription] = useState("");
  const [taskRequirements, setTaskRequirements] = useState("");
  const [backendDown, setBackendDown] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollingGeneration = useRef(0);
  const selection = useMemo(() => repositorySelection(repositoryText), [repositoryText]);
  const running = submitting || ["running", "comparing", "stopping"].includes(batch?.state);
  const liveDisabled = DEMO_MODE || backendDown;
  const selectedProvider = providers.find(p => p.id === provider);
  const providerUnavailable = provider === "configured" ? ready?.ai_reasoning_available === false : !selectedProvider?.configured;
  const taskInvalid = taskEnabled && !taskDescription.trim();
  const batchProgress = batch?.total ? Math.min(100, Math.round((Number(batch.completed ?? 0) / Number(batch.total)) * 100)) : 0;

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
    if (taskEnabled && !taskDescription.trim()) { setError("Describe the task before enabling task profiling."); return; }
    const resolvedTaskId = taskId.trim() || `ui-${taskSlug(taskTitle || taskCategory || "batch-task")}`;
    const task = taskEnabled ? {
      id: resolvedTaskId,
      description: taskDescription.trim(),
      title: taskTitle.trim(),
      category: taskCategory.trim(),
      requirements: taskRequirements.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
      assignments: Object.fromEntries(selection.urls.map((url) => [url, resolvedTaskId])),
    } : undefined;
    setSubmitting(true); setError(""); setResult(null);
    try {
      const r = await fetch(`${API}/api/batches`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ urls: selection.urls, deterministic_only: deterministicOnly, provider, ...(task ? { task } : {}) }) });
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
    return (
      <li key={repo.url} className="group flex items-start justify-between gap-3 rounded-lg border border-slate-800 bg-slate-950/50 p-3 transition hover:border-sky-500/35 hover:bg-slate-900/55">
        <div className="min-w-0">
          <a href={repo.url} target="_blank" rel="noreferrer" className="break-all font-mono text-xs text-sky-200 transition hover:text-sky-100 hover:underline">{repo.repository}</a>
          <p className="mt-1 text-xs leading-relaxed text-slate-400">{repo.description || "No description provided."}</p>
          {(repo.language || repo.stars) && (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px] text-slate-500">
              {repo.language && <Badge className="border-slate-700 text-slate-400">{repo.language}</Badge>}
              {typeof repo.stars === "number" && <span>★ {repo.stars.toLocaleString("en-US")}</span>}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => addRepository(repo.url)}
          disabled={running || added}
          aria-label={`${added ? "Added" : "Add"} ${repo.repository}`}
          className={`${buttonSecondary} shrink-0 self-start px-3 py-1.5 text-xs`}
        >
          {added ? "Added" : "Add"}
        </button>
      </li>
    );
  });

  return (
    <main className="min-h-screen text-slate-200">
      <header className="sticky top-0 z-40 border-b border-slate-800/80 bg-slate-950/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8">
          <a href="#top" className="group flex items-center gap-3 rounded-lg focus-visible:ring-2 focus-visible:ring-sky-300/60">
            <span aria-hidden="true" className="grid h-9 w-9 place-items-center rounded-lg border border-sky-400/30 bg-sky-400/10 font-mono text-xs font-bold tracking-[0.12em] text-sky-300">AR</span>
            <span>
              <span className="block font-mono text-xl font-semibold tracking-[0.22em] text-slate-50 transition group-hover:text-sky-100">ARGUS</span>
              <span className="block text-[10px] uppercase tracking-[0.14em] text-slate-500">Repository forensics &amp; integrity</span>
            </span>
          </a>
          <div className="flex items-center gap-2">
            <span
              aria-live="polite"
              className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] ${DEMO_MODE ? "border-sky-500/30 bg-sky-500/10 text-sky-200" : health ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-amber-500/30 bg-amber-500/10 text-amber-200"}`}
            >
              <span aria-hidden="true" className={`status-dot h-1.5 w-1.5 rounded-full ${DEMO_MODE ? "bg-sky-300" : health ? "bg-emerald-300" : "bg-amber-300"}`} />
              {DEMO_MODE ? "Public demo · static" : health ? "Local backend connected" : "Connecting to backend…"}
            </span>
            {!DEMO_MODE && ready?.model && (
              <span className="hidden rounded-full border border-slate-800 bg-slate-900/70 px-3 py-1.5 text-[11px] text-slate-400 sm:inline-flex">
                {ready.model} · {ready.ai_reasoning_available ? "AI ready" : "AI unavailable"}
              </span>
            )}
          </div>
        </div>
        <nav aria-label="Page sections" className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pb-2 text-xs sm:px-6 lg:px-8">
          <a href="#evaluate" className="shrink-0 rounded-md px-2.5 py-1.5 text-slate-400 transition hover:bg-slate-800/70 hover:text-slate-100">Evaluate</a>
          {batch && <a href="#batch-results" className="shrink-0 rounded-md px-2.5 py-1.5 text-slate-400 transition hover:bg-slate-800/70 hover:text-slate-100">Batch results</a>}
          {result && <a href="#report" className="shrink-0 rounded-md px-2.5 py-1.5 text-slate-400 transition hover:bg-slate-800/70 hover:text-slate-100">Report</a>}
          {result && (result.task_evaluation || result.repository_profile) && <a href="#task-context" className="shrink-0 rounded-md px-2.5 py-1.5 text-slate-400 transition hover:bg-slate-800/70 hover:text-slate-100">Task fit</a>}
          <a href="#history" className="shrink-0 rounded-md px-2.5 py-1.5 text-slate-400 transition hover:bg-slate-800/70 hover:text-slate-100">History</a>
        </nav>
      </header>

      <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
        <section id="top" className="relative scroll-mt-24 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/45 p-5 shadow-[0_30px_100px_-70px_rgba(56,189,248,0.8)] sm:p-7">
          <div aria-hidden="true" className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-sky-500/10 blur-3xl" />
          <div className="relative grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.55fr)] lg:items-end">
            <div>
              <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-sky-300/80">Measure first, reason second</p>
              <SplitText
                as="h1"
                text="Evaluate repositories with evidence, not guesswork."
                className="mt-2 max-w-3xl text-3xl font-semibold tracking-tight text-slate-50 sm:text-4xl lg:text-[2.7rem] lg:leading-[1.08]"
              />
              <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-400">
                Build a repository cohort, inspect integrity evidence and task fit, and compare only the peers that implement the same work. The report keeps measured facts, model reasoning and deterministic policy decisions visibly separate.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-300">Deterministic evidence first</Badge>
                <Badge className="border-sky-500/30 bg-sky-500/10 text-sky-300">Task-aware peer context</Badge>
                <Badge className="border-slate-700 bg-slate-900/70 text-slate-300">Explainable scores</Badge>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-2">
              <Stat label="Mode" value={DEMO_MODE ? "DEMO" : "LOCAL"} hint={DEMO_MODE ? "Saved real evaluation" : "Local backend"} />
              <Stat label="Saved reports" value={fmt(saved.length)} hint="Available without rerunning" />
              <Stat label="Model" value={ready?.model ?? "—"} hint={DEMO_MODE ? "Bundled Qwen report" : ready?.ai_reasoning_available ? "AI reasoning ready" : "Deterministic only"} />
              <Stat label="Queue" value={running ? `${batch?.completed ?? 0}/${batch?.total ?? 0}` : "Ready"} tone={running ? "text-sky-300" : ""} hint={running ? "Batch in progress" : "Accepting work"} />
            </div>
          </div>
        </section>

        {DEMO_MODE && (
          <div role="status" className="rounded-xl border border-sky-500/30 bg-sky-500/10 p-4 text-sm leading-relaxed text-sky-100">
            <strong>Public demo.</strong> This page shows a saved, real Qwen3-8B evaluation. Live evaluation is not available here: start the local ARGUS backend to evaluate a batch.
          </div>
        )}
        {!DEMO_MODE && backendDown && (
          <div role="alert" className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm leading-relaxed text-amber-100">
            The local backend is not reachable. Start ARGUS and reload to evaluate repositories. Saved demo results remain readable.
          </div>
        )}

        <section id="evaluate" className="scroll-mt-24 rounded-2xl border border-slate-800 bg-slate-900/45 p-4 shadow-[0_24px_90px_-70px_rgba(56,189,248,0.6)] sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold tracking-tight text-slate-50">Start a batch evaluation</h2>
              <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-400">Paste public GitHub repositories or add curated samples. ARGUS evaluates them one at a time and keeps every report.</p>
            </div>
            <Badge className="border-slate-700 bg-slate-950/70 text-slate-300">Up to 50 repositories</Badge>
          </div>

          <div className="mt-5 grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
            <form onSubmit={evaluate} className="space-y-4">
              <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-4">
                <label htmlFor="repository-links" className="block">
                  <span className="flex flex-wrap items-baseline justify-between gap-2 text-sm font-medium text-slate-200">
                    Repository links
                    <span className="text-[10px] font-normal uppercase tracking-[0.14em] text-slate-500">required</span>
                  </span>
                  <textarea
                    id="repository-links"
                    value={repositoryText}
                    onChange={(event) => setRepositoryText(event.target.value)}
                    required
                    rows={8}
                    maxLength={20000}
                    disabled={running || liveDisabled}
                    aria-describedby="repository-links-help"
                    placeholder={"https://github.com/owner/first-repository\nhttps://github.com/owner/second-repository"}
                    className={`${inputClass} mt-2 min-h-44 resize-y font-mono text-xs leading-relaxed`}
                  />
                </label>
                <p id="repository-links-help" className="mt-2 text-xs leading-relaxed text-slate-500">One home-page URL per line. Commas, spaces and semicolons also work. Duplicate links are removed before scheduling.</p>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <label className={`${buttonSecondary} cursor-pointer px-3 py-1.5 text-xs`}>
                      Import .txt
                      <input
                        aria-label="Import repository links"
                        type="file"
                        accept=".txt,text/plain"
                        disabled={running || liveDisabled}
                        className="sr-only"
                        onChange={async (event) => {
                          const input = event.currentTarget;
                          const file = input.files?.[0];
                          if (!file) return;
                          if (file.size > 100000) {
                            setError("Use a text file smaller than 100 KB.");
                            input.value = "";
                            return;
                          }
                          try {
                            setRepositoryText(await file.text());
                            setError("");
                          } catch {
                            setError("Could not read that text file.");
                          }
                          input.value = "";
                        }}
                      />
                    </label>
                    <button type="button" onClick={() => { setRepositoryText(""); setError(""); }} disabled={running || liveDisabled} className={buttonGhost}>Clear links</button>
                  </div>
                  <span className="text-xs text-sky-200" aria-live="polite">
                    {selection.urls.length} {selection.urls.length === 1 ? "repository" : "repositories"} selected
                    {selection.duplicates > 0 ? ` · ${selection.duplicates} duplicate(s) ignored` : ""}
                  </span>
                </div>
                {selection.invalid.length > 0 && (
                  <p role="alert" className="mt-2 break-all text-xs text-red-300">
                    Fix these links: {selection.invalid.slice(0, 3).join(", ")}{selection.invalid.length > 3 ? "…" : ""}
                  </p>
                )}
                {selection.urls.length > 50 && <p role="alert" className="mt-2 text-xs text-red-300">Select at most 50 repositories.</p>}
              </div>

              {!DEMO_MODE && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-4">
                    <label className="block text-xs text-slate-300">
                      AI provider
                      <select aria-label="AI provider" value={provider} onChange={(event) => setProvider(event.target.value)} disabled={running || liveDisabled} className={`${inputClass} mt-1.5`}>
                        {providers.length ? providers.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.id === "configured" ? "Server default" : item.id === "openai" ? "OpenAI API" : "Claude API"} · {item.model}{item.configured ? "" : " · API key required"}
                          </option>
                        )) : <option value="configured">Server default</option>}
                      </select>
                    </label>
                    {selectedProvider && (
                      <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
                        {selectedProvider.provider} · {selectedProvider.model}
                        {provider !== "configured" ? " · Sends evaluation evidence to the selected API; usage is billed to your API account." : ""}
                      </p>
                    )}
                    <details className="mt-2 text-[11px] text-slate-500">
                      <summary className="cursor-pointer text-slate-400">Configure OpenAI or Claude</summary>
                      <p className="mt-1.5 leading-relaxed">Set OPENAI_API_KEY or ANTHROPIC_API_KEY in the backend environment and restart the backend. Optional model overrides: ARGUS_OPENAI_MODEL and ARGUS_ANTHROPIC_MODEL. Keys stay on the server.</p>
                    </details>
                  </div>
                  <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-800 bg-slate-950/35 p-4 transition hover:border-slate-700">
                    <input type="checkbox" checked={deterministicOnly} onChange={(event) => setDeterministicOnly(event.target.checked)} disabled={running || liveDisabled} className="mt-0.5 h-4 w-4 accent-sky-400" />
                    <span>
                      <span className="block text-sm font-medium text-slate-200">Deterministic evidence only</span>
                      <span className="mt-1 block text-xs leading-relaxed text-slate-500">Skip AI reasoning for a faster run. These reports are marked INCOMPLETE_EVALUATION because model checks do not run.</span>
                    </span>
                  </label>
                </div>
              )}

              {!DEMO_MODE && providerUnavailable && !deterministicOnly && (
                <p role="alert" className="rounded-lg border border-amber-500/25 bg-amber-500/10 p-3 text-xs leading-relaxed text-amber-200">
                  The selected provider is unavailable. Start its runtime or configure its API key, or select deterministic evidence only.
                </p>
              )}

              <details className="group rounded-xl border border-slate-800 bg-slate-950/35">
                <summary className="flex cursor-pointer items-start justify-between gap-3 p-4">
                  <span>
                    <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-200">Task context <Badge className="border-slate-700 text-slate-400">Optional</Badge></span>
                    <span className="mt-1 block text-xs leading-relaxed text-slate-500">Describe the work being evaluated. ARGUS profiles implementation evidence, checks requirements and compares only task-relevant peers.</span>
                  </span>
                  <span aria-hidden="true" className="mt-0.5 text-slate-500 transition group-open:rotate-180">⌄</span>
                </summary>
                <div className="border-t border-slate-800 p-4">
                  <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-slate-800 bg-slate-900/45 p-3 transition hover:border-slate-700">
                    <input type="checkbox" checked={taskEnabled} onChange={(event) => setTaskEnabled(event.target.checked)} disabled={running || liveDisabled} className="mt-0.5 h-4 w-4 accent-sky-400" />
                    <span>
                      <span className="block text-sm font-medium text-slate-200">Enable task profiling and peer comparison</span>
                      <span className="mt-1 block text-xs leading-relaxed text-slate-500">All selected repositories are explicitly assigned to this task. README mentions alone are never treated as implementation evidence.</span>
                    </span>
                  </label>
                  {taskEnabled && (
                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      <label className="block text-xs text-slate-300">
                        Task ID
                        <input value={taskId} onChange={(event) => setTaskId(event.target.value)} maxLength={120} disabled={running || liveDisabled} placeholder="ui-graph-coloring" className={`${inputClass} mt-1.5`} />
                        <span className="mt-1 block text-[11px] text-slate-500">Optional. A stable ID is generated when blank.</span>
                      </label>
                      <label className="block text-xs text-slate-300">
                        Title
                        <input value={taskTitle} onChange={(event) => setTaskTitle(event.target.value)} maxLength={300} disabled={running || liveDisabled} placeholder="Graph coloring heuristics" className={`${inputClass} mt-1.5`} />
                      </label>
                      <label className="block text-xs text-slate-300">
                        Category
                        <input value={taskCategory} onChange={(event) => setTaskCategory(event.target.value)} maxLength={120} disabled={running || liveDisabled} placeholder="Algorithms" className={`${inputClass} mt-1.5`} />
                      </label>
                      <label className="block text-xs text-slate-300">
                        Peer context weight
                        <input value="0.15 · server default" readOnly disabled aria-label="Peer context weight is configured on the server" className={`${inputClass} mt-1.5`} />
                        <span className="mt-1 block text-[11px] text-slate-500">Peer context is capped by the backend and stays below the absolute score.</span>
                      </label>
                      <label className="block text-xs text-slate-300 sm:col-span-2">
                        Task description <span className="text-red-300">required</span>
                        <textarea
                          value={taskDescription}
                          onChange={(event) => setTaskDescription(event.target.value)}
                          rows={3}
                          maxLength={12000}
                          disabled={running || liveDisabled}
                          required={taskEnabled}
                          aria-invalid={taskInvalid}
                          aria-describedby="task-description-help"
                          placeholder="Describe the required behaviour, algorithms and deliverables in enough detail to distinguish this task from adjacent work."
                          className={`${inputClass} mt-1.5 resize-y leading-relaxed ${taskInvalid ? "border-red-500/60" : ""}`}
                        />
                        <span id="task-description-help" className="mt-1 block text-[11px] leading-relaxed text-slate-500">This text drives task similarity and requirement matching. It is not used as evidence of implementation.</span>
                      </label>
                      <label className="block text-xs text-slate-300 sm:col-span-2">
                        Requirements
                        <textarea
                          value={taskRequirements}
                          onChange={(event) => setTaskRequirements(event.target.value)}
                          rows={4}
                          disabled={running || liveDisabled}
                          placeholder={"One requirement per line\nParse DIMACS graph instances\nImplement a coloring heuristic\nCompare solution quality across instances"}
                          className={`${inputClass} mt-1.5 resize-y font-mono text-xs leading-relaxed`}
                        />
                        <span className="mt-1 block text-[11px] leading-relaxed text-slate-500">Optional. Coverage is assessed from source and test evidence; each requirement is reported as covered, partial, missing or unverified.</span>
                      </label>
                    </div>
                  )}
                  {taskInvalid && <p role="alert" className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-200">Describe the task before enabling task profiling.</p>}
                </div>
              </details>

              <button
                type="submit"
                disabled={running || liveDisabled || !selection.urls.length || !!selection.invalid.length || selection.urls.length > 50 || (!deterministicOnly && providerUnavailable) || taskInvalid}
                className={`${buttonPrimary} w-full py-3`}
              >
                {running ? `Evaluating batch · ${batch?.completed ?? 0}/${batch?.total ?? selection.urls.length}` : `Evaluate ${selection.urls.length || "selected"} ${selection.urls.length === 1 ? "repository" : "repositories"}`}
              </button>
              <p className="text-xs text-slate-500">Repositories are queued one at a time. Closing this page does not cancel the batch.</p>
              {error && <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm leading-relaxed text-red-200">{error}</p>}
            </form>

            <aside className="space-y-4">
              <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-4">
                <h3 className="text-sm font-semibold text-slate-100">Find public repositories</h3>
                <p className="mt-1 text-xs leading-relaxed text-slate-500">Search GitHub and add candidates to the batch without leaving the page.</p>
                <div className="mt-2 flex gap-2">
                  <input
                    aria-label="Search public GitHub repositories"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void search(); } }}
                    maxLength={120}
                    placeholder="graph coloring, social golfer, timetabling…"
                    className={`${inputClass} min-w-0 flex-1`}
                  />
                  <button type="button" onClick={() => { void search(); }} disabled={searching || liveDisabled || query.trim().length < 2} className={`${buttonSecondary} shrink-0`}>
                    {searching ? "Searching…" : "Search"}
                  </button>
                </div>
                {searchError && <p role="alert" className="mt-2 rounded-lg border border-amber-500/25 bg-amber-500/10 p-2.5 text-xs leading-relaxed text-amber-200">{searchError}</p>}
                {searching && <div className="mt-3 space-y-2" role="status" aria-live="polite"><div className="loading-shimmer relative h-14 overflow-hidden rounded-lg border border-slate-800 bg-slate-900/50" /><span className="sr-only">Searching public repositories</span></div>}
                {searched && !searchResults.length && !searching && <div className="mt-3"><EmptyState title="No public repositories found" description="Try a broader query or paste repository URLs directly." /></div>}
                {!!searchResults.length && <ul className="mt-3 max-h-72 space-y-2 overflow-auto pr-0.5">{repositoryCards(searchResults)}</ul>}
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-100">Curated test repositories</h3>
                    <p className="mt-1 text-xs text-slate-500">Small public projects for trying cohort and task comparison.</p>
                  </div>
                  <button type="button" disabled={running || liveDisabled} onClick={() => PUBLIC_TEST_REPOS.forEach((repo) => addRepository(repo.url))} className={buttonGhost}>Add all 4</button>
                </div>
                <ul className="mt-3 space-y-2">{repositoryCards(PUBLIC_TEST_REPOS)}</ul>
              </div>
            </aside>
          </div>
        </section>

        {!DEMO_MODE && !!savedBatches.length && (
          <FadeContent>
            <Section id="saved-batches" title="Saved batch results" hint="Reopen a completed cohort without evaluating it again">
              <label className="block text-sm text-slate-300">
                Choose a completed batch
                <select
                  aria-label="View saved batch results"
                  value={batch?.batch_id ?? ""}
                  disabled={running || liveDisabled}
                  onChange={(event) => {
                    if (!event.target.value) return;
                    setError("");
                    setRepositoryText("");
                    trackBatch(event.target.value);
                    try { localStorage.setItem("argus.latestBatch", event.target.value); } catch {}
                  }}
                  className={`${inputClass} mt-2`}
                >
                  <option value="">Select a saved batch to display its graphs</option>
                  {batch && !savedBatches.some((item) => item.batch_id === batch.batch_id) && <option value={batch.batch_id}>Current batch · {batch.total} repositories</option>}
                  {savedBatches.map((item) => <option key={item.batch_id} value={item.batch_id}>{item.batch_id} · {item.total} repositories · {item.model} · {String(item.state).replaceAll("_", " ")}</option>)}
                </select>
              </label>
            </Section>
          </FadeContent>
        )}

        {batch && (
          <FadeContent>
            <Section title="Repository statistics" hint="Per-repository measurements · shared comparison scales">
              <RepositoryStatistics key={batch.batch_id} api={API} batchId={batch.batch_id} revision={`${batch.completed}:${batch.state}`} />
            </Section>
          </FadeContent>
        )}

        {batch && (
          <FadeContent>
            <Section
              id="batch-results"
              title="Batch evaluation"
              hint={`${batch.completed ?? 0}/${batch.total ?? 0} finished · ${String(batch.state).replaceAll("_", " ")} · ${batch.elapsed_s ?? 0}s`}
              action={running ? (
                <button
                  type="button"
                  onClick={stopEvaluation}
                  disabled={stopping || batch.state === "stopping"}
                  className="inline-flex items-center gap-2 rounded-lg border border-red-500/50 bg-red-500/10 px-3.5 py-2 text-xs font-semibold text-red-200 transition hover:bg-red-500/15 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {stopping || batch.state === "stopping" ? "Stopping…" : "Stop evaluation"}
                </button>
              ) : <Badge className={STATUS_STYLE[batch.state] ?? "border-slate-700 text-slate-300"}>{String(batch.state).replaceAll("_", " ")}</Badge>}
            >
              <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-3.5">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span className="text-slate-300"><span className="font-mono text-slate-100">{batch.completed ?? 0}</span> of <span className="font-mono text-slate-100">{batch.total ?? 0}</span> repositories finished</span>
                  <span className="text-slate-500">{batch.fixture ? "Controlled local fixture" : "Public GitHub cohort"} · model {batch.model}</span>
                </div>
                <div
                  className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800"
                  role="progressbar"
                  aria-label="Batch evaluation progress"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={batchProgress}
                  aria-valuetext={`${batchProgress}% complete`}
                >
                  <div className="h-full rounded-full bg-gradient-to-r from-sky-500 to-emerald-400 transition-[width] duration-500" style={{ width: `${batchProgress}%` }} />
                </div>
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
                  <span>{batch.state === "comparing" ? "Comparing code and README patterns…" : running ? "Evaluating repositories one at a time." : "Completed reports remain available below."}</span>
                  {batch.fixture && <span className="text-sky-300">Generated repositories, not public GitHub links.</span>}
                </div>
              </div>
              {batch.state === "cancelled" && <p role="status" className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/10 p-3 text-sm text-amber-200">Evaluation stopped. {batch.cancelled ?? 0} repositories cancelled. Completed reports remain available.</p>}
              {batch.state === "stopping" && <p role="status" className="mt-3 text-sm text-amber-200">Stopping the active worker and cancelling the remaining queue…</p>}
              <div className="mt-4"><BatchResults key={batch.batch_id} batch={batch} onOpen={open} /></div>
              {batch.state === "comparing" && <p className="mt-3 text-sm text-sky-200">Comparing repository code and README patterns…</p>}
              {(batch.task_cross_validation || batch.task_cross_validation_error) && (
                <div className="mt-5 border-t border-slate-800 pt-5">
                  <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Task-based peer comparison</h3>
                  <TaskComparisonPanel validation={batch.task_cross_validation} error={batch.task_cross_validation_error} />
                </div>
              )}
              {batch.cross_validation_error && <p role="alert" className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/10 p-3 text-sm text-amber-200">{batch.cross_validation_error}</p>}
              {batch.persistence_error && <p role="alert" className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/10 p-3 text-sm text-amber-200">{batch.persistence_error}</p>}
            </Section>
          </FadeContent>
        )}

        {job && (
          <FadeContent>
            <Section title="Current evaluation" hint={job.repository}>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <Badge className="border-sky-500/40 bg-sky-500/10 text-sky-300">Running</Badge>
                <span>{job.stages?.[job.stage_index] ?? "Working"}</span>
                {job.deterministic_only && <Badge className="border-slate-700 text-slate-400">DETERMINISTIC ONLY</Badge>}
              </div>
              <ol className="mt-3 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
                {(job.stages ?? []).map((stage: string, index: number) => {
                  const done = index < job.stage_index;
                  const current = index === job.stage_index;
                  return (
                    <li key={stage} className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-xs ${current ? "border-sky-500/40 bg-sky-500/10 text-sky-100" : done ? "border-emerald-500/25 text-emerald-300" : "border-slate-800 text-slate-500"}`}>
                      <span aria-hidden="true" className="font-mono">{done ? "✓" : current ? "•" : "○"}</span>
                      <span className="min-w-0 break-words">{stage}{job.deterministic_only && index === 2 ? " (skipped)" : ""}</span>
                    </li>
                  );
                })}
              </ol>
              <details className="mt-3 rounded-lg border border-slate-800 bg-black/20 p-3">
                <summary className="cursor-pointer text-xs text-slate-400">Execution log</summary>
                <pre className="mt-2 max-h-40 overflow-auto text-xs leading-relaxed text-slate-400">{job.log.join("\n")}</pre>
              </details>
            </Section>
          </FadeContent>
        )}

        {!!batch?.cross_validation?.length && (
          <FadeContent>
            <Section title="Cross-repository checks" hint={`${batch.cross_validation.length} repository pairs · README structure is advisory`}>
              <div className="overflow-x-auto rounded-xl border border-slate-800">
                <table className="min-w-[720px] w-full text-left text-xs">
                  <thead className="bg-slate-950/50 text-[10px] uppercase tracking-[0.14em] text-slate-500"><tr><th className="px-3 py-3 font-medium">Repository pair</th><th className="px-3 py-3 font-medium">Code A → B</th><th className="px-3 py-3 font-medium">Code B → A</th><th className="px-3 py-3 font-medium">README text</th><th className="px-3 py-3 font-medium">README headings</th></tr></thead>
                  <tbody className="divide-y divide-slate-800/80">{batch.cross_validation.map((pair: any) => <tr key={`${pair.a}:${pair.b}`} className="align-top transition hover:bg-slate-900/45"><td className="px-3 py-3 pr-3"><div className="break-all font-mono text-slate-300">A: {pair.a}</div><div className="break-all font-mono text-slate-300">B: {pair.b}</div>{pair.flagged && <div className="mt-2 text-rose-300">FLAGGED · code overlap ≥ {Math.round(pair.threshold * 100)}% · review required</div>}</td>{[pair.code_a_in_b, pair.code_b_in_a, pair.readme_text_similarity, pair.readme_heading_similarity].map((value: any, index: number) => <td key={index} className="px-3 py-3 font-mono text-slate-300">{typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "Unavailable"}</td>)}</tr>)}</tbody>
                </table>
              </div>
              <p className="mt-3 text-xs leading-relaxed text-slate-500">Code overlap uses token-shingle containment in both directions. Code overlap at or above the configured threshold flags both participants for review and excludes them from the primary statistics. Shared templates, libraries and attribution still require review; overlap alone does not establish copying direction or intent.</p>
            </Section>
          </FadeContent>
        )}

        {result && <FadeContent><Dashboard r={result} links={reportLinks(evaluationId, resultSource)} source={resultSource} /></FadeContent>}

        <Section id="history" title="Completed evaluations" hint={DEMO_MODE ? "Saved real ARGUS result bundled with this page" : "Saved reports are available without re-running evaluations"}>
          <SavedEvaluations rows={saved} onOpen={open} demoMode={DEMO_MODE} />
        </Section>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-800/80 px-1 py-4 text-[11px] text-slate-600">
          <span>ARGUS · Repository Forensics &amp; Engineering Integrity Agent</span>
          <span>{DEMO_MODE ? "Public demo · static saved evidence" : "Local full mode · evidence remains on this machine"}</span>
        </footer>
      </div>
    </main>
  );
}
