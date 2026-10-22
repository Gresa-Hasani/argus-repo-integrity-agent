from pathlib import Path

import pytest

from argus.cohort import cross_validate, grade_populations


def test_only_verified_grades_and_known_flags_enter_populations():
    rows = [
        {"score": 70, "grade_verified": True, "flagged": False},
        {"score": 90, "grade_verified": True, "flagged": True},
        {"score": 80, "grade_verified": True, "flagged": None},
        {"score": 60, "grade_verified": False, "flagged": False},
        {"score": float('nan'), "grade_verified": True, "flagged": False},
    ]
    p = grade_populations(rows)
    assert p['without_flagged'] == rows[:1]
    assert p['with_flagged'] == rows[:2]


def test_without_flags_only_primary_population():
    assert list(grade_populations([{"score": 80, "grade_verified": True, "flagged": False}])) == ['without_flagged']
    assert grade_populations([]) == {'without_flagged': []}


def test_every_pair_and_unavailable_is_not_zero(clean_repo):
    repos = [
        {"slug": 'a', "acquisition_status": 'available', "local_path": str(clean_repo)},
        {"slug": 'b', "acquisition_status": 'available', "local_path": str(clean_repo)},
        {"slug": 'c', "acquisition_status": 'unavailable'},
    ]
    pairs = cross_validate(repos)
    assert len(pairs) == 3
    assert pairs[0]['code_a_in_b'] == 1
    assert pairs[0]['readme_text_similarity'] == 1
    assert all(p['readme_structure_advisory_only'] for p in pairs)
    assert pairs[1]['code_a_in_b'] is None
    assert pairs[1]['status'] == 'unavailable'


def test_duplicate_slugs_rejected():
    with pytest.raises(ValueError):
        cross_validate([{"slug": 'same'}, {"slug": 'same'}])


def test_plot_exports_both_flag_populations(tmp_path):
    pytest.importorskip('matplotlib')
    from argus.cohort import plot_grades
    rows = [{"score": 70, "grade_verified": True, "flagged": False},
            {"score": 90, "grade_verified": True, "flagged": True}]
    files = plot_grades(rows, tmp_path, title='Synthetic fixture')
    assert {p.name for p in files} == {'grades-without_flagged.png', 'grades-without_flagged.svg', 'grades-with_flagged.png', 'grades-with_flagged.svg'}
    assert all(p.stat().st_size > 100 for p in files)


@pytest.mark.parametrize('scores', [[], [80], [80, 80]])
def test_plot_handles_empty_small_and_constant_populations(tmp_path, scores):
    pytest.importorskip('matplotlib')
    from argus.cohort import plot_grades
    rows = [{"score": s, "grade_verified": True, "flagged": False} for s in scores]
    assert len(plot_grades(rows, tmp_path, title='Synthetic fixture')) == 2


def test_two_independent_git_repositories_with_copied_source_are_flagged(tmp_path):
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location('copied_fixture', Path(__file__).parents[1] / 'scripts/test_copied_repos.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    summary = fixture.run_fixture(tmp_path / 'reports')
    pair = summary['cross_validation'][0]
    assert pair['flagged'] and pair['flag_reason'] == 'CODE_OVERLAP_REVIEW_REQUIRED'
    assert pair['code_a_in_b'] == pair['code_b_in_a'] == 1.0
    assert pair['matched_files_a'][0]['file'] == 'coloring.py'
    assert pair['matched_files_a'][0]['best_match'] == 'coloring.py'
    assert pair['matched_files_a'][0]['containment'] == 1.0
    for row in summary['rows']:
        report = next(json.loads(p.read_text()) for p in (tmp_path / 'reports').glob('*.json') if p.name not in {'copied-fixture-summary.json', 'batch-c0c0c0c0c0c0.json'} and json.loads(p.read_text()).get('evaluation_id') == row['evaluation_id'])
        findings = [f for f in report['findings'] if f['title'] == 'SIMILARITY_THRESHOLD_EXCEEDED']
        assert findings and findings[0]['requires_manual_review']
        assert report['definition_of_done']['counts']['integrity_flags'] > 0
    assert summary['populations'][0]['rows'] == []
    assert len(summary['populations'][1]['rows']) == 2


def test_matching_readmes_without_matching_source_do_not_flag(tmp_path):
    from conftest import RepoBuilder
    first = RepoBuilder(tmp_path / 'first')
    second = RepoBuilder(tmp_path / 'second')
    first.commit('Add mathematical routines', {'README.md': '# Assignment\n## Setup\nSame starter README.\n',
        'math.py': 'def factorial(number):\n    accumulator = 1\n    for factor in range(2, number + 1):\n        accumulator *= factor\n    return accumulator\n'})
    second.commit('Add string parser', {'README.md': '# Assignment\n## Setup\nSame starter README.\n',
        'parser.py': 'import re\nclass Tokenizer:\n    def split(self, content):\n        result = re.findall(r"[a-z]+", content.lower())\n        unique = dict.fromkeys(result)\n        return sorted(unique.keys())\n'})
    pair = cross_validate([{'slug': p.name, 'local_path': str(p), 'acquisition_status': 'available'} for p in [first.path, second.path]])[0]
    assert pair['readme_text_similarity'] == pair['readme_heading_similarity'] == 1
    assert not pair['flagged'] and pair['flag_reason'] is None
