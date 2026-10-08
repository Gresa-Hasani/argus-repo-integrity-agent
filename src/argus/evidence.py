"""Evidence store: the single source of truth that findings are allowed to cite."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable, Optional

from argus.models import Anomaly, Category, Evidence, Lifecycle, Severity


class EvidenceStore:
    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}
        self._anomalies: dict[str, Anomaly] = {}
        self._counters: dict[str, int] = defaultdict(int)

    def add(self, type: str, source: str, summary: str, data: Optional[dict[str, Any]] = None) -> str:
        prefix = type.upper().replace(" ", "_")
        self._counters[prefix] += 1
        evidence_id = f"EV-{prefix}-{self._counters[prefix]:03d}"
        self._items[evidence_id] = Evidence(id=evidence_id, type=type, source=source, summary=summary, data=data or {})
        return evidence_id

    def add_anomaly(
        self,
        category: Category,
        title: str,
        description: str,
        evidence_ids: Iterable[str],
        severity_hint: Severity = Severity.LOW,
        material: bool = False,
        possible_explanations: Optional[list[str]] = None,
        source: str = "",
    ) -> str:
        evidence_ids = list(evidence_ids)
        missing = [e for e in evidence_ids if e not in self._items]
        if missing:
            raise KeyError(f"anomaly cites unknown evidence: {missing}")
        self._counters["ANOMALY"] += 1
        anomaly_id = f"AN-{self._counters['ANOMALY']:03d}"
        anomaly = Anomaly(
            id=anomaly_id,
            category=category,
            title=title,
            description=description,
            evidence_ids=evidence_ids,
            severity_hint=severity_hint,
            material=material,
            possible_explanations=possible_explanations or [],
            # Backed by more than one independent evidence item: corroborated, but still not assessed.
            lifecycle=Lifecycle.CORROBORATED if len(evidence_ids) >= 2 else Lifecycle.OBSERVED,
        )
        self._anomalies[anomaly_id] = anomaly
        # Anomalies are citable too, so a finding can point at the pattern itself.
        self._items[anomaly_id] = Evidence(
            id=anomaly_id,
            type="anomaly",
            source=source or "anomaly_detection",
            summary=f"{title}: {description}",
            data={"category": category.value, "material": material, "evidence_ids": evidence_ids},
        )
        return anomaly_id

    def has(self, evidence_id: str) -> bool:
        return evidence_id in self._items

    def get(self, evidence_id: str) -> Evidence:
        return self._items[evidence_id]

    def all(self) -> list[Evidence]:
        return list(self._items.values())

    def anomalies(self) -> list[Anomaly]:
        return list(self._anomalies.values())

    def anomaly(self, anomaly_id: str) -> Anomaly:
        return self._anomalies[anomaly_id]

    def has_anomaly(self, anomaly_id: str) -> bool:
        return anomaly_id in self._anomalies

    def ids_from(self, source: str) -> list[str]:
        return [e.id for e in self._items.values() if e.source == source]


def build_packet(
    store: EvidenceStore,
    metrics: dict[str, Any],
    evidence_ids: Iterable[str],
    char_budget: int,
) -> tuple[dict[str, Any], list[str]]:
    """Reduce evidence to what one reasoning step needs.

    Returns the packet and the list of evidence ids the model may cite. If the packet would
    exceed the budget, trailing evidence is dropped and the omission is stated in the packet
    (never silent).
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for evidence_id in evidence_ids:
        if evidence_id in seen or not store.has(evidence_id):
            continue
        seen.add(evidence_id)
        ordered.append(evidence_id)
    # Anomalies first: they are what the step must investigate.
    ordered.sort(key=lambda i: 0 if i.startswith("AN-") else 1)

    def render(ids: list[str]) -> dict[str, Any]:
        anomalies = []
        evidence = []
        for evidence_id in ids:
            if store.has_anomaly(evidence_id):
                a = store.anomaly(evidence_id)
                anomalies.append(
                    {
                        "id": a.id,
                        "category": a.category.value,
                        "title": a.title,
                        "description": a.description,
                        "material": a.material,
                        "supporting_evidence_ids": [e for e in a.evidence_ids if e in ids],
                        "possible_legitimate_explanations": a.possible_explanations,
                    }
                )
            else:
                e = store.get(evidence_id)
                evidence.append({"id": e.id, "type": e.type, "summary": e.summary, "data": e.data})
        packet: dict[str, Any] = {"metrics": metrics, "anomalies": anomalies, "evidence": evidence}
        if len(ids) < len(ordered):
            packet["omitted_evidence_count"] = len(ordered) - len(ids)
        return packet

    kept = list(ordered)
    packet = render(kept)
    while len(json.dumps(packet, default=str)) > char_budget and len(kept) > 1:
        kept.pop()
        packet = render(kept)
    return packet, kept
