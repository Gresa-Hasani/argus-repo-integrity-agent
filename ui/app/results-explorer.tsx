"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { useMemo, useState } from "react";
import {
  Badge,
  EmptyState,
  FilterChip,
  RELATION_STYLE,
  STATUS_STYLE,
  ScoreBar,
  TASK_STATUS_LABEL,
  TASK_STATUS_STYLE,
  buttonGhost,
  buttonSecondary,
  formatTimestamp,
  inputClass,
  scoreText,
  statusLabel,
  taskStatusLabel,
} from "./ui-kit";

type Source = "demo" | "api";

const sourceLabel = (source: Source) => (source === "demo" ? "Bundled demo" : "Local report");

function activeFilterButton(label: string, onRemove: () => void) {
  return (
    <FilterChip key={label} label={label} onRemove={onRemove}>
      {label}
    </FilterChip>
  );
}

export function SavedEvaluations({
  rows,
  onOpen,
  demoMode,
}: {
  rows: any[];
  onOpen: (id: string, source: Source) => void;
  demoMode: boolean;
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [source, setSource] = useState("all");
  const [minFindings, setMinFindings] = useState("");
  const [maxFindings, setMaxFindings] = useState("");
  const [sort, setSort] = useState("newest");

  const statuses = useMemo(
    () => Array.from(new Set(rows.map((row) => String(row.status ?? "")).filter(Boolean))).sort(),
    [rows],
  );

  const low = minFindings.trim() === "" ? null : Number(minFindings);
  const high = maxFindings.trim() === "" ? null : Number(maxFindings);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    const rowsFiltered = rows.filter((row) => {
      const haystack = [row.repository, row.status, row.model, row.timestamp, row.source]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (query && !haystack.includes(query)) return false;
      if (status !== "all" && row.status !== status) return false;
      if (source !== "all" && row.source !== source) return false;
      if (low !== null && Number.isFinite(low) && Number(row.findings ?? 0) < low) return false;
      if (high !== null && Number.isFinite(high) && Number(row.findings ?? 0) > high) return false;
      return true;
    });

    const timestamp = (value: unknown) => {
      const parsed = Date.parse(String(value ?? ""));
      return Number.isFinite(parsed) ? parsed : 0;
    };
    return rowsFiltered.sort((a, b) => {
      if (sort === "oldest") return timestamp(a.timestamp) - timestamp(b.timestamp);
      if (sort === "name") return String(a.repository).localeCompare(String(b.repository));
      if (sort === "name-desc") return String(b.repository).localeCompare(String(a.repository));
      if (sort === "status") return String(a.status).localeCompare(String(b.status));
      if (sort === "findings-desc") return Number(b.findings ?? 0) - Number(a.findings ?? 0);
      if (sort === "findings-asc") return Number(a.findings ?? 0) - Number(b.findings ?? 0);
      return timestamp(b.timestamp) - timestamp(a.timestamp);
    });
  }, [high, low, rows, search, sort, source, status]);

  const hasFilters =
    search.trim() !== "" || status !== "all" || source !== "all" || minFindings !== "" || maxFindings !== "";

  const clearAll = () => {
    setSearch("");
    setStatus("all");
    setSource("all");
    setMinFindings("");
    setMaxFindings("");
    setSort("newest");
  };

  return (
    <div>
      <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-3.5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-12">
          <label className="block lg:col-span-4">
            <span className="mb-1.5 block text-[10px] uppercase tracking-[0.14em] text-slate-500">Search</span>
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Repository, model, status…"
              className={inputClass}
              aria-label="Search completed evaluations"
            />
          </label>
          <label className="block lg:col-span-2">
            <span className="mb-1.5 block text-[10px] uppercase tracking-[0.14em] text-slate-500">Status</span>
            <select value={status} onChange={(event) => setStatus(event.target.value)} className={inputClass} aria-label="Filter completed evaluations by status">
              <option value="all">All statuses</option>
              {statuses.map((value) => <option key={value} value={value}>{statusLabel(value)}</option>)}
            </select>
          </label>
          <label className="block lg:col-span-2">
            <span className="mb-1.5 block text-[10px] uppercase tracking-[0.14em] text-slate-500">Source</span>
            <select value={source} onChange={(event) => setSource(event.target.value)} className={inputClass} aria-label="Filter completed evaluations by source">
              <option value="all">All sources</option>
              <option value="api">Local reports</option>
              <option value="demo">Bundled demo</option>
            </select>
          </label>
          <label className="block lg:col-span-2">
            <span className="mb-1.5 block text-[10px] uppercase tracking-[0.14em] text-slate-500">Findings range</span>
            <div className="flex items-center gap-1.5">
              <input
                type="number"
                min={0}
                inputMode="numeric"
                value={minFindings}
                onChange={(event) => setMinFindings(event.target.value)}
                placeholder="Min"
                className={inputClass}
                aria-label="Minimum findings"
              />
              <span className="text-slate-600">–</span>
              <input
                type="number"
                min={0}
                inputMode="numeric"
                value={maxFindings}
                onChange={(event) => setMaxFindings(event.target.value)}
                placeholder="Max"
                className={inputClass}
                aria-label="Maximum findings"
              />
            </div>
          </label>
          <label className="block lg:col-span-2">
            <span className="mb-1.5 block text-[10px] uppercase tracking-[0.14em] text-slate-500">Sort</span>
            <select value={sort} onChange={(event) => setSort(event.target.value)} className={inputClass} aria-label="Sort completed evaluations">
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
              <option value="name">Name A–Z</option>
              <option value="name-desc">Name Z–A</option>
              <option value="status">Status</option>
              <option value="findings-desc">Most findings</option>
              <option value="findings-asc">Fewest findings</option>
            </select>
          </label>
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-slate-500" aria-live="polite">
            Showing <span className="font-mono text-slate-300">{filtered.length}</span> of{" "}
            <span className="font-mono text-slate-300">{rows.length}</span> saved evaluation{rows.length === 1 ? "" : "s"}
          </p>
          <button type="button" onClick={clearAll} disabled={!hasFilters} className={buttonGhost}>
            Clear all filters
          </button>
        </div>
        {hasFilters && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {search.trim() && activeFilterButton(`Search: ${search.trim()}`, () => setSearch(""))}
            {status !== "all" && activeFilterButton(`Status: ${statusLabel(status)}`, () => setStatus("all"))}
            {source !== "all" && activeFilterButton(`Source: ${sourceLabel(source as Source)}`, () => setSource("all"))}
            {minFindings !== "" && activeFilterButton(`Findings ≥ ${minFindings}`, () => setMinFindings(""))}
            {maxFindings !== "" && activeFilterButton(`Findings ≤ ${maxFindings}`, () => setMaxFindings(""))}
          </div>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="mt-3">
          <EmptyState title="No saved evaluations yet" description="Completed evaluations will appear here with their status, model and report link." />
        </div>
      ) : filtered.length === 0 ? (
        <div className="mt-3">
          <EmptyState
            title="No evaluations match these filters"
            description="Try a different repository name, status, source or findings range."
            action={<button type="button" onClick={clearAll} className={buttonSecondary}>Clear all filters</button>}
          />
        </div>
      ) : (
        <ul className="mt-3 divide-y divide-slate-800/80 overflow-hidden rounded-xl border border-slate-800/80 bg-slate-950/25">
          {filtered.map((row) => (
            <li key={`${row.source}:${row.evaluation_id}`} className="group flex flex-col gap-3 px-4 py-4 transition hover:bg-slate-900/55 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="break-all font-mono text-sm text-slate-100 transition group-hover:text-sky-100">{row.repository}</span>
                  <Badge className={STATUS_STYLE[row.status] ?? "border-slate-700 text-slate-300"} title={row.status}>
                    {statusLabel(row.status)}
                  </Badge>
                  {row.source === "demo" && <Badge className="border-sky-500/30 text-sky-300">DEMO</Badge>}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                  <span title={row.timestamp}>{formatTimestamp(row.timestamp)}</span>
                  <span>{row.model ?? "no model"}</span>
                  <span>{row.findings ?? 0} finding{Number(row.findings) === 1 ? "" : "s"}</span>
                  <span>{sourceLabel(row.source)}</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => onOpen(row.evaluation_id, row.source)}
                className={`${buttonSecondary} shrink-0 self-start sm:self-auto`}
                aria-label={`Open report for ${row.repository}`}
              >
                Open report <span aria-hidden="true">→</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {demoMode && rows.length > 0 && (
        <p className="mt-3 text-xs text-slate-500">The demo index is static. Start the local backend to evaluate repositories and save new reports.</p>
      )}
    </div>
  );
}

function batchTaskMap(batch: any): Map<string, any> {
  const evaluations: any[] = batch?.task_cross_validation?.evaluations ?? [];
  return new Map<string, any>(evaluations.map((evaluation: any) => [String(evaluation.repository).toLowerCase(), evaluation]));
}

function statusForRow(row: any) {
  if (row.completion_status) return row.completion_status;
  if (row.state === "running") return "RUNNING";
  if (row.state === "queued") return "QUEUED";
  if (row.state === "failed") return "FAILED";
  if (row.state === "cancelled") return "CANCELLED";
  return row.state ? String(row.state).toUpperCase() : "UNKNOWN";
}

function statusTextForRow(row: any) {
  if (row.completion_status) return statusLabel(row.completion_status);
  if (row.state === "running") return `Running${row.stages?.[row.stage_index] ? ` · ${row.stages[row.stage_index]}` : ""}`;
  if (row.state === "queued") return "Queued";
  if (row.state === "failed") return "Failed";
  if (row.state === "cancelled") return "Stopped";
  return row.state ? statusLabel(String(row.state).toUpperCase()) : "Unknown";
}

export function BatchResults({
  batch,
  onOpen,
}: {
  batch: any;
  onOpen: (id: string, source: Source) => void;
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [category, setCategory] = useState("all");
  const [minScore, setMinScore] = useState("");
  const [maxScore, setMaxScore] = useState("");
  const [sort, setSort] = useState("queue");

  const rows: any[] = useMemo(() => {
    const taskByRepo = batchTaskMap(batch);
    return (batch.items ?? []).map((item: any) => {
      const task = taskByRepo.get(String(item.repository).toLowerCase());
      return {
        ...item,
        task,
        category: task?.task?.category ?? "",
        taskTitle: task?.task?.title || task?.task?.task_id || "",
        score: typeof task?.final_score === "number" ? task.final_score : null,
        taskStatus: task?.status ?? null,
        relation: task?.task?.relation ?? null,
      };
    });
  }, [batch]);

  const statuses: string[] = useMemo(
    () => Array.from(new Set(rows.map((row: any) => statusForRow(row)))).sort(),
    [rows],
  );
  const categories: string[] = useMemo(
    () => Array.from(new Set(rows.map((row: any) => String(row.category ?? "")).filter(Boolean))).sort(),
    [rows],
  );
  const hasScores = rows.some((row: any) => typeof row.score === "number");
  const low = minScore.trim() === "" ? null : Number(minScore);
  const high = maxScore.trim() === "" ? null : Number(maxScore);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    const result = rows.filter((row: any) => {
      const haystack = [row.repository, row.category, row.taskTitle, row.completion_status, row.state, row.error]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (query && !haystack.includes(query)) return false;
      if (status !== "all" && statusForRow(row) !== status) return false;
      if (category !== "all" && row.category !== category) return false;
      if (low !== null && Number.isFinite(low) && (row.score === null || row.score < low)) return false;
      if (high !== null && Number.isFinite(high) && (row.score === null || row.score > high)) return false;
      return true;
    });
    if (sort === "score-desc") return result.sort((a: any, b: any) => (b.score ?? -1) - (a.score ?? -1));
    if (sort === "score-asc") return result.sort((a: any, b: any) => (a.score ?? 999) - (b.score ?? 999));
    if (sort === "name") return result.sort((a: any, b: any) => String(a.repository).localeCompare(String(b.repository)));
    if (sort === "name-desc") return result.sort((a: any, b: any) => String(b.repository).localeCompare(String(a.repository)));
    if (sort === "status") return result.sort((a: any, b: any) => statusForRow(a).localeCompare(statusForRow(b)));
    return result;
  }, [category, high, low, rows, search, sort, status]);

  const hasFilters =
    search.trim() !== "" || status !== "all" || category !== "all" || minScore !== "" || maxScore !== "";

  const clearAll = () => {
    setSearch("");
    setStatus("all");
    setCategory("all");
    setMinScore("");
    setMaxScore("");
    setSort("queue");
  };

  const hasTask = Boolean(batch.task_cross_validation);

  return (
    <div>
      <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-3.5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-12">
          <label className="block sm:col-span-2 lg:col-span-4">
            <span className="mb-1.5 block text-[10px] uppercase tracking-[0.14em] text-slate-500">Search</span>
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Repository, task, status…"
              className={inputClass}
              aria-label="Search batch results"
            />
          </label>
          <label className="block lg:col-span-2">
            <span className="mb-1.5 block text-[10px] uppercase tracking-[0.14em] text-slate-500">Status</span>
            <select value={status} onChange={(event) => setStatus(event.target.value)} className={inputClass} aria-label="Filter batch results by status">
              <option value="all">All statuses</option>
              {statuses.map((value) => <option key={value} value={value}>{value === "RUNNING" ? "Running" : statusLabel(value)}</option>)}
            </select>
          </label>
          {categories.length > 0 && (
            <label className="block lg:col-span-2">
              <span className="mb-1.5 block text-[10px] uppercase tracking-[0.14em] text-slate-500">Task category</span>
              <select value={category} onChange={(event) => setCategory(event.target.value)} className={inputClass} aria-label="Filter batch results by task category">
                <option value="all">All categories</option>
                {categories.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          )}
          {hasScores && (
            <label className={`block ${categories.length > 0 ? "lg:col-span-2" : "lg:col-span-3"}`}>
              <span className="mb-1.5 block text-[10px] uppercase tracking-[0.14em] text-slate-500">Score range</span>
              <div className="flex items-center gap-1.5">
                <input
                  type="number"
                  min={0}
                  max={100}
                  inputMode="decimal"
                  value={minScore}
                  onChange={(event) => setMinScore(event.target.value)}
                  placeholder="Min"
                  className={inputClass}
                  aria-label="Minimum final task score"
                />
                <span className="text-slate-600">–</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  inputMode="decimal"
                  value={maxScore}
                  onChange={(event) => setMaxScore(event.target.value)}
                  placeholder="Max"
                  className={inputClass}
                  aria-label="Maximum final task score"
                />
              </div>
            </label>
          )}
          <label className={`block ${hasScores ? "lg:col-span-2" : "lg:col-span-4"}`}>
            <span className="mb-1.5 block text-[10px] uppercase tracking-[0.14em] text-slate-500">Sort</span>
            <select value={sort} onChange={(event) => setSort(event.target.value)} className={inputClass} aria-label="Sort batch results">
              <option value="queue">Queue order</option>
              {hasScores && <option value="score-desc">Score high–low</option>}
              {hasScores && <option value="score-asc">Score low–high</option>}
              <option value="name">Name A–Z</option>
              <option value="name-desc">Name Z–A</option>
              <option value="status">Status</option>
            </select>
          </label>
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-slate-500" aria-live="polite">
            Showing <span className="font-mono text-slate-300">{filtered.length}</span> of{" "}
            <span className="font-mono text-slate-300">{rows.length}</span> repositor{rows.length === 1 ? "y" : "ies"}
            {hasTask ? " · scores from task cross-validation" : ""}
          </p>
          <button type="button" onClick={clearAll} disabled={!hasFilters} className={buttonGhost}>
            Clear all filters
          </button>
        </div>
        {hasFilters && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {search.trim() && activeFilterButton(`Search: ${search.trim()}`, () => setSearch(""))}
            {status !== "all" && activeFilterButton(`Status: ${status === "RUNNING" ? "Running" : statusLabel(status)}`, () => setStatus("all"))}
            {category !== "all" && activeFilterButton(`Category: ${category}`, () => setCategory("all"))}
            {minScore !== "" && activeFilterButton(`Score ≥ ${minScore}`, () => setMinScore(""))}
            {maxScore !== "" && activeFilterButton(`Score ≤ ${maxScore}`, () => setMaxScore(""))}
          </div>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="mt-3"><EmptyState title="No repositories in this batch" description="The batch has not produced any repository entries yet." /></div>
      ) : filtered.length === 0 ? (
        <div className="mt-3">
          <EmptyState
            title="No repositories match these filters"
            description="Clear one or more filters to return to the full batch."
            action={<button type="button" onClick={clearAll} className={buttonSecondary}>Clear all filters</button>}
          />
        </div>
      ) : (
        <>
          <div className="mt-3 hidden overflow-x-auto rounded-xl border border-slate-800/80 md:block">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-950/50 text-[10px] uppercase tracking-[0.14em] text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-medium">Repository</th>
                  <th className="px-3 py-3 font-medium">Task</th>
                  <th className="px-3 py-3 font-medium">Status</th>
                  <th className="px-3 py-3 font-medium">Final score</th>
                  <th className="px-4 py-3 text-right font-medium">Report</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {filtered.map((row: any) => (
                  <tr key={row.job_id ?? row.repository} className="align-top transition hover:bg-slate-900/45">
                    <td className="max-w-[22rem] px-4 py-3">
                      {batch.fixture ? (
                        <span className="break-all font-mono text-xs text-sky-200">{row.repository}</span>
                      ) : (
                        <a href={`https://github.com/${row.repository}`} target="_blank" rel="noreferrer" className="break-all font-mono text-xs text-sky-200 hover:underline">{row.repository}</a>
                      )}
                      {row.error && <p className="mt-1 text-xs text-red-300">{row.error}</p>}
                      {row.similarity_flagged && <div className="mt-1.5"><Badge className={STATUS_STYLE.FLAGGED}>CODE OVERLAP · REVIEW</Badge></div>}
                    </td>
                    <td className="max-w-[15rem] px-3 py-3">
                      {row.task ? (
                        <div className="space-y-1">
                          <div className="text-xs text-slate-200">{row.taskTitle || "Task assigned"}</div>
                          <div className="flex flex-wrap gap-1">
                            {row.category && <Badge className="border-slate-700 text-slate-400">{row.category}</Badge>}
                            {row.relation && <Badge className={RELATION_STYLE[row.relation] ?? "border-slate-700 text-slate-300"}>{row.relation}</Badge>}
                          </div>
                        </div>
                      ) : (
                        <span className="text-xs text-slate-600">No task</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <div className="space-y-1.5">
                        {row.completion_status ? (
                          <Badge className={STATUS_STYLE[row.completion_status] ?? "border-slate-700 text-slate-300"}>{statusLabel(row.completion_status)}</Badge>
                        ) : (
                          <span className={row.state === "failed" ? "text-xs text-red-300" : "text-xs text-slate-300"}>{statusTextForRow(row)}</span>
                        )}
                        {row.taskStatus && <Badge className={TASK_STATUS_STYLE[row.taskStatus] ?? "border-slate-700 text-slate-300"}>{taskStatusLabel(row.taskStatus)}</Badge>}
                      </div>
                    </td>
                    <td className="min-w-32 px-3 py-3">
                      {row.task ? <ScoreBar label="Final" value={row.score} /> : <span className="text-xs text-slate-600">Not scored</span>}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {row.evaluation_id ? (
                        <button type="button" onClick={() => onOpen(row.evaluation_id, "api")} className={buttonSecondary}>Open</button>
                      ) : (
                        <span className="text-xs text-slate-600">Pending</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ul className="mt-3 space-y-2 md:hidden">
            {filtered.map((row: any) => (
              <li key={row.job_id ?? row.repository} className="rounded-xl border border-slate-800 bg-slate-950/40 p-3.5">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <span className="break-all font-mono text-xs text-sky-200">{row.repository}</span>
                  {row.completion_status ? <Badge className={STATUS_STYLE[row.completion_status] ?? "border-slate-700 text-slate-300"}>{statusLabel(row.completion_status)}</Badge> : <span className="text-xs text-slate-300">{statusTextForRow(row)}</span>}
                </div>
                {row.task && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <Badge className="border-slate-700 text-slate-300">{row.taskTitle || "Task"}</Badge>
                    {row.category && <Badge className="border-slate-700 text-slate-400">{row.category}</Badge>}
                    {row.relation && <Badge className={RELATION_STYLE[row.relation] ?? "border-slate-700 text-slate-300"}>{row.relation}</Badge>}
                  </div>
                )}
                {row.task && <div className="mt-3"><ScoreBar label="Final task score" value={row.score} /></div>}
                {row.error && <p className="mt-2 text-xs text-red-300">{row.error}</p>}
                {row.evaluation_id && <button type="button" onClick={() => onOpen(row.evaluation_id, "api")} className={`${buttonSecondary} mt-3 w-full`}>Open report</button>}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export function TaskComparisonPanel({ validation, error }: { validation: any; error?: string }) {
  if (!validation && !error) return null;
  const evaluations = validation?.evaluations ?? [];
  const groups = validation?.groups ?? [];
  return (
    <div className="space-y-4">
      {error && <p role="alert" className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">{error}</p>}
      {validation && (
        <>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
              <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Peer weight</div>
              <div className="mt-1 font-mono text-lg text-slate-100">{Math.round(Number(validation.peer_context_weight ?? 0) * 100)}%</div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
              <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Minimum peers</div>
              <div className="mt-1 font-mono text-lg text-slate-100">{validation.minimum_peers ?? "—"}</div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
              <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Task groups</div>
              <div className="mt-1 font-mono text-lg text-slate-100">{groups.length}</div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
              <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Task evaluations</div>
              <div className="mt-1 font-mono text-lg text-slate-100">{evaluations.length}</div>
            </div>
          </div>

          {groups.length > 0 && (
            <div className="space-y-2">
              {groups.map((group: any) => (
                <div key={group.task_id} className="rounded-lg border border-slate-800 bg-slate-950/35 p-3.5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-sm text-slate-100">{group.title || group.task_id}</div>
                      <div className="mt-1 text-xs text-slate-500">{group.category || "uncategorised"} · {group.task_ids?.length ?? 1} task definition{(group.task_ids?.length ?? 1) === 1 ? "" : "s"}</div>
                    </div>
                    <Badge className="border-sky-500/30 bg-sky-500/10 text-sky-300">{group.repositories?.length ?? 0} repositor{(group.repositories?.length ?? 0) === 1 ? "y" : "ies"}</Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(group.repositories ?? []).map((repository: string) => <Badge key={repository} className="border-slate-700 text-slate-300">{repository}</Badge>)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {evaluations.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-slate-800/80">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-slate-950/50 text-[10px] uppercase tracking-[0.14em] text-slate-500">
                  <tr>
                    <th className="px-3 py-3 font-medium">Repository</th>
                    <th className="px-3 py-3 font-medium">Task</th>
                    <th className="px-3 py-3 font-medium">Absolute</th>
                    <th className="px-3 py-3 font-medium">Peer context</th>
                    <th className="px-3 py-3 font-medium">Final</th>
                    <th className="px-3 py-3 font-medium">Status</th>
                    <th className="px-3 py-3 font-medium">Confidence</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80">
                  {evaluations.map((evaluation: any) => (
                    <tr key={evaluation.repository} className="align-top transition hover:bg-slate-900/45">
                      <td className="max-w-[18rem] px-3 py-3 font-mono text-sky-200"><span className="break-all">{evaluation.repository}</span></td>
                      <td className="max-w-[16rem] px-3 py-3">
                        <div className="text-slate-200">{evaluation.task?.title || evaluation.task?.task_id || "—"}</div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {evaluation.task?.category && <Badge className="border-slate-700 text-slate-400">{evaluation.task.category}</Badge>}
                          {evaluation.task?.relation && <Badge className={RELATION_STYLE[evaluation.task.relation] ?? "border-slate-700 text-slate-300"}>{evaluation.task.relation}</Badge>}
                        </div>
                      </td>
                      <td className="px-3 py-3 font-mono text-slate-300">{scoreText(evaluation.absolute_score)}</td>
                      <td className="px-3 py-3 font-mono text-slate-300">{scoreText(evaluation.relative_score)}</td>
                      <td className="px-3 py-3 font-mono text-slate-100">{scoreText(evaluation.final_score)}</td>
                      <td className="px-3 py-3">
                        <Badge className={TASK_STATUS_STYLE[evaluation.status] ?? "border-slate-700 text-slate-300"}>{TASK_STATUS_LABEL[evaluation.status] ?? evaluation.status}</Badge>
                        {evaluation.task?.relation && <div className="mt-1 text-[10px] text-slate-500">{evaluation.task.relation}</div>}
                      </td>
                      <td className="px-3 py-3 font-mono text-slate-300">{typeof evaluation.confidence === "number" ? `${Math.round(evaluation.confidence * 100)}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {evaluations.length === 0 && <EmptyState title="No task evaluations in this batch" description="Task profiling did not produce a comparable evaluation for these repositories." />}

          {validation.limitations?.length > 0 && (
            <details className="rounded-lg border border-slate-800 bg-slate-950/35 p-3.5 text-xs text-slate-400">
              <summary className="cursor-pointer text-slate-300">Batch limitation notes</summary>
              <ul className="mt-2 list-disc space-y-1 pl-5 leading-relaxed">
                {validation.limitations.map((limitation: string, index: number) => <li key={index}>{limitation}</li>)}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}
