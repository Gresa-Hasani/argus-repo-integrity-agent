"""Deterministic finding policy.

The model proposes candidate findings. This layer decides what each candidate is:

    FACT -> OBSERVATION -> ENGINEERING_WEAKNESS -> ANOMALY -> MATERIAL_INTEGRITY_CONCERN

The decision is taken from the evidence a candidate cites, never from the candidate's wording, its
proposed severity or its request for manual review. A candidate is a finding only if a deterministic
basis exists for it; otherwise it is an observation or is discarded. Everything here is pure and
free of I/O so it can be tested exhaustively.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from argus.evidence import EvidenceStore
from argus.models import SEVERITY_RANK, Category, Finding, FindingType, LLMFinding, Observation, Outcome, Severity

# Categories whose findings exist only when a deterministic anomaly pattern was detected.
ANOMALY_ONLY = {
    Category.COAUTHOR_INTEGRITY, Category.CONTRIBUTION_INTEGRITY, Category.LOC_INFLATION, Category.COMMIT_INFLATION,
    Category.TIMELINE_ANOMALY, Category.BRANCH_WORKFLOW,
}
# Categories whose findings are produced by deterministic rules; the model may only add reasoning to them.
RULE_OWNED = {Category.REPOSITORY_HYGIENE, Category.CI_CD, Category.SECRET_EXPOSURE, Category.SIMILARITY, Category.CODE_PROVENANCE}


@dataclass
class Decision:
    finding_type: FindingType
    reason: str
    category: Optional[Category] = None
    severity: Severity = Severity.INFO
    material: bool = False
    requires_manual_review: bool = False
    outcome: Outcome = Outcome.PASS
    basis: list[str] = field(default_factory=list)
    merge_into: Optional[str] = None  # finding_id of an existing finding that already covers this
    title: Optional[str] = None  # deterministic title/text: the finding statement never comes from the model
    text: Optional[str] = None

    @property
    def action(self) -> str:
        if self.merge_into:
            return "MERGED"
        if self.finding_type == FindingType.NORMAL:
            return "DISCARDED"
        if self.finding_type == FindingType.OBSERVATION:
            return "OBSERVATION"
        return "ACCEPTED"


def outcome_for(finding_type: FindingType, material: bool) -> Outcome:
    """FAIL is reserved for genuine engineering failures; material concerns go to REVIEW; the rest PASS."""
    if material:
        return Outcome.REVIEW
    if finding_type == FindingType.ENGINEERING_WEAKNESS:
        return Outcome.FAIL
    return Outcome.PASS


def _cap(severity: Severity, ceiling: Severity) -> Severity:
    return severity if SEVERITY_RANK[severity] <= SEVERITY_RANK[ceiling] else ceiling


def assess_candidate(candidate: LLMFinding, store: EvidenceStore, findings: list[Finding]) -> Decision:
    """Classify one model candidate. `findings` are the findings that already exist."""
    cited = [store.get(e) for e in dict.fromkeys(candidate.evidence_ids) if store.has(e)]
    if not cited:
        return Decision(FindingType.NORMAL, "no valid evidence cited")
    anomalies = [store.anomaly(e.id) for e in cited if store.has_anomaly(e.id)]

    # 1. Anchored in deterministically detected patterns: the pattern, not the model, sets category and severity.
    if anomalies:
        material = any(a.material for a in anomalies) or len(anomalies) >= 2
        lead = max(anomalies, key=lambda a: (a.material, SEVERITY_RANK[a.severity_hint]))
        existing = next((f for f in findings if lead.id in f.evidence_ids), None)
        basis = [f"anomaly {a.id} ({'material' if a.material else 'non-material'}): {a.title}" for a in anomalies]
        if len(anomalies) >= 2:
            basis.append(f"{len(anomalies)} independent anomaly patterns combined")
        severity = lead.severity_hint if material else _cap(lead.severity_hint, Severity.MEDIUM)
        return Decision(
            FindingType.MATERIAL_INTEGRITY_CONCERN if material else FindingType.ANOMALY,
            "anchored in a deterministically detected anomaly", lead.category, severity, material, material,
            outcome_for(FindingType.ANOMALY, material), basis, existing.finding_id if existing else None,
            title=lead.title, text=" ".join(a.description for a in anomalies),
        )

    by_type: dict[str, list[Any]] = {}
    for e in cited:
        by_type.setdefault(e.type, []).append(e)
    category = candidate.category

    # 2. Categories that only exist as anomalies: without a detected pattern there is nothing to find.
    if category in ANOMALY_ONLY:
        return Decision(FindingType.NORMAL, f"{category.value} requires a deterministically detected anomaly pattern; none is cited, so this is an ordinary repository characteristic")

    # 3. README mismatch: only a deterministically CONTRADICTED claim can support it.
    if category == Category.README_MISMATCH:
        claims = by_type.get("readme_claim", [])
        contradicted = [c for c in claims if c.data.get("status") == "CONTRADICTED"]
        statuses = ", ".join(f"{c.data.get('technology')}={c.data.get('status')}" for c in claims) or "no claim cited"
        if not contradicted:
            return Decision(FindingType.NORMAL, f"README_MISMATCH is valid only for a CONTRADICTED claim; deterministic cross-check says: {statuses}")
        existing = next((f for f in findings if f.category == category and any(c.id in f.evidence_ids for c in contradicted)), None)
        return Decision(
            FindingType.ENGINEERING_WEAKNESS, "README claim contradicted by repository evidence", category,
            Severity.MEDIUM if len(contradicted) >= 2 else Severity.LOW, False, False, Outcome.FAIL,
            [f"claim {c.id}: {c.data.get('technology')} is CONTRADICTED" for c in contradicted], existing.finding_id if existing else None,
        )

    # 4. Commit traceability: a weakness only when the measured share of low-information messages is high.
    if category == Category.COMMIT_INTEGRITY:
        for e in by_type.get("commit_quality", []):
            ratio, n = e.data.get("weak_message_ratio", 0), e.data.get("non_merge_commits", 0)
            if n >= 5 and ratio >= 0.3:
                return Decision(
                    FindingType.ENGINEERING_WEAKNESS, "measured share of low-information commit messages is high", category,
                    Severity.MEDIUM if ratio >= 0.6 else Severity.LOW, False, False, Outcome.FAIL,
                    [f"{e.id}: weak_message_ratio={ratio:.0%} over {n} non-merge commits (threshold 30%, minimum 5 commits)"],
                    title="High share of low-information commit messages",
                    text=f"{ratio:.0%} of {n} non-merge commits use low-information messages, which reduces traceability.",
                )
        return Decision(FindingType.NORMAL, "commit metrics do not show a traceability weakness (needs >=5 commits and >=30% low-information messages)")

    # 5. AI assistance is an observation, and only when explicit signals exist.
    if category == Category.AI_ASSISTANCE:
        for e in by_type.get("ai_signals", []):
            if e.data.get("commits_attributed_to_ai_tools") or e.data.get("commits_with_ai_tool_markers_in_message") or e.data.get("ai_assistant_config_files"):
                return Decision(FindingType.OBSERVATION, "explicit AI-tool signals exist; AI assistance is not restricted by the evaluation rules", category)
        return Decision(FindingType.NORMAL, "no explicit AI-tool attribution in the evidence; style is not evidence")

    # 6. Rule-owned categories: deterministic rules raise these findings; the model can only add reasoning.
    if category in RULE_OWNED:
        ids = {e.id for e in cited}
        existing = next((f for f in findings if f.origin == "deterministic" and f.category == category and ids & set(f.evidence_ids)), None)
        if existing:
            return Decision(existing.finding_type, "already raised by a deterministic rule; model reasoning attached", category, existing.severity, existing.material, existing.requires_manual_review, existing.outcome, [], existing.finding_id)
        return Decision(FindingType.NORMAL, f"{category.value} findings are raised by deterministic rules; no rule fired on the cited evidence")

    return Decision(FindingType.NORMAL, f"no deterministic basis for a {category.value} finding")


_MANUAL = r"\b(manual(ly)?[- ]review\w*|human review|requires? (a )?review|needs? (a )?review|should be reviewed|further (review|investigation))\b"
_MATERIAL = r"\b(?<!non-)(?<!non )material\b|\bintegrity (flag|concern|violation)s?\b|\bred flags?\b"
_SEVERITY_WORD = re.compile(r"(?i)\b(critical|high|medium|low)[- ]severity\b|\bseverity (?:is |of |level )?(critical|high|medium|low)\b")
_TYPE_TOKEN = re.compile(r"\b(NORMAL|OBSERVATION|ENGINEERING_WEAKNESS|ANOMALY|MATERIAL_INTEGRITY_CONCERN)\b")
_OUTCOME_TOKEN = re.compile(r"\b(PASS|FAIL|REVIEW|UNVERIFIABLE)\b")


def advisory_conflicts(text: str, *, manual_review: bool, material: bool, severity: str, finding_type: str, outcome: str) -> list[str]:
    """Reason codes for model text that contradicts a finding's authoritative fields."""
    codes = []
    if not manual_review and _affirms(text, _MANUAL):
        codes.append("contradicts_manual_review")
    if not material and _affirms(text, _MATERIAL):
        codes.append("contradicts_material")
    for m in _SEVERITY_WORD.finditer(text):
        if (m.group(1) or m.group(2)).upper() != severity:
            codes.append("contradicts_severity")
    if any(t != finding_type for t in _TYPE_TOKEN.findall(text)):
        codes.append("contradicts_finding_type")
    if any(t != outcome for t in _OUTCOME_TOKEN.findall(text)):
        codes.append("contradicts_outcome")
    if _ACCUSATORY.search(text):
        codes.append("accusatory_language")
    return list(dict.fromkeys(codes))


