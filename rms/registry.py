from __future__ import annotations

import threading
from copy import deepcopy


class RuntimeRegistry:

    def __init__(self):
        self._lock = threading.RLock()
        self._runtimes: dict[str, dict] = {}

    def update(self, snapshot: dict) -> None:
        runtime_instance_id = snapshot["runtime_instance_id"]

        with self._lock:
            self._runtimes[runtime_instance_id] = deepcopy(snapshot)

    def get(self, runtime_instance_id: str) -> dict | None:
        with self._lock:
            snapshot = self._runtimes.get(runtime_instance_id)
            return deepcopy(snapshot) if snapshot is not None else None

    def list_active(self) -> list[dict]:
        with self._lock:
            return deepcopy(list(self._runtimes.values()))


registry = RuntimeRegistry()


