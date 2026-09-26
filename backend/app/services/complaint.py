"""投诉处理业务规则：期限判定、状态流转、必填校验与编号合并统一走 complaint_rules。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.services.complaint_rules import (
    BUSINESS_FIELDS,
    CREATE_REQUIRED_FIELDS,
    NUMBER_FIELD,
    STATUS_ORDER,
    STATUS_PENDING,
    apply_action,
    available_actions,
    is_overdue,
    merge_into,
)
from app.store import store

MODULE = "complaint"
REQUIRED_FIELDS = CREATE_REQUIRED_FIELDS
# 兼容既有常量取值，状态序列仍只从共用口径取
STATUS_ACTIONS_LIST = STATUS_ORDER
NEGATIVE_ACTIONS: list[str] = []


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

    def find_by_number(self, complaint_number: str) -> dict[str, Any] | None:
        """按投诉编号定位现有记录，供重复受理时合并。"""
        number = complaint_number.strip()
        for row in store.rows(MODULE):
            if str(row.get(NUMBER_FIELD) or "").strip() == number:
                return row
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing

        rows = store.rows(MODULE)
        number = str(values.get(NUMBER_FIELD)).strip()
        existing = self.find_by_number(number)
        if existing is not None:
            # 投诉编号重复不再另起记录：合并空缺字段，原状态、回复内容与关闭时间全部保留
            merge_into(existing, values)
            return existing, []

        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry[NUMBER_FIELD] = number
        for field in BUSINESS_FIELDS:
            text = str(values.get(field) or "").strip()
            if text:
                entry[field] = text
        entry["status"] = STATUS_PENDING
        entry["pending"] = True
        entry["abnormal"] = is_overdue(entry)
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
        *,
        now: datetime | date | str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"投诉记录 {entry_id} 不存在或已归档"
        error = apply_action(entry, action, values, now=now)
        if error is not None:
            return None, error
        return entry, f"投诉记录已{action}"

    def actions_for(self, entry: dict[str, Any]) -> list[str]:
        """暴露共用的可执行动作口径，供各入口保持一致。"""
        return available_actions(entry)