def sanitize_advisory(text: str, **fields: Any) -> tuple[str, list[str]]:
    """Drop the sentences of model text that contradict the authoritative fields; report why."""
    kept, removed = [], []
    for sentence in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        if not sentence:
            continue
        codes = advisory_conflicts(sentence, **fields)
        if codes:
            removed += codes
        else:
            kept.append(sentence)
    return " ".join(kept), list(dict.fromkeys(removed))


# ------------------------------------------------------------------------------------------------
# Repository observations: plain facts, generated from metrics. Never counted as findings.
# ------------------------------------------------------------------------------------------------
def repository_observations(m: dict[str, Any], kind: str) -> list[Observation]:
    out: list[Observation] = []

    def add(topic: str, text: str, evidence: Optional[list[Optional[str]]] = None) -> None:
        out.append(Observation(id=f"OBS-{len(out) + 1:03d}", topic=topic, text=text, evidence_ids=[e for e in (evidence or []) if e]))

    if "commits" not in m:
        return out
    commits, contrib, tl, br, scc = m["commits"], m["contributors"], m["timeline"], m["branches"], m["scc"]
    cev = contrib["evidence"]
    humans = contrib["human_contributors"]
    add("contributors", "Single human contributor" if humans == 1 else f"{humans} human contributors", list(cev["contributors"].values())[:6])

    root = commits["granularity"].get("root_commit")
    n = commits["total"]
    if n == 1:
        add("history", "Single commit: the repository consists of its initial commit only", [tl["evidence"]["timeline"]])
    else:
        add("history", f"{n} commits over {tl['duration_hours']:g} hours on {tl['active_days']} active day(s)", [tl["evidence"]["timeline"]])
    if root and root["is_initial_scaffold"]:
        add("history", f"Initial commit {root['sha']} ({root['message']!r}) is a project scaffold: +{root['additions']:,} raw lines, +{root['meaningful_additions']:,} meaningful source lines (estimate)")
    if not tl["deadline"]:
        add("timeline", "No deadline or expected milestone configured: timing of activity is not assessed against any expectation")

    ws = commits["inflation"]["whitespace_only_commits"]
    if 0 < ws < 3:
        add("history", f"{ws} isolated whitespace-only commit(s): below the pattern threshold of 3, not an anomaly", [commits["evidence"]["inflation"]])

    co = contrib["coauthorship"]
    add("coauthorship", "Co-authorship: none detected" if not co["total_coauthored_commits"] else f"Co-authorship: {co['total_coauthored_commits']} commit(s) carry Co-authored-by trailers", [cev["coauthorship"]])
    add("workflow", br["workflow"].capitalize() + f" ({br['branch_count']} branch(es), {br['merge_commits']} merge commit(s))", [br["evidence"]["branches"]])

    gh = m.get("github") or {}
    if kind != "github":
        add("workflow", "Pull requests: not applicable (local repository)")
    elif (gh.get("pull_requests") or {}).get("count") == 0:
        add("workflow", "No pull requests on GitHub")

    ci = m.get("ci") or {}
    if not ci.get("workflow_files") and not ci.get("other_ci_files"):
        add("ci", "No CI workflows")
    hy = m.get("hygiene")
    if hy:
        st = hy["structure"]
        if not st["has_tests"]:
            add("tests", "No test files", [hy["evidence"]["structure"]])
        if not st["has_license"]:
            add("structure", "No LICENSE file", [hy["evidence"]["structure"]])
        missing = hy["gitignore"]["missing_expected_patterns"]
        if missing:
            add("hygiene", ".gitignore does not list some common exclusions for the detected stack: " + "; ".join(f"{x['ecosystem']}: {', '.join(x['expected'])}" for x in missing), [hy["evidence"]["gitignore"]])

    excluded = ", ".join(f"{x['category']} {x['code_loc']:,}" for x in scc["excluded_content"][:5])
    add("composition", f"Codebase composition: {scc['raw_code_loc']:,} raw code LOC, of which {scc['meaningful_source_loc_estimate']:,} is meaningful source (estimate)" + (f"; the remainder is {excluded}" if excluded else ""))

    ai = m.get("ai_signals")
    if ai:
        if ai["commits_attributed_to_ai_tools"] or ai["commits_with_ai_tool_markers_in_message"]:
            add("ai_assistance", f"Explicit AI-tool attribution on {ai['commits_attributed_to_ai_tools']} commit(s)", [ai["evidence"]["ai_signals"]])
        else:
            add("ai_assistance", "No AI-tool attribution in commit history", [ai["evidence"]["ai_signals"]])
        if ai["ai_assistant_config_files"]:
            add("ai_assistance", "AI-assistant configuration files tracked: " + ", ".join(ai["ai_assistant_config_files"][:6]), [ai["evidence"]["ai_signals"]])

    sim = m.get("similarity") or {}
    if not sim.get("performed"):
        add("provenance", "No similarity comparison supplied: provenance is not verified by similarity evidence")
    readme = m.get("readme")
    if readme and readme.get("present"):
        open_claims = [c for c in readme["claims"] if c["status"] in ("NOT_VERIFIED", "PARTIALLY_VERIFIED")]
        if open_claims:
            add("readme", "README technology mentions without full supporting evidence: " + ", ".join(f"{c['technology']} ({c['status']})" for c in open_claims), [c["evidence_id"] for c in open_claims][:8])
    return out


