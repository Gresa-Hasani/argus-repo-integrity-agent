"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import {
  Badge,
  RELATION_STYLE,
  REQUIREMENT_ICON,
  REQUIREMENT_STYLE,
  ScoreBar,
  ScoreRing,
  Section,
  TASK_STATUS_LABEL,
  TASK_STATUS_STYLE,
  pct,
} from "./ui-kit";

const list = (value: any): any[] => (Array.isArray(value) ? value : []);

function ProfileChips({ profile }: { profile: any }) {
  const languages = list(profile?.languages).slice(0, 4);
  const technologies = list(profile?.technologies).slice(0, 6);
  const structure = profile?.structure ?? {};
  const testing = profile?.testing ?? {};
  const quality = profile?.quality ?? {};
  const documentation = profile?.documentation ?? {};
  const architecture = profile?.architecture ?? {};

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Static repository profile</div>
          <div className="mt-1 text-sm text-slate-200">{profile?.repository ?? "Repository profile"}</div>
        </div>
        <Badge className="border-slate-700 text-slate-300">Confidence {pct(profile?.confidence)}</Badge>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Structure</div>
          <p className="mt-1 text-xs leading-relaxed text-slate-300">
            {structure.tracked_files ?? 0} tracked · {structure.source_files ?? 0} source · {structure.test_files ?? 0} test
          </p>
          <p className="text-xs text-slate-500">{structure.config_files ?? 0} config · {structure.documentation_files ?? 0} docs · {structure.ci_files ?? 0} CI</p>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Testing & quality</div>
          <p className="mt-1 text-xs leading-relaxed text-slate-300">Test score {testing.score == null ? "not measurable" : pct(testing.score)}</p>
          <p className="text-xs text-slate-500">Quality score {quality.score == null ? "not measurable" : pct(quality.score)}</p>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Documentation</div>
          <p className="mt-1 text-xs leading-relaxed text-slate-300">README {documentation.readme_present ? "present" : "missing"}</p>
          <p className="text-xs text-slate-500">{list(documentation.documentation_files).length} documentation file(s) · licence {list(documentation.license_files).length > 0 ? "detected" : "not detected"}</p>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Architecture</div>
          <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-300">{list(architecture.patterns).join(", ") || "No pattern confidently inferred"}</p>
          <p className="text-xs text-slate-500">{list(architecture.entry_points).length} entry point(s)</p>
        </div>
      </div>
      {languages.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {languages.map((language: any) => (
            <Badge key={language.language} className="border-sky-500/25 bg-sky-500/5 text-sky-200">
              {language.language}{typeof language.share_of_code === "number" ? ` ${Math.round(language.share_of_code * 100)}%` : ""}
            </Badge>
          ))}
        </div>
      )}
      {technologies.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {technologies.map((technology: any) => (
            <Badge key={`${technology.category}:${technology.name}`} className="border-slate-700 text-slate-300" title={list(technology.evidence).join(", ")}>
              {technology.name}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function RequirementList({ profile }: { profile: any }) {
  const requirements = list(profile?.task_coverage);
  if (requirements.length === 0) {
    return <p className="text-sm text-slate-400">The task defines no explicit requirements; requirement fulfilment is not scored.</p>;
  }
  return (
    <div className="space-y-2">
      {requirements.map((requirement: any) => (
        <div key={requirement.requirement_id} className="rounded-lg border border-slate-800 bg-slate-950/35 p-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-xs">
                <span
                  aria-label={`Requirement status: ${requirement.status}`}
                  className={`grid h-5 w-5 shrink-0 place-items-center rounded border font-mono text-[11px] ${REQUIREMENT_STYLE[requirement.status] ?? "border-slate-700 text-slate-300"}`}
                >
                  {REQUIREMENT_ICON[requirement.status] ?? "?"}
                </span>
                <span className="font-mono text-slate-500">{requirement.requirement_id}</span>
                <Badge className={REQUIREMENT_STYLE[requirement.status] ?? "border-slate-700 text-slate-300"}>{requirement.status}</Badge>
              </div>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-200">{requirement.requirement}</p>
            </div>
            <div className="text-right text-xs">
              <div className="font-mono text-slate-200">{pct(requirement.score)}</div>
              <div className="text-slate-500">confidence {pct(requirement.confidence)}</div>
            </div>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-slate-400">{requirement.explanation}</p>
          {list(requirement.evidence).length > 0 && (
            <details className="mt-2 text-xs text-slate-400">
              <summary className="cursor-pointer text-slate-300">Evidence ({requirement.evidence.length})</summary>
              <ul className="mt-1.5 space-y-1 pl-4">
                {requirement.evidence.map((item: string, index: number) => <li key={index} className="break-all font-mono text-[11px] text-slate-400">{item}</li>)}
              </ul>
            </details>
          )}
          {list(requirement.limitations).length > 0 && (
            <p className="mt-1.5 text-[11px] text-amber-300/80">Limitation: {requirement.limitations.join("; ")}</p>
          )}
        </div>
      ))}
    </div>
  );
}

function CriterionList({ task }: { task: any }) {
  const criteria = list(task?.criteria);
  if (criteria.length === 0) return <p className="text-sm text-slate-400">No absolute criterion was measurable.</p>;
  return (
    <div className="space-y-3">
      {criteria.map((criterion: any) => (
        <div key={criterion.id} className="rounded-lg border border-slate-800 bg-slate-950/35 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-medium text-slate-200">{criterion.label}</span>
            <div className="flex items-center gap-2 text-[10px] text-slate-500">
              <span>weight {criterion.weight}</span>
              <span>confidence {pct(criterion.confidence)}</span>
            </div>
          </div>
          <div className="mt-2"><ScoreBar label="Score" value={criterion.score} /></div>
          {criterion.explanation && <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{criterion.explanation}</p>}
          {list(criterion.evidence).length > 0 && (
            <details className="mt-1.5 text-xs text-slate-400">
              <summary className="cursor-pointer text-slate-300">Evidence</summary>
              <ul className="mt-1 space-y-1 pl-4">
                {criterion.evidence.map((item: string, index: number) => <li key={index} className="break-all font-mono text-[11px]">{item}</li>)}
              </ul>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}

function PeerList({ task }: { task: any }) {
  const comparable = list(task?.comparable_repositories);
  const excluded = list(task?.excluded_repositories);
  const comparisons = list(task?.peer_comparisons);
  return (
    <div className="space-y-3">
      {comparable.length > 0 ? (
        <ul className="space-y-2">
          {comparable.map((peer: any) => (
            <li key={peer.repository} className="rounded-lg border border-slate-800 bg-slate-950/35 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="break-all font-mono text-xs text-slate-200">{peer.repository}</span>
                <div className="flex flex-wrap gap-1">
                  <Badge className={RELATION_STYLE[peer.relation] ?? "border-slate-700 text-slate-300"}>{peer.relation}</Badge>
                  <Badge className="border-slate-700 text-slate-400">relevance {pct(peer.relevance)}</Badge>
                  <Badge className="border-slate-700 text-slate-400">confidence {pct(peer.confidence)}</Badge>
                  {peer.duplicate && <Badge className="border-amber-500/40 bg-amber-500/10 text-amber-300">duplicate</Badge>}
                </div>
              </div>
              {peer.reason && <p className="mt-1.5 text-xs leading-relaxed text-slate-500">{peer.reason}</p>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-400">No comparable task-relevant peers were available. The final score remains absolute.</p>
      )}
      {comparisons.length > 0 && (
        <details className="rounded-lg border border-slate-800 bg-slate-950/35 p-3">
          <summary className="cursor-pointer text-xs text-slate-300">Peer criterion differences ({comparisons.length})</summary>
          <ul className="mt-2 space-y-2">
            {comparisons.map((comparison: any) => (
              <li key={comparison.peer} className="text-xs leading-relaxed text-slate-400">
                <span className="font-mono text-slate-300">{comparison.peer}</span>
                {Object.keys(comparison.criterion_deltas ?? {}).length > 0 && (
                  <span> · {Object.entries(comparison.criterion_deltas).map(([key, value]: [string, any]) => `${key}=${Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(1)}`).join(", ")}</span>
                )}
                {comparison.explanation && <p className="mt-1">{comparison.explanation}</p>}
              </li>
            ))}
          </ul>
        </details>
      )}
      {excluded.length > 0 && (
        <details className="rounded-lg border border-slate-800 bg-slate-950/35 p-3">
          <summary className="cursor-pointer text-xs text-slate-300">Excluded from peer statistics ({excluded.length})</summary>
          <ul className="mt-2 space-y-1.5">
            {excluded.map((peer: any) => (
              <li key={peer.repository} className="text-xs leading-relaxed text-slate-400">
                <span className="font-mono text-slate-300">{peer.repository}</span> · {peer.relation}
                {peer.reason && <span> — {peer.reason}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function TaskResultPanel({ evaluation }: { evaluation: any }) {
  const task = evaluation?.task_evaluation;
  const profile = task?.profile ?? evaluation?.repository_profile;
  const error = evaluation?.profiling_error;
  if (!task && !profile && !error) return null;

  const assignment = task?.task;
  const score = task?.final_score;
  const status = task?.status ?? (profile ? "PROFILE_ONLY" : "NOT_AVAILABLE");

  return (
    <Section
      id="task-context"
      title="Task fit and peer context"
      hint="Static, source-based assessment · separate from integrity findings and completion status"
    >
      {error && <p role="alert" className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">{error}</p>}
      {task ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,0.75fr)]">
          <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className={TASK_STATUS_STYLE[status] ?? "border-slate-700 text-slate-300"}>{TASK_STATUS_LABEL[status] ?? status}</Badge>
              {assignment?.relation && <Badge className={RELATION_STYLE[assignment.relation] ?? "border-slate-700 text-slate-300"}>{assignment.relation}</Badge>}
              {assignment?.category && <Badge className="border-slate-700 text-slate-300">{assignment.category}</Badge>}
              <span className="font-mono text-[11px] text-slate-500">{assignment?.task_id}</span>
            </div>
            <h3 className="mt-3 text-base font-semibold text-slate-100">{assignment?.title || assignment?.task_id || "Task assignment"}</h3>
            {assignment?.description && <p className="mt-2 text-sm leading-relaxed text-slate-300">{assignment.description}</p>}
            <div className="mt-3 grid gap-x-5 gap-y-1 text-xs sm:grid-cols-2">
              <div className="flex justify-between gap-3 border-b border-slate-800/70 py-1"><span className="text-slate-500">Assignment method</span><span className="text-right font-mono text-slate-300">{assignment?.method ?? "n/a"}</span></div>
              <div className="flex justify-between gap-3 border-b border-slate-800/70 py-1"><span className="text-slate-500">Relevance</span><span className="text-right font-mono text-slate-300">{pct(assignment?.relevance)}</span></div>
              <div className="flex justify-between gap-3 border-b border-slate-800/70 py-1"><span className="text-slate-500">Assignment confidence</span><span className="text-right font-mono text-slate-300">{pct(assignment?.confidence)}</span></div>
              <div className="flex justify-between gap-3 border-b border-slate-800/70 py-1"><span className="text-slate-500">Corroboration</span><span className="text-right font-mono text-slate-300">{assignment?.corroboration == null ? "n/a" : pct(assignment.corroboration)}</span></div>
            </div>
            {assignment?.explanation && <p className="mt-3 text-xs leading-relaxed text-slate-400">{assignment.explanation}</p>}
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-4">
            <ScoreRing value={score} />
            <div className="mt-4 space-y-3">
              <ScoreBar label="Absolute task score" value={task.absolute_score} detail="Configured criteria measured only from this repository." />
              <ScoreBar label="Relative peer context" value={task.relative_score} detail={task.relative_score == null ? "Not computed; the final score remains absolute." : "Small, separately weighted peer contribution."} />
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <Badge className="border-slate-700 text-slate-300">Confidence {pct(task.confidence)} · {task.confidence_level}</Badge>
              {typeof task.comparable_repositories?.length === "number" && <Badge className="border-slate-700 text-slate-300">{task.comparable_repositories.length} peer(s)</Badge>}
            </div>
          </div>
        </div>
      ) : (
        <p className="rounded-lg border border-slate-800 bg-slate-950/35 p-4 text-sm text-slate-400">
          No comparative task evaluation was produced. The repository profile below is descriptive only.
        </p>
      )}

      {profile && <div className="mt-4"><ProfileChips profile={profile} /></div>}

      {task && (
        <>
          {task.score_explanation && (
            <p className="mt-4 rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 text-xs leading-relaxed text-slate-300">{task.score_explanation}</p>
          )}

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Requirement coverage</h3>
              <RequirementList profile={profile} />
            </div>
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Absolute scoring criteria</h3>
              <CriterionList task={task} />
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Comparable peers</h3>
              <PeerList task={task} />
            </div>
            <div className="space-y-3">
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
                <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-emerald-300">Strengths</h3>
                {list(task.strengths).length > 0 ? (
                  <ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-relaxed text-slate-300">
                    {task.strengths.map((item: string, index: number) => <li key={index}>{item}</li>)}
                  </ul>
                ) : <p className="mt-2 text-xs text-slate-500">None recorded.</p>}
              </div>
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
                <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-amber-300">Weaknesses</h3>
                {list(task.weaknesses).length > 0 ? (
                  <ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-relaxed text-slate-300">
                    {task.weaknesses.map((item: string, index: number) => <li key={index}>{item}</li>)}
                  </ul>
                ) : <p className="mt-2 text-xs text-slate-500">None recorded.</p>}
              </div>
            </div>
          </div>

          {list(task.limitations).length > 0 && (
            <details className="mt-4 rounded-lg border border-slate-800 bg-slate-950/35 p-3">
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Limitations ({task.limitations.length})</summary>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-relaxed text-slate-400">
                {task.limitations.map((item: string, index: number) => <li key={index}>{item}</li>)}
              </ul>
            </details>
          )}
        </>
      )}

      {!task && profile && (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Requirement coverage</h3>
            <RequirementList profile={profile} />
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Profile limitations</h3>
            <ul className="list-disc space-y-1 pl-5 text-xs leading-relaxed text-slate-400">
              {(profile.limitations ?? []).map((item: string, index: number) => <li key={index}>{item}</li>)}
            </ul>
          </div>
        </div>
      )}
    </Section>
  );
}
