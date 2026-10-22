import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import argus.server as server


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    server._jobs.clear()
    server._batches.clear()
    monkeypatch.setattr(server, 'llm_ready', lambda *args: False)
    yield TestClient(server.create_app({}))
    server._jobs.clear()
    server._batches.clear()


def wait_batch(api, batch_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = api.get(f'/api/batches/{batch_id}').json()
        if value['state'] in {'done', 'done_with_errors'}:
            return value
        time.sleep(.01)
    pytest.fail('batch did not finish')


def test_batch_runs_serially_deduplicates_and_preserves_reports(api, monkeypatch):
    calls, concurrent = [], []
    count = 0

    def run(job_id, url, deterministic_only):
        nonlocal count
        count += 1
        concurrent.append(count)
        calls.append(url)
        time.sleep(.01)
        server._jobs[job_id].update(state='done', finished=time.time(), evaluation_id='report-' + job_id,
                                    completion_status='INCOMPLETE_EVALUATION')
        count -= 1

    monkeypatch.setattr(server, '_run', run)
    response = api.post('/api/batches', json={'urls': ['https://github.com/owner/one.git', 'https://github.com/OWNER/ONE/', 'https://github.com/owner/two'], 'deterministic_only': True})
    assert response.status_code == 200
    value = wait_batch(api, response.json()['batch_id'])
    assert calls == ['https://github.com/owner/one', 'https://github.com/owner/two']
    assert max(concurrent) == 1
    assert value['total'] == value['completed'] == 2
    assert value['failed'] == 0
    assert all(row['evaluation_id'] and row['completion_status'] == 'INCOMPLETE_EVALUATION' for row in value['items'])
    assert len(value['cross_validation']) == 1
    assert value['cross_validation'][0]['status'] == 'unavailable'  # mocked runs produced no clone
    assert 'work_dir' not in str(value) and 'local_path' not in str(value)
    server._batches.clear()
    server._jobs.clear()
    assert api.get(f"/api/batches/{value['batch_id']}").json() == value  # persisted summary survives restart


@pytest.mark.parametrize('urls', [[], ['https://github.com/owner/ok', '/etc'], ['https://github.com/owner/..'], ['https://github.com/owner/repo'] * 51])
def test_entire_batch_is_validated_before_any_job_starts(api, urls, monkeypatch):
    started = []
    monkeypatch.setattr(server, '_run_batch', lambda *args: started.append(args))
    assert api.post('/api/batches', json={'urls': urls}).status_code == 422
    assert not started and not server._jobs and not server._batches


def test_failed_repository_does_not_abort_following_jobs(api, monkeypatch):
    calls = []

    def run(job_id, url, deterministic_only):
        calls.append(url)
        if url.endswith('/bad'):
            raise RuntimeError('internal failure must not leak')
        server._jobs[job_id].update(state='done', finished=time.time(), evaluation_id='saved')

    monkeypatch.setattr(server, '_run', run)
    response = api.post('/api/batches', json={'urls': ['https://github.com/owner/bad', 'https://github.com/owner/good']})
    value = wait_batch(api, response.json()['batch_id'])
    assert len(calls) == 2 and value['state'] == 'done_with_errors' and value['failed'] == 1
    assert value['items'][0]['error'] == server.PUBLIC_FAILURE
    assert value['items'][1]['evaluation_id'] == 'saved'


def test_batch_reserves_capacity_while_other_repositories_are_queued(api, monkeypatch):
    release = threading.Event()

    def run(job_id, url, deterministic_only):
        release.wait(3)
        server._jobs[job_id].update(state='done', finished=time.time())

    monkeypatch.setattr(server, '_run', run)
    response = api.post('/api/batches', json={'urls': ['https://github.com/owner/one', 'https://github.com/owner/two']})
    try:
        assert api.get('/ready').json()['accepting_evaluations'] is False
        assert api.post('/api/evaluate', json={'url': 'https://github.com/owner/three'}).status_code == 429
        assert api.post('/api/batches', json={'urls': ['https://github.com/owner/three']}).status_code == 429
    finally:
        release.set()
    wait_batch(api, response.json()['batch_id'])
    assert api.get('/ready').json()['accepting_evaluations'] is True


def test_search_filters_private_and_non_github_results(api, monkeypatch):
    captured = []

    def fetch(path, token):
        captured.append(path)
        return {'items': [
            {'private': False, 'html_url': 'https://github.com/owner/public', 'description': 'Solver', 'stargazers_count': 3},
            {'private': True, 'html_url': 'https://github.com/owner/private'},
            {'private': False, 'html_url': 'https://evil.example/owner/repo'},
            {'private': False, 'archived': True, 'html_url': 'https://github.com/owner/archived'},
        ]}

    monkeypatch.setattr(server, 'github_get', fetch)
    rows = api.get('/api/repositories/search', params={'q': 'graph coloring'}).json()
    assert [row['url'] for row in rows] == ['https://github.com/owner/public']
    assert 'is%3Apublic' in captured[0] and 'per_page=8' in captured[0]


def test_search_failure_offers_paste_and_test_repositories(api, monkeypatch):
    def fail(*args):
        raise OSError('/home/private-path')
    monkeypatch.setattr(server, 'github_get', fail)
    response = api.get('/api/repositories/search', params={'q': 'timetabling'})
    assert response.status_code == 503
    assert 'private-path' not in response.text
    assert 'public test repositories' in response.json()['detail']


def test_missing_batch_and_path_traversal_are_not_file_lookups(api):
    assert api.get('/api/batches/not-a-batch').status_code == 404
    assert api.get('/api/batches/..%2F..%2Fetc').status_code == 404


def test_provider_selection_requires_backend_key_and_queues_selected_provider(api, monkeypatch):
    for key in ('OPENAI_API_KEY', 'ARGUS_LLM_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    options = api.get('/api/providers').json()
    option = next(p for p in options if p['id'] == 'openai')
    assert option['configured'] is False and option['model'] == 'gpt-4.1-mini'
    request = {'urls': ['https://github.com/owner/one'], 'provider': 'openai'}
    assert api.post('/api/batches', json=request).status_code == 422
    assert not server._jobs
    monkeypatch.setenv('OPENAI_API_KEY', 'must-never-be-public')
    monkeypatch.setenv('ARGUS_OPENAI_MODEL', 'chosen-openai-model')
    monkeypatch.setattr(server, '_run_batch', lambda *a: None)
    value = api.post('/api/batches', json=request).json()
    assert value['model'] == 'chosen-openai-model'
    assert all(job['provider'] == 'openai' for job in server._jobs.values())
    assert server.evaluation_config('openai').llm_provider == 'openai'
    assert 'must-never-be-public' not in str(api.get('/api/providers').json()) + str(value)
    assert api.post('/api/batches', json={**request, 'provider': 'unknown'}).status_code == 422


def test_batch_statistics_reads_actual_reports_and_retains_failed_rows(api, monkeypatch):
    from types import SimpleNamespace
    from test_statistics import report
    report_data = report()
    batch = {'batch_id': 'abcdef123456', 'state': 'done_with_errors', 'items': [
        {'repository': 'owner/one', 'state': 'done', 'evaluation_id': 'test'},
        {'repository': 'owner/missing', 'state': 'failed', 'evaluation_id': None}]}
    import json
    Path('argus-reports').mkdir()
    Path('argus-reports/batch-abcdef123456.json').write_text(json.dumps(batch))
    monkeypatch.setattr(server, '_saved', lambda: {'test': {'result': SimpleNamespace(model_dump=lambda **kw: report_data)}})
    response = api.get('/api/batches/abcdef123456/statistics')
    assert response.status_code == 200
    data = response.json()
    assert data['rows'][0]['source_loc'] == 120
    assert data['rows'][1]['available'] is False and 'findings' not in data['rows'][1]
    assert data['populations'][0]['excluded'] == 1
    assert api.get('/api/batches/000000000000/statistics').status_code == 404


def test_saved_batch_picker_ignores_invalid_files(api):
    import json
    directory = Path('argus-reports')
    directory.mkdir()
    directory.joinpath('batch-abcdef123456.json').write_text(json.dumps({'batch_id': 'abcdef123456', 'state': 'done', 'total': 4, 'completed': 4, 'model': 'test', 'private': 'do-not-serve'}))
    directory.joinpath('batch-111111111111.json').write_text('{invalid')
    directory.joinpath('batch-222222222222.json').write_text(json.dumps({'batch_id': 'wrong', 'state': 'done'}))
    rows = api.get('/api/batches').json()
    assert rows == [{'batch_id': 'abcdef123456', 'state': 'done', 'model': 'test', 'total': 4, 'completed': 4}]


def test_real_batch_comparison_flags_both_copied_repositories(api, monkeypatch, clean_repo):
    import shutil
    def acquire(job_id, url, deterministic_only):
        job = server._jobs[job_id]
        target = Path(job['work_dir']) / 'target'
        shutil.copytree(clean_repo, target)
        job.update(acquired=True, state='done', finished=time.time())
    monkeypatch.setattr(server, '_run', acquire)
    response = api.post('/api/batches', json={'urls': ['https://github.com/fixture/original', 'https://github.com/fixture/copy'], 'deterministic_only': True})
    value = wait_batch(api, response.json()['batch_id'])
    assert value['cross_validation'][0]['code_a_in_b'] == value['cross_validation'][0]['code_b_in_a'] == 1
    assert value['cross_validation'][0]['flagged']
    assert all(item['similarity_flagged'] for item in value['items'])
    server._batches.clear()
    server._jobs.clear()
    saved = api.get(f"/api/batches/{value['batch_id']}").json()
    assert all(item['similarity_flagged'] for item in saved['items'])
