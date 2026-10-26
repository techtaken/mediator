"""In-memory stand-in for the subset of the supabase-py query builder we use.

Filters are applied for real, so tests can exercise conditional updates
(optimistic locking, atomic status claims) rather than canned return values.
"""

from __future__ import annotations

import copy
import itertools
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class Result:
    data: list[dict[str, Any]]


class FakeQuery:
    def __init__(self, db: "FakeSupabase", table: str):
        self.db = db
        self.table_name = table
        self.op = "select"
        self.payload: Any = None
        self.filters: list[tuple[str, Any]] = []
        self.limit_n: int | None = None
        self.order_by: str | None = None
        self.on_conflict: str | None = None

    # builder ---------------------------------------------------------------
    def select(self, *_cols: str) -> "FakeQuery":
        self.op = "select"
        return self

    def insert(self, payload: Any) -> "FakeQuery":
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload: dict[str, Any]) -> "FakeQuery":
        self.op, self.payload = "update", payload
        return self

    def upsert(self, payload: dict[str, Any], on_conflict: str = "id") -> "FakeQuery":
        self.op, self.payload, self.on_conflict = "upsert", payload, on_conflict
        return self

    def eq(self, column: str, value: Any) -> "FakeQuery":
        self.filters.append((column, value))
        return self

    def limit(self, n: int) -> "FakeQuery":
        self.limit_n = n
        return self

    def order(self, column: str) -> "FakeQuery":
        self.order_by = column
        return self

    # execution -------------------------------------------------------------
    def _match(self, row: dict[str, Any]) -> bool:
        return all(row.get(column) == value for column, value in self.filters)

    def execute(self) -> Result:
        failure = self.db.failures.get((self.table_name, self.op))
        if failure:
            raise failure
        rows = self.db.tables.setdefault(self.table_name, [])
        if self.op == "select":
            found = [copy.deepcopy(row) for row in rows if self._match(row)]
            if self.order_by:
                found.sort(key=lambda row: row.get(self.order_by) or "")
            if self.limit_n is not None:
                found = found[: self.limit_n]
            return Result(found)
        if self.op == "insert":
            payloads = self.payload if isinstance(self.payload, list) else [self.payload]
            inserted = [self.db._new_row(self.table_name, dict(item)) for item in payloads]
            rows.extend(inserted)
            return Result(copy.deepcopy(inserted))
        if self.op == "update":
            changed = []
            for row in rows:
                if self._match(row):
                    row.update(copy.deepcopy(self.payload))
                    changed.append(copy.deepcopy(row))
            return Result(changed)
        if self.op == "upsert":
            keys = [key.strip() for key in (self.on_conflict or "id").split(",")]
            for row in rows:
                if all(row.get(key) == self.payload.get(key) for key in keys):
                    row.update(copy.deepcopy(self.payload))
                    return Result([copy.deepcopy(row)])
            new = self.db._new_row(self.table_name, dict(self.payload))
            rows.append(new)
            return Result([copy.deepcopy(new)])
        raise AssertionError(self.op)


class FakeSupabase:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.failures: dict[tuple[str, str], Exception] = {}
        self._clock = itertools.count(1)

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    def _new_row(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("created_at", f"2026-06-01T00:00:{next(self._clock):06d}Z")
        if table == "sessions":
            row.setdefault("status", "intake")
            row.setdefault("user_a_ready", False)
            row.setdefault("user_b_ready", False)
            row.setdefault("invite_token_b", "token_xyz")
            row.setdefault("state_version", 0)
            row.setdefault("mediation_state", {})
            row.setdefault("halted_for", None)
            row.setdefault("halt_kind", None)
            row.setdefault("halted_reason", None)
        if table == "messages":
            row.setdefault("is_private", True)
        return row

    def rows(self, table: str, **filters: Any) -> list[dict[str, Any]]:
        return [row for row in self.tables.get(table, []) if all(row.get(k) == v for k, v in filters.items())]

    def add_session(self, **overrides: Any) -> dict[str, Any]:
        row = self._new_row("sessions", {"id": "sess_abc", "created_by": "user_123", **overrides})
        self.tables.setdefault("sessions", []).append(row)
        return row
