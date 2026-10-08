"""Writes the JSON Schemas derived from the Pydantic models: `python -m argus.llm.schemas.export`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from argus.models import AnalysisResult, FinalEvaluation, Finding


def schemas() -> dict[str, dict[str, Any]]:
    return {
        "finding.json": Finding.model_json_schema(),
        "analysis.json": AnalysisResult.model_json_schema(),
        "final_report.json": FinalEvaluation.model_json_schema(),
    }


def main() -> None:
    here = Path(__file__).parent
    for name, schema in schemas().items():
        (here / name).write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {here / name}")


if __name__ == "__main__":
    main()
