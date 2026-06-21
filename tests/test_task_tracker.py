import threading
import time

from packages.domain.task_tracker import TaskTracker


def test_submit_passes_task_id_to_accepting_callable() -> None:
    tracker = TaskTracker()
    seen: dict[str, str | None] = {}
    done = threading.Event()

    def run(progress_callback=None, task_id: str | None = None) -> dict:
        seen["task_id"] = task_id
        if progress_callback:
            progress_callback("done", 1, 1)
        done.set()
        return {"task_id": task_id}

    task_id = tracker.submit("wiki", "Wiki", run, total=1)

    assert done.wait(2)
    deadline = time.time() + 2
    result = None
    while time.time() < deadline:
        result = tracker.get_result(task_id)
        if result is not None:
            break
        time.sleep(0.01)

    assert seen["task_id"] == task_id
    assert result == {"task_id": task_id}


def test_submit_does_not_pass_task_id_to_generic_kwargs() -> None:
    tracker = TaskTracker()
    seen: dict[str, object] = {}
    done = threading.Event()

    def run(progress_callback=None, **kwargs) -> dict:
        seen["kwargs"] = kwargs
        done.set()
        return kwargs

    task_id = tracker.submit("wiki", "Wiki", run)

    assert done.wait(2)
    deadline = time.time() + 2
    result = None
    while time.time() < deadline:
        result = tracker.get_result(task_id)
        if result is not None:
            break
        time.sleep(0.01)

    assert seen["kwargs"] == {}
    assert result == {}
