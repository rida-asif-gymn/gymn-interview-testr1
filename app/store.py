"""In-memory state. One process, one lock: every check-then-write happens while holding it,
so "may not" rules (one member per phone, unique plan id) hold under concurrent requests."""
from __future__ import annotations

import threading
import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.members: dict[str, dict] = {}
        self.member_by_phone: dict[str, str] = {}  # E.164 -> member id
        self.plans: dict[str, dict] = {}
        self.agreements: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}
