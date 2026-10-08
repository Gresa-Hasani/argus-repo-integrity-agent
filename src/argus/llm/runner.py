"""Runs one reasoning step: prompt + evidence packet -> validated, evidence-grounded structured output."""

from __future__ import annotations

import copy
import json
import re
from importlib import resources
from typing import Any, Callable, Optional, Type

from pydantic import BaseModel, ValidationError

from argus.evidence import EvidenceStore
from argus.llm.interface import LLMError, LLMProvider
from argus.models import AnalysisResult

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


class PolicyRejection(ValueError):
    """Structurally valid output that a deterministic consistency check refused."""


class LLMStepError(Exception):
    """A reasoning step could not produce a valid result. Never converted into a pass.

    kind: "call_failed" | "invalid_output" | "policy_rejected"
    """

    def __init__(self, step: str, reason: str, attempts: int, kind: str = "invalid_output") -> None:
        super().__init__(f"{step}: {reason} (after {attempts} attempt(s))")
        self.step, self.reason, self.attempts, self.kind = step, reason, attempts, kind


def load_prompt(name: str) -> str:
    return resources.files("argus.llm.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")


def extract_json(text: str) -> Any:
    text = _THINK.sub("", text).strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fenced:
        text = fenced.group(1)
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found in model output")
        text = text[start: end + 1]
    return json.loads(text)


def constrained_schema(
    model_cls: Type[BaseModel], evidence_ids: list[str], anomaly_ids: list[str], classifications: Optional[list[str]]
) -> dict[str, Any]:
    """JSON Schema for the runtime's constrained decoding, narrowed to the ids in this packet."""
    schema = copy.deepcopy(model_cls.model_json_schema())
    defs = schema.get("$defs", {})
    props = schema.get("properties", {})
    if "LLMFinding" in defs:
        if evidence_ids:
            defs["LLMFinding"]["properties"]["evidence_ids"]["items"] = {"type": "string", "enum": evidence_ids}
        else:
            props["findings"]["maxItems"] = 0
    if "AnomalyResolution" in defs:
        if anomaly_ids:
            defs["AnomalyResolution"]["properties"]["anomaly_id"] = {"type": "string", "enum": anomaly_ids}
        else:
            props["resolved_anomalies"]["maxItems"] = 0
    # Bound the answer: local models are slow, and long lists add nothing a reviewer can use.
    for key, limit in (("findings", 5), ("resolved_anomalies", 6), ("unresolved_questions", 3)):
        if key in props:
            props[key].setdefault("maxItems", limit)
    if "LLMFinding" in defs:
        defs["LLMFinding"]["properties"]["possible_explanations"]["maxItems"] = 3
    if classifications and "classification" in props:
        props["classification"] = {"type": "string", "enum": classifications}
        schema.setdefault("required", []).append("classification")
    return schema


def validate_result(
    result: BaseModel, allowed: set[str], anomaly_ids: set[str], store: EvidenceStore, classifications: Optional[list[str]]
) -> None:
    """Grounding checks the schema cannot express. Raises ValueError with a message the model can act on."""
    if not isinstance(result, AnalysisResult):
        return
    for finding in result.findings:
        unknown = [e for e in finding.evidence_ids if e not in allowed or not store.has(e)]
        if unknown:
            raise ValueError(
                f"finding '{finding.title}' cites evidence ids that are not in the evidence packet: {unknown}. "
                "Only ids present in the packet may be cited."
            )
    for resolution in result.resolved_anomalies:
        if resolution.anomaly_id not in anomaly_ids:
            raise ValueError(f"resolved_anomalies references '{resolution.anomaly_id}', which is not an anomaly in the packet")
    if classifications:
        value = (result.classification or "").strip().upper()
        if value not in classifications:
            raise ValueError(f"classification must be one of {classifications}, got {result.classification!r}")
        result.classification = value


def run_step(
    provider: LLMProvider,
    step: str,
    packet: dict[str, Any],
    allowed_ids: list[str],
    store: EvidenceStore,
    model_cls: Type[BaseModel] = AnalysisResult,
    classifications: Optional[list[str]] = None,
    max_attempts: int = 2,
    extra_check: Optional[Callable[[BaseModel], None]] = None,
) -> tuple[BaseModel, dict[str, Any]]:
    system = load_prompt("system")
    anomaly_ids = [i for i in allowed_ids if store.has_anomaly(i)]
    schema = constrained_schema(model_cls, allowed_ids, anomaly_ids, classifications)
    base_prompt = (
        f"{load_prompt(step)}\n\n## EVIDENCE PACKET (authoritative, measured deterministically)\n"
        f"```json\n{json.dumps(packet, separators=(",", ":"), default=str, ensure_ascii=False)}\n```\n\n"
        f"## IDS YOU MAY CITE\n{', '.join(allowed_ids) if allowed_ids else '(none - return no findings)'}\n\n"
        "Return the JSON object now."
    )
    meta: dict[str, Any] = {"step": step, "attempts": 0, "duration_s": 0.0, "repaired": False}
    prompt = base_prompt
    last_error, last_kind = "no attempt made", "invalid_output"
    for attempt in range(1, max_attempts + 1):
        meta["attempts"] = attempt
        try:
            response = provider.generate(system, prompt, schema)
        except LLMError as exc:
            raise LLMStepError(step, f"model call failed: {exc}", attempt, "call_failed") from exc
        meta["duration_s"] = round(meta["duration_s"] + response.duration_s, 2)
        meta["model"] = response.model
        try:
            result = model_cls.model_validate(extract_json(response.text))
            validate_result(result, set(allowed_ids), set(anomaly_ids), store, classifications)
            if extra_check:
                extra_check(result)  # raises ValueError with a message the model can act on
            meta["repaired"] = attempt > 1
            return result, meta
        except (ValueError, ValidationError) as exc:  # json.JSONDecodeError is a ValueError
            last_error = str(exc)[:600]
            last_kind = "policy_rejected" if isinstance(exc, PolicyRejection) else "invalid_output"
            prompt = (
                f"{base_prompt}\n\n## YOUR PREVIOUS RESPONSE WAS REJECTED\n{last_error}\n"
                "Return a corrected JSON object only. Cite only ids listed under IDS YOU MAY CITE."
            )
    raise LLMStepError(step, last_error if last_kind == "policy_rejected" else f"invalid structured output: {last_error}", max_attempts, last_kind)
