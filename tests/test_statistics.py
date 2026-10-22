from argus.statistics import cohort_statistics, report_statistics


def report(**updates):
    return {'evaluation_id': 'test', 'completion_status': 'INCOMPLETE_EVALUATION',
        'repository': {'acquisition': {'success': True}},
        'deterministic_metrics': {'scc': {'meaningful_source_loc_estimate': 120}, 'commits': {'total': 3}},
        'coverage': [{'status': 'PASS'}, {'status': 'FAIL'}, {'status': 'UNVERIFIABLE'}, {'status': 'NOT_APPLICABLE'}],
        'findings': [{'severity': 'HIGH'}, {'severity': 'LOW'}], 'errors': [{}],
        'definition_of_done': {'counts': {'integrity_flags': 0}}, **updates}


def test_real_measurements_and_unavailable_are_distinct():
    row = report_statistics(report())
    assert row['source_loc'] == 120 and row['commits'] == 3
    assert row['checks_passed_pct'] == 33.33 and row['incomplete']
    assert row['findings'] == 2 and row['severity'] == {'HIGH': 1, 'LOW': 1}
    assert row['evaluator_errors'] == 1 and not row['flagged']
    failed = report_statistics(report(repository={'acquisition': {'success': False}}, coverage=[]))
    assert failed['source_loc'] is None and failed['commits'] is None and failed['checks_passed_pct'] is None


def test_flags_are_excluded_from_primary_even_when_status_incomplete():
    clean = report_statistics(report()) | {'repository': 'owner/clean', 'available': True}
    flagged = report_statistics(report(definition_of_done={'counts': {'integrity_flags': 1}})) | {'repository': 'owner/flagged', 'available': True}
    missing = {'repository': 'owner/failed', 'available': False, 'state': 'failed'}
    data = cohort_statistics([clean, flagged, missing])
    primary, all_rows = data['populations']
    assert [r['repository'] for r in primary['rows']] == ['owner/clean']
    assert primary['excluded'] == 2 and all_rows['excluded'] == 1
    assert all_rows['distributions']['source_loc']['max_x'] == primary['distributions']['source_loc']['max_x']
    assert all_rows['distributions']['source_loc']['normal_fit'] == []


def test_normal_fit_statistics_and_missing_measurements():
    rows = [report_statistics(report()) | {'repository': str(i), 'available': True, 'commits': i} for i in [0, 10, 20]]
    rows.append(report_statistics(report()) | {'repository': 'unknown', 'available': True, 'commits': None})
    dist = cohort_statistics(rows)['populations'][0]['distributions']['commits']
    assert dist['n'] == 3 and dist['missing'] == 1
    assert dist['mean'] == dist['median'] == dist['std_dev'] == 10
    assert len(dist['normal_fit']) == 101 and sum(dist['bins']) == 3
    assert dist['bins'][0] == dist['bins'][5] == dist['bins'][9] == 1
    assert cohort_statistics([])['populations'][0]['distributions']['commits']['mean'] is None
