"""Comparable measured report statistics. These are evidence metrics, not grades."""
from __future__ import annotations

import math
from statistics import mean, median, stdev
from collections import Counter
from typing import Any


def report_statistics(report: dict[str, Any]) -> dict[str, Any]:
    metrics = report.get('deterministic_metrics') or {}
    counts = (report.get('definition_of_done') or {}).get('counts') or {}
    status = report.get('completion_status')
    flags = counts.get('integrity_flags')
    flagged = status == 'FLAGGED' or isinstance(flags, (int, float)) and flags > 0
    findings = report.get('findings') or []
    coverage = report.get('coverage') or []
    # Unverifiable/error/incomplete checks are not passed checks.
    applicable = [c for c in coverage if c.get('status') != 'NOT_APPLICABLE']
    passed = sum(c.get('status') == 'PASS' for c in applicable)
    scc = metrics.get('scc') or {}
    acquisition = (report.get('repository') or {}).get('acquisition') or {}
    acquired = acquisition.get('success') is True
    return {
        'evaluation_id': report['evaluation_id'], 'status': status, 'flagged': bool(flagged),
        'incomplete': status in {'INCOMPLETE_EVALUATION', 'EVALUATOR_ERROR'},
        'findings': len(findings), 'severity': dict(Counter(f.get('severity', 'UNKNOWN') for f in findings)),
        'source_loc': scc.get('meaningful_source_loc_estimate') if acquired else None,
        'commits': (metrics.get('commits') or {}).get('total') if acquired else None,
        'checks_passed_pct': round(100 * passed / len(applicable), 2) if applicable else None,
        'evaluator_errors': len(report.get('errors') or []),
    }


METRICS = ('findings', 'source_loc', 'commits', 'checks_passed_pct', 'evaluator_errors')


def cohort_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    available = [r for r in rows if r.get('available')]
    populations = [('without_flagged', [r for r in available if not r['flagged']])]
    if any(r['flagged'] for r in available):
        populations.append(('with_flagged', available))
    domains = {key: max([1] + [r[key] for r in available if isinstance(r.get(key), (int, float)) and math.isfinite(r[key])]) for key in METRICS}
    domains['checks_passed_pct'] = 100
    output = []
    for name, population in populations:
        distributions = {}
        for key in METRICS:
            values = [r[key] for r in population if isinstance(r.get(key), (int, float)) and math.isfinite(r[key])]
            width = domains[key] / 10
            bins = [0] * 10
            for value in values:
                bins[min(9, max(0, int(value / width)))] += 1
            average = mean(values) if values else None
            sd = stdev(values) if len(values) > 1 else None
            curve = []
            if len(values) >= 3 and sd and sd > 0:
                for i in range(101):
                    x = domains[key] * i / 100
                    y = math.exp(-0.5 * ((x - average) / sd) ** 2) / (sd * math.sqrt(2 * math.pi)) * len(values) * width
                    curve.append([x, y])
            distributions[key] = {'n': len(values), 'missing': len(population) - len(values), 'mean': average,
                                  'median': median(values) if values else None, 'std_dev': sd,
                                  'max_x': domains[key], 'bins': bins, 'normal_fit': curve}
        output.append({'id': name, 'rows': population, 'excluded': len(rows) - len(population),
                       'incomplete': sum(r['incomplete'] for r in population), 'distributions': distributions})
    return {'rows': rows, 'populations': output, 'note': 'Measured evidence statistics, not assignment grades.'}
