"""Isolated evaluation workers so cancellation can interrupt blocking I/O safely."""
from __future__ import annotations

import multiprocessing
import os
import signal

from argus.models import FinalEvaluation
from argus.pipeline import Evaluation


class EvaluationCancelled(Exception):
    pass


def _isolate():
    if os.name == 'posix':
        os.setsid()  # Git children belong to this worker's group, never the API's.
        signal.signal(signal.SIGTERM, lambda *_: os.killpg(os.getpid(), signal.SIGKILL))


def _evaluate(connection, url, cfg):
    _isolate()
    try:
        result = Evaluation(url, cfg, None, lambda message: connection.send(('progress', message))).run()
        connection.send(('result', result.model_dump(mode='json')))
    except Exception:
        connection.send(('error', None))
    finally:
        connection.close()


def _terminate(process):
    if process.pid and os.name == 'posix':
        try:
            if os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGKILL)
            elif process.is_alive():
                process.kill()
        except ProcessLookupError:
            pass
    elif process.is_alive():
        process.kill()
    process.join(timeout=5)


def _run_worker(target, arguments, progress, cancel):
    """Spawn rather than fork the threaded API. Only the parent writes final reports."""
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=target, args=(sender, *arguments), daemon=True)
    process.start()
    sender.close()
    try:
        while True:
            if cancel.is_set():
                raise EvaluationCancelled()
            if receiver.poll(.1):
                try:
                    kind, payload = receiver.recv()
                except EOFError:
                    raise RuntimeError('Evaluation worker exited without a result.') from None
                if kind == 'progress':
                    progress(payload)
                elif kind == 'result':
                    return payload
                else:
                    raise RuntimeError('Evaluation worker failed.')
            elif not process.is_alive():
                raise RuntimeError('Evaluation worker exited without a result.')
    finally:
        _terminate(process)
        receiver.close()


def run_evaluation(url, cfg, progress, cancel):
    return FinalEvaluation.model_validate(_run_worker(_evaluate, (url, cfg), progress, cancel))


def _compare(connection, repositories, threshold):
    _isolate()
    try:
        from argus.cohort import cross_validate
        connection.send(('result', cross_validate(repositories, threshold)))
    except Exception:
        connection.send(('error', None))
    finally:
        connection.close()


def run_comparison(repositories, threshold, cancel):
    return _run_worker(_compare, (repositories, threshold), lambda message: None, cancel)
