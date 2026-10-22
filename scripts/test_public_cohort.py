"""Reproduce static testing after cloning the public manifest entries.

Run: .venv/bin/python scripts/test_public_cohort.py
Requires: pip install -e '.[dev,analytics]'
No code from a selected repository is executed.
"""
import json
import sys
from pathlib import Path

from argus.cli import write_validated
from argus.cohort import cross_validate, plot_grades
from argus.collectors.gitutil import git
from argus.config import Config
from argus.pipeline import Evaluation

ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "test-cohort"
OUT = COHORT / "output"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((COHORT / "manifest.json").read_text())
    if "--plots-only" in sys.argv:
        data = json.loads((OUT / "cross-validation.json").read_text())
        records, pairs = data["repositories"], data["pairs"]
    else:
        records = []
        for entry in manifest["repositories"]:
            repo = COHORT / "repos" / entry["slug"].replace("/", "--")
            row = dict(entry, local_path=str(repo), acquisition_status="unavailable")
            try:
                row["head"] = git(repo, "rev-parse", "HEAD").strip()
                row["acquisition_status"] = "available"
                print(f"Evaluating {entry['slug']}", flush=True)
                cfg = Config(llm_enabled=False, github_api=False, out_dir=str(OUT / "reports"))
                result = Evaluation(str(repo), cfg).run()
                write_validated(result, OUT / "reports")
                row.update(completion_status=result.completion_status.value, evaluation_id=result.evaluation_id,
                           material_findings=sum(f.material and f.status.value == "OPEN" for f in result.findings),
                           findings=len(result.findings), score=None, grade_verified=False,
                           flagged=True if any(f.material and f.status.value == "OPEN" for f in result.findings) else None,
                       flag_state="material finding detected" if any(f.material and f.status.value == "OPEN" for f in result.findings) else "pending full evaluation",
                       benchmark_status="unverified: no independent solution validation")
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            records.append(row)
        pairs = cross_validate(records)
        data = {"purpose": manifest["purpose"], "repositories": records, "pairs": pairs,
                "grades": "Real grades unavailable: no assignment rubric or independently validated benchmark outcomes.",
                "flag_policy": "Deterministic-only evaluations are incomplete, never treated as cleared."}
        (OUT / "cross-validation.json").write_text(json.dumps(data, indent=2))

    # Explicit synthetic fixtures exercise both plots without attributing grades or flags to real projects.
    fixture = [{"slug": f"synthetic-{i + 1}", "score": s, "flagged": i in (1, 6), "grade_verified": True}
               for i, s in enumerate([58, 65, 70, 73, 77, 80, 85, 90])]
    (OUT / "synthetic-grades.json").write_text(json.dumps({"synthetic": True, "purpose": "Chart/filter test only; no real repository grades or flags", "rows": fixture}, indent=2))
    plot_grades(fixture, OUT, title="SYNTHETIC TEST GRADES — not repository results")

    import matplotlib.pyplot as plt
    import numpy as np
    labels = [r["slug"] for r in records]
    matrix = np.full((len(labels), len(labels)), np.nan)
    for pair in pairs:
        i, j = labels.index(pair["a"]), labels.index(pair["b"])
        matrix[i, j] = pair["code_a_in_b"] if pair["code_a_in_b"] is not None else np.nan
        matrix[j, i] = pair["code_b_in_a"] if pair["code_b_in_a"] is not None else np.nan
    fig, ax = plt.subplots(figsize=(10, 7))
    cmap = plt.get_cmap("Blues").copy()
    cmap.set_bad("#e5e5e5")
    im = ax.imshow(matrix, vmin=0, vmax=1, cmap=cmap)
    ax.set_xticks(range(len(labels)), labels, rotation=25, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    ax.set_title("Public test cohort: directional code containment\nRows contained in columns; grey = unavailable / self comparison")
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, "—" if np.isnan(matrix[i, j]) else f"{matrix[i, j]:.1%}", ha="center", va="center")
    fig.colorbar(im, ax=ax, label="Token-shingle containment")
    fig.tight_layout()
    fig.savefig(OUT / "code-containment.png", dpi=160)
    fig.savefig(OUT / "code-containment.svg")
    plt.close(fig)
    print(json.dumps([{k: r.get(k) for k in ('slug', 'head', 'completion_status', 'findings', 'material_findings')} for r in records], indent=2))
    print(f"Compared {len(pairs)} pairs. Outputs: {OUT}")


if __name__ == "__main__":
    main()