# ------------------------------------------------------------------------------------------------
# Executive summary: deterministic text, plus consistency checks for any model-written narrative.
# ------------------------------------------------------------------------------------------------
STATUSES = ("DONE_CLEAN", "DONE_WITH_FINDINGS", "FLAGGED", "INCOMPLETE_EVALUATION", "EVALUATOR_ERROR")
_NEG = r"\b(no|not|none|zero|without|0|neither|nor|never)\b"
_ACCUSATORY = re.compile(r"(?i)\b(plagiari[sz]\w*|cheat\w*|fraud\w*|misconduct|dishonest\w*|fabricat\w*)\b")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def _affirms(text: str, pattern: str) -> bool:
    """True if a sentence matches `pattern` without a negation in that sentence."""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if re.search(pattern, sentence, re.I) and not re.search(_NEG, sentence, re.I):
            return True
    return False


def deterministic_summary(name: str, status: str, counts: dict[str, int], scale: Optional[dict[str, Any]], reasons: list[str]) -> str:
    parts = [f"ARGUS evaluated {name} and the evaluation status is {status}."]
    if scale:
        parts.append(
            f"The repository has {scale['commits']} commit(s) by {scale['human_contributors']} human contributor(s) on {scale['branches']} branch(es), "
            f"with {scale['code_loc']:,} raw code LOC of which {scale['meaningful_source_loc_estimate']:,} is estimated to be meaningful source."
        )
    parts.append(
        f"{counts['engineering_weaknesses']} engineering weakness(es), {counts['integrity_findings']} integrity finding(s) and {counts['security_findings']} security finding(s) are open; "
        f"{counts['integrity_flags']} of them are material."
    )
    parts.append("Manual review is required." if counts["manual_review_requirements"] else "No manual review is required.")
    if counts["evaluator_errors"] or counts["mandatory_coverage_gaps"] or counts["unverifiable"]:
        parts.append(f"{counts['evaluator_errors']} evaluator error(s), {counts['mandatory_coverage_gaps']} mandatory coverage gap(s) and {counts['unverifiable']} unverifiable check(s) limit this evaluation.")
    else:
        parts.append("All applicable checks completed with no evaluator errors and no coverage gaps.")
    if reasons:
        parts.append("Status basis: " + "; ".join(r.rstrip(".") for r in reasons[:3]) + ".")
    return " ".join(parts)


