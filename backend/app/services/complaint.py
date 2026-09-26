"""投诉处理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.complaint_rules import (
    ACTION_TARGETS,
    CREATE_DETAIL_FIELDS,
    CREATE_REQUIRED_FIELDS,
    DETAIL_FIELDS,
    NUMBER_FIELD,
    STATUS_ORDER,
    STATUS_PENDING,
    apply_action,
    apply_supplied_fields,
    missing_required,
    normalised,
)
from app.store import store

MODULE = "complaint"
REQUIRED_FIELDS = CREATE_REQUIRED_FIELDS
ACTION_RULES = ACTION_TARGETS


class ComplaintService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(NUMBER_FIELD, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def _find_by_number(self, complaint_number: str) -> dict[str, Any] | None:
        target = normalised(complaint_number)
        for row in store.rows(MODULE):
            if normalised(row.get(NUMBER_FIELD)) == target:
                return row
        return None

    def create_entry(
        self,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[str], bool]:
        missing = missing_required(values, REQUIRED_FIELDS)
        existing = self._find_by_number(values.get(NUMBER_FIELD, ""))
        if existing is not None:
            apply_supplied_fields(existing, values, DETAIL_FIELDS)
            remaining = missing_required(existing, REQUIRED_FIELDS)
            if remaining:
                return None, remaining, True
            return existing, [], True

        if missing:
            return None, missing, False

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry[NUMBER_FIELD] = values.get(NUMBER_FIELD)
        apply_supplied_fields(entry, values, REQUIRED_FIELDS[1:] + CREATE_DETAIL_FIELDS)
        entry["status"] = STATUS_PENDING
        entry["投诉状态"] = STATUS_PENDING
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, [], False

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"投诉记录 {entry_id} 不存在或已归档"

        error = apply_action(entry, action, values)
        if error is not None:
            return None, error
        return entry, f"投诉记录已{action}"
