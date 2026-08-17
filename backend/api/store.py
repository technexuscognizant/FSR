"""
backend/api/store.py
====================
PHASE 4 — session storage. Owner: Member 3.

Holds the parsed statements between requests so the frontend can upload once
and then call /validate, /analytics and /compare without re-uploading.

WHY IN MEMORY
-------------
A dict in the process, with a TTL. No database, no Redis. For a demo running
on one machine for five days that is the right call — a database here would
be a day of work that no judge will ever see.

The trade-off is real and worth being able to state out loud: restart the
server and every session is gone, and this will not survive more than one
worker process. The fix is to swap this one module for Redis; nothing else
in the codebase would change, because everything goes through these four
functions.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# How long an upload stays usable, and how many we keep at once. Both exist
# so a long demo session cannot slowly eat all the memory on the machine.
SESSION_TTL_SECONDS = 2 * 60 * 60
MAX_SESSIONS = 50

_sessions: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()      # uvicorn can serve requests on several threads


def _now() -> float:
    return time.time()


def _prune_locked() -> None:
    """Drop expired sessions, then the oldest if we are still over the cap."""
    cutoff = _now() - SESSION_TTL_SECONDS
    for session_id in [k for k, v in _sessions.items() if v["created_at"] < cutoff]:
        _sessions.pop(session_id, None)

    if len(_sessions) > MAX_SESSIONS:
        oldest = sorted(_sessions.items(), key=lambda kv: kv[1]["created_at"])
        for session_id, _ in oldest[:len(_sessions) - MAX_SESSIONS]:
            _sessions.pop(session_id, None)


def create(data: Dict[str, Any]) -> str:
    """Store parsed canonical data and return its session id."""
    session_id = uuid.uuid4().hex[:12]
    with _lock:
        _prune_locked()
        _sessions[session_id] = {
            "data": data,
            "created_at": _now(),
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cache": {},        # computed reports, so we do the work once
        }
    return session_id


def get(session_id: str) -> Optional[Dict[str, Any]]:
    """Return the session record, or None if unknown or expired."""
    with _lock:
        _prune_locked()
        return _sessions.get(session_id)


def cached(session_id: str, key: str, producer) -> Any:
    """
    Return a computed report, running `producer` only the first time.

    Validation and analytics are pure functions of the uploaded file, so
    recomputing them on every page view would be wasted work — and during a
    live demo, wasted seconds.
    """
    session = get(session_id)
    if session is None:
        raise KeyError(session_id)
    if key not in session["cache"]:
        session["cache"][key] = producer(session["data"])
    return session["cache"][key]


def delete(session_id: str) -> bool:
    with _lock:
        return _sessions.pop(session_id, None) is not None


def list_all() -> List[Dict[str, Any]]:
    with _lock:
        _prune_locked()
        return [
            {
                "session_id": session_id,
                "company_name": record["data"]["company_name"],
                "source_file": record["data"]["source_file"],
                "uploaded_at": record["uploaded_at"],
            }
            for session_id, record in sorted(
                _sessions.items(), key=lambda kv: kv[1]["created_at"]
            )
        ]


def clear() -> None:
    """Used by the tests so one test cannot leak state into the next."""
    with _lock:
        _sessions.clear()