_SLUG = re.compile(r"(?<![\w./:-])([A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+)(?![\w/])")


def summary_problems(text: str, status: str, counts: dict[str, int], allowed_numbers: Optional[set[str]] = None, repository: Optional[str] = None) -> list[str]:
    """Ways in which a narrative contradicts the computed evaluation, each as "<reason_code>: <detail>".

    Empty list means consistent."""
    problems = []
    if status not in text:
        problems.append(f"missing_authoritative_status: must state the evaluation status exactly as {status}")
    # Longest names first so DONE_WITH_FINDINGS is not mistaken for a stray DONE_CLEAN-like token.
    stripped = text.replace(status, "")
    for other in STATUSES:
        if other != status and other in stripped:
            problems.append(f"contradicts_authoritative_status: mentions status {other}, but the computed status is {status}")
    if counts.get("manual_review_requirements", 0) == 0 and _affirms(text, r"manual(ly)?[- ]review"):
        problems.append("contradicts_manual_review_status: says or implies manual review is needed, but the computed result is: manual review required = NO")
    if counts.get("manual_review_requirements", 0) > 0 and re.search(r"(?i)\bno\b[^.]{0,30}manual review|manual review[^.]{0,20}\bnot\b", text):
        problems.append("contradicts_manual_review_status: says manual review is not needed, but the computed result requires manual review")
    if counts.get("integrity_flags", 0) == 0 and _affirms(text, r"\b(integrity (flag|concern|issue)s?|(?<!non-)(?<!non )material (integrity )?(finding|concern|issue)s?|suspicious|red flags?)\b"):
        problems.append("contradicts_integrity_flag_count: describes integrity or material concerns, but the computed result has 0 integrity flags")
    if counts.get("evaluator_errors", 0) == 0 and _affirms(text, r"\bevaluator (error|failure)s?\b"):
        problems.append("contradicts_evaluator_error_count: mentions evaluator errors, but none occurred")
    if counts.get("mandatory_coverage_gaps", 0) == 0 and counts.get("unverifiable", 0) == 0 and _affirms(text, r"\b(coverage gaps?|incomplete evaluation|unverifiable)\b"):
        problems.append("contradicts_coverage_gaps: mentions coverage gaps, but none exist")
    if (counts.get("mandatory_coverage_gaps", 0) or counts.get("evaluator_errors", 0)) and re.search(r"(?i)\bno (coverage gaps|evaluator errors)\b|\b(all|every) (applicable )?checks? (were |was )?(completed|passed)\b", stripped):
        problems.append("contradicts_coverage_gaps: describes the evaluation as complete despite coverage gaps or evaluator errors")
    if repository and "/" in repository:
        import difflib

        for token in _SLUG.findall(text):
            token = token.rstrip(".,;:")
            if token.lower() != repository.lower() and difflib.SequenceMatcher(None, token.lower(), repository.lower()).ratio() >= 0.6:
                problems.append(f"misnamed_repository: writes the repository as '{token}', but the evaluated repository is '{repository}'")
    if _ACCUSATORY.search(text):
        problems.append("accusatory_language: uses accusatory language; ARGUS reports evidence, not verdicts")
    if allowed_numbers is not None:
        unknown = sorted({n for n in _NUMBER.findall(text) if n.replace(",", "").rstrip(".") not in allowed_numbers})
        if unknown:
            problems.append(f"unsupported_number: contains numbers that are not in the evidence packet: {', '.join(unknown[:8])}")
    return problems


def reason_codes(problems: list[str]) -> list[str]:
    """Stable machine-readable codes for summary_problems() entries, in order, without duplicates."""
    return list(dict.fromkeys(p.split(":", 1)[0] for p in problems))


def numbers_in(obj: Any) -> set[str]:
    """Every number that appears anywhere in a packet, as the model may legitimately repeat it."""
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            found.add(str(value))
            if isinstance(value, float) and 0 <= value <= 1:
                found.add(f"{value * 100:g}")  # 0.96 may be written as 96
                found.add(str(round(value * 100)))
            if isinstance(value, float) and value == int(value):
                found.add(str(int(value)))
        elif isinstance(value, str):
            found.update(n.replace(",", "") for n in _NUMBER.findall(value))
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(k)
                walk(v)
        elif isinstance(value, (list, tuple, set)):
            for v in value:
                walk(v)

    walk(obj)
    return found
