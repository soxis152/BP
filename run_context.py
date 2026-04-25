"""Sdileny runtime run_id pro dlouho bezici procesy.

Main aplikace muze bezet dlouho a mezi jednotlivymi testy nechci restartovat
vsechny threaddy jen kvuli novemu run_id. Proto drzim aktualni run_id v malem
stavovem souboru a procesy ho prubezne nacitaji s levnou cache.
"""

from __future__ import annotations

from pathlib import Path
import threading
import time

try:
    from config import ACTIVE_RUN_ID_FILE, RUN_ID
except ImportError:
    from .config import ACTIVE_RUN_ID_FILE, RUN_ID


RUN_ID_POLL_SECONDS = 0.5
_lock = threading.RLock()
_cached_run_id = None
_cached_mtime_ns = None
_last_poll_monotonic = 0.0


def sanitize_run_id(value: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError("run_id nesmi byt prazdne")
    return cleaned


def _state_path() -> Path:
    return Path(ACTIVE_RUN_ID_FILE).resolve()


def _read_state_file(path: Path) -> str | None:
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8").strip()
    return content or None


def initialize_run_id_file() -> str:
    """Zajisti, ze existuje stavovy soubor s aktivnim run_id."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with _lock:
        current = _read_state_file(path)
        if current is None:
            current = sanitize_run_id(RUN_ID)
            path.write_text(current + "\n", encoding="utf-8")

        stat = path.stat()
        global _cached_run_id, _cached_mtime_ns, _last_poll_monotonic
        _cached_run_id = current
        _cached_mtime_ns = stat.st_mtime_ns
        _last_poll_monotonic = time.monotonic()
        return current


def get_current_run_id() -> str:
    """Vrati aktualni run_id a pri zmene stavoveho souboru ho obnovi."""
    path = _state_path()
    global _cached_run_id, _cached_mtime_ns, _last_poll_monotonic

    with _lock:
        if _cached_run_id is None:
            return initialize_run_id_file()

        now = time.monotonic()
        if now - _last_poll_monotonic < RUN_ID_POLL_SECONDS:
            return _cached_run_id

        _last_poll_monotonic = now
        try:
            stat = path.stat()
        except FileNotFoundError:
            return initialize_run_id_file()

        if _cached_mtime_ns != stat.st_mtime_ns:
            current = _read_state_file(path) or sanitize_run_id(RUN_ID)
            _cached_run_id = current
            _cached_mtime_ns = stat.st_mtime_ns

        return _cached_run_id


def set_current_run_id(new_run_id: str) -> str:
    """Nastavi nove run_id pro vsechny procesy, ktere pouzivaji run_context."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = sanitize_run_id(new_run_id)
    path.write_text(value + "\n", encoding="utf-8")

    stat = path.stat()
    global _cached_run_id, _cached_mtime_ns, _last_poll_monotonic
    with _lock:
        _cached_run_id = value
        _cached_mtime_ns = stat.st_mtime_ns
        _last_poll_monotonic = time.monotonic()
    return value
