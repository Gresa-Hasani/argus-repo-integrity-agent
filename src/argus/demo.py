"""Export a finished evaluation as static demo data for the public (backend-less) frontend.

    python -m argus.demo argus-reports/<report>.json

Writes a scrubbed copy (no absolute paths, local service URLs or full email addresses) to
`demo-data/` (read by a local backend) and `ui/public/demo/` (served statically by the frontend),
and rebuilds `ui/public/demo/index.json`. The evaluation itself is not changed or re-run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from argus.models import FinalEvaluation
from argus.server import public_result, scrub_text

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "demo-data"
FRONTEND_DIR = ROOT / "ui" / "public" / "demo"


def index_row(result: FinalEvaluation) -> dict:
    """Same shape as a row of GET /api/evaluations."""
    name = "/".join(str(x) for x in (result.repository.get("owner"), result.repository.get("name")) if x)
    return {
        "evaluation_id": result.evaluation_id, "repository": name, "timestamp": result.timestamp, "status": result.completion_status.value,
        "model": result.model.get("model"), "kind": result.repository.get("kind"), "findings": result.definition_of_done.counts.get("open_findings", 0),
    }


def export(report_json: Path) -> FinalEvaluation:
    result = FinalEvaluation.model_validate(json.loads(report_json.read_text(encoding="utf-8")))
    public = public_result(result)
    FinalEvaluation.model_validate(public)  # the scrubbed copy must still be a valid ARGUS result
    payload = json.dumps(public, indent=2, ensure_ascii=False)
    markdown = scrub_text(report_json.with_suffix(".md").read_text(encoding="utf-8"))
    BACKEND_DIR.mkdir(parents=True, exist_ok=True)
    FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
    (BACKEND_DIR / report_json.name).write_text(payload, encoding="utf-8")
    (BACKEND_DIR / report_json.with_suffix(".md").name).write_text(markdown, encoding="utf-8")
    # The frontend addresses demo files by evaluation id only.
    (FRONTEND_DIR / f"{result.evaluation_id}.json").write_text(payload, encoding="utf-8")
    (FRONTEND_DIR / f"{result.evaluation_id}.md").write_text(markdown, encoding="utf-8")
    rows = []
    for path in sorted(FRONTEND_DIR.glob("argus-*.json")):
        rows.append(index_row(FinalEvaluation.model_validate(json.loads(path.read_text(encoding="utf-8")))))
    rows.sort(key=lambda row: row["timestamp"], reverse=True)
    (FRONTEND_DIR / "index.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m argus.demo <report.json>")
    exported = export(Path(sys.argv[1]))
    print(f"exported {exported.evaluation_id} ({exported.completion_status.value}) to demo-data/ and ui/public/demo/")
