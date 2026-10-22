"""Independent static check of saved ITC2007 UD2 schedules (no solver execution)."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / 'test-cohort/repos/Docheinstein--itc2007-cct'


def validate(instance: Path, solution: Path):
    sections = defaultdict(list)
    header = {}
    section = ''
    for raw in instance.read_text().splitlines():
        line = raw.strip()
        if not line or line == 'END.':
            continue
        if line.endswith(':'):
            section = line[:-1]
        elif not section:
            key, value = line.split(':', 1)
            header[key] = value.strip()
        else:
            sections[section].append(line.split())
    courses = {c: (t, int(n), int(d), int(s)) for c, t, n, d, s in sections['COURSES']}
    rooms = {r: int(cap) for r, cap in sections['ROOMS']}
    curricula = {r[0]: set(r[2:]) for r in sections['CURRICULA']}
    unavailable = {(c, int(d), int(p)) for c, d, p in sections['UNAVAILABILITY_CONSTRAINTS']}
    rows = []
    errors = []
    for line in solution.read_text().splitlines():
        if not line.strip():
            continue
        c, r, d, p = line.split()
        d, p = int(d), int(p)
        if c not in courses or r not in rooms or not 0 <= d < int(header['Days']) or not 0 <= p < int(header['Periods_per_day']):
            errors.append('unknown course/room or out-of-range period')
            continue
        rows.append((c, r, d, p))
    counts = Counter(c for c, r, d, p in rows)
    errors += [f'{c}: lecture count mismatch' for c, (_, n, _, _) in courses.items() if counts[c] != n]
    seen = defaultdict(set)
    for c, r, d, p in rows:
        resources = [('course', c), ('room', r), ('teacher', courses[c][0])]
        resources += [('curriculum', cur) for cur, members in curricula.items() if c in members]
        for resource in resources:
            if (d, p) in seen[resource]:
                errors.append(f'collision: {resource}')
            seen[resource].add((d, p))
        if (c, d, p) in unavailable:
            errors.append(f'unavailable: {c}')
    capacity = sum(max(0, courses[c][3] - rooms[r]) for c, r, d, p in rows)
    min_days = 5 * sum(max(0, courses[c][2] - len({d for cc, r, d, p in rows if cc == c})) for c in courses)
    stability = sum(max(0, len({r for cc, r, d, p in rows if cc == c}) - 1) for c in courses)
    compactness = 0
    for cur in curricula:
        slots = seen[('curriculum', cur)]
        compactness += 2 * sum((d, p-1) not in slots and (d, p+1) not in slots for d, p in slots)
    return {'instance': instance.name, 'instance_sha256': hashlib.sha256(instance.read_bytes()).hexdigest(),
            'solution_sha256': hashlib.sha256(solution.read_bytes()).hexdigest(),
            'objective': 'ITC2007 UD2: capacity + 5*missing_working_days + 2*isolated_curriculum_lectures + extra_rooms',
            'feasibility': 'valid' if not errors else 'invalid', 'hard_error_count': len(errors), 'errors': errors[:20],
            'soft_components': {'capacity': capacity, 'minimum_working_days': min_days, 'compactness': compactness, 'room_stability': stability},
            'objective_value': capacity + min_days + compactness + stability if not errors else None,
            'bound': 'feasible upper bound on minimum cost' if not errors else None,
            'optimality': 'not proved by this check', 'runtime': 'not measured; saved solution validated only'}


if __name__ == '__main__':
    rows = [validate(REPO / f'datasets/comp{i:02}.ctt', REPO / f'results/races/comp{i:02}.ctt.sol') for i in range(1, 8)]
    out = ROOT / 'test-cohort/output/validated-timetables.json'
    out.write_text(json.dumps(rows, indent=2))
    print(json.dumps([{k: r[k] for k in ('instance', 'feasibility', 'objective_value')} for r in rows], indent=2))
