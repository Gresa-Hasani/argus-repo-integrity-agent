import os
import threading
import time
from pathlib import Path

import pytest

from argus import server
from argus.worker import EvaluationCancelled, _run_worker, run_evaluation
from argus.config import Config
from fastapi.testclient import TestClient


def _blocking_worker(connection, marker):
    if os.name == 'posix':
        os.setsid()
    Path(marker).write_text(str(os.getpid()))
    time.sleep(60)


def test_cancellation_terminates_blocking_worker(tmp_path):
    cancel = threading.Event()
    marker = tmp_path / 'worker-pid'
    errors = []
    def run():
        try:
            _run_worker(_blocking_worker, (str(marker),), lambda message: None, cancel)
        except EvaluationCancelled:
            errors.append('cancelled')
    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(.02)
    assert marker.exists()
    pid = int(marker.read_text())
    cancel.set()
    thread.join(5)
    assert not thread.is_alive() and errors == ['cancelled']
    if os.name == 'posix':
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_real_spawned_worker_produces_valid_report(clean_repo, tmp_path):
    messages = []
    cfg = Config(llm_enabled=False, github_api=False, work_dir=str(tmp_path / 'work'))
    result = run_evaluation(str(clean_repo), cfg, messages.append, threading.Event())
    assert result.repository['acquisition']['success']
    assert not result.errors and messages


def test_stop_batch_preserves_completed_and_cancels_queue(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    server._jobs.clear(); server._batches.clear()
    active = threading.Event()
    calls = []
    def run(job_id, url, deterministic_only):
        job = server._jobs[job_id]
        calls.append(url)
        if len(calls) == 1:
            job.update(state='done', evaluation_id='completed-report', finished=time.time())
            return
        active.set()
        assert job['cancel'].wait(5)
        job.update(state='cancelled', finished=time.time())
    monkeypatch.setattr(server, '_run', run)
    api = TestClient(server.create_app({}))
    response = api.post('/api/batches', json={'urls':[f'https://github.com/owner/repo{i}' for i in range(3)], 'deterministic_only': True})
    batch_id = response.json()['batch_id']
    assert active.wait(5)
    assert api.post(f'/api/batches/{batch_id}/stop').json()['state'] == 'stopping'
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = api.get(f'/api/batches/{batch_id}').json()
        if value['state'] == 'cancelled':
            break
        time.sleep(.02)
    assert value['state'] == 'cancelled' and value['cancelled'] == 2
    assert value['items'][0]['evaluation_id'] == 'completed-report'
    assert value['items'][0]['state'] == 'done' and len(calls) == 2
    assert server.active_jobs() == 0
    server._jobs.clear(); server._batches.clear()
    assert api.get(f'/api/batches/{batch_id}').json()['state'] == 'cancelled'
    assert api.post(f'/api/batches/{batch_id}/stop').json()['state'] == 'cancelled'
    assert api.post('/api/batches/000000000000/stop').status_code == 404
