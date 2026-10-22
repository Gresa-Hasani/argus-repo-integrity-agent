#!/usr/bin/env python3
"""Reproducible local copy fixture: two real Git repos, real collectors, no LLM/network.

Run: .venv/bin/python scripts/test_copied_repos.py
The reports are deliberately incomplete (AI skipped) but carry real similarity flags.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from argus.cohort import cross_validate, overlap_flags
from argus.config import Config
from argus.pipeline import evaluate
from argus.report import write_reports
from argus.statistics import cohort_statistics, report_statistics

SOURCE = '''"""A small graph-coloring fixture, deliberately copied into both test repositories."""
def greedy_coloring(adjacency):
    colors = {}
    ordered = sorted(adjacency, key=lambda vertex: (-len(adjacency[vertex]), vertex))
    for vertex in ordered:
        forbidden = {colors[neighbor] for neighbor in adjacency[vertex] if neighbor in colors}
        candidate = 0
        while candidate in forbidden:
            candidate += 1
        colors[vertex] = candidate
    for vertex, neighbors in adjacency.items():
        for neighbor in neighbors:
            if vertex != neighbor and colors[vertex] == colors[neighbor]:
                raise ValueError("adjacent vertices cannot share a color")
    return colors
'''


def create_fixture(path: Path, name: str):
    path.mkdir(parents=True)
    (path / 'coloring.py').write_text(SOURCE)
    (path / 'README.md').write_text(f'# {name}\n\nControlled ARGUS test fixture. Source deliberately copied.\n')
    (path / '.gitignore').write_text('__pycache__/\n*.pyc\n.env\n.venv/\n')
    def git(*args):
        subprocess.run(['git', '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', '-c',
                        'user.name=ARGUS Test Fixture', '-c', 'user.email=fixture@example.invalid',
                        '-C', str(path), *args], check=True, capture_output=True)
    git('init', '-q', '-b', 'main')
    git('add', '.')
    git('commit', '-qm', 'Add controlled graph-coloring fixture')


def run_fixture(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='argus-copied-fixture-') as root:
        repos = [Path(root) / 'original', Path(root) / 'copy']
        for path in repos:
            create_fixture(path, path.name)
        comparisons = cross_validate([{'slug': 'fixture/' + p.name, 'local_path': str(p), 'acquisition_status': 'available'} for p in repos])
        flags = overlap_flags(comparisons)
        rows, items = [], []
        # Use a recognizable fixed batch id to reopen this fixture in the UI.
        batch_id = 'c0c0c0c0c0c0'
        for i, path in enumerate(repos):
            cfg = Config(llm_enabled=False, github_api=False, compare=[str(repos[1 - i])], out_dir=str(out))
            result = evaluate(str(path), cfg)
            write_reports(result, out)
            slug = 'fixture/' + path.name
            flagged = slug in flags
            row = report_statistics(result.model_dump(mode='json')) | {'repository': slug, 'state': 'done', 'available': True, 'similarity_flagged': flagged}
            row['flagged'] = row['flagged'] or flagged
            rows.append(row)
            items.append({'job_id': f'fixture-{i}', 'repository': slug, 'state': 'done', 'evaluation_id': result.evaluation_id,
                          'completion_status': result.completion_status.value, 'deterministic_only': True, 'similarity_flagged': flagged})
        batch = {'batch_id': batch_id, 'fixture': True, 'state': 'done', 'model': 'Controlled copied-code fixture (AI skipped)',
                 'total': 2, 'completed': 2, 'failed': 0, 'elapsed_s': 0, 'items': items, 'cross_validation': comparisons}
        (out / f'batch-{batch_id}.json').write_text(json.dumps(batch, indent=2))
        summary = {'fixture': True, 'batch_id': batch_id, 'cross_validation': comparisons, **cohort_statistics(rows)}
        (out / 'copied-fixture-summary.json').write_text(json.dumps(summary, indent=2))
        assert flags == {'fixture/original', 'fixture/copy'}
        assert comparisons[0]['code_a_in_b'] == comparisons[0]['code_b_in_a'] == 1.0
        assert all(r['flagged'] for r in rows)
        return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('argus-reports'))
    summary = run_fixture(parser.parse_args().out)
    print(json.dumps({'batch_id': summary['batch_id'], 'overlap': '100% in both directions',
                      'flagged_repositories': [r['repository'] for r in summary['rows'] if r['flagged']],
                      'without_flagged': len(summary['populations'][0]['rows']),
                      'with_flagged': len(summary['populations'][1]['rows'])}, indent=2))
