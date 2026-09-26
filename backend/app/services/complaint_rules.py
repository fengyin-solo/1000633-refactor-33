"""投诉处理共用规则。

受理、回复、关闭以及重复投诉编号合并都通过这里的规则执行，避免处理期限、
必填字段和状态流转在不同入口出现不同口径。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable, Iterable

STATUS_PENDING = "待受理"
STATUS_PROCESSING = "处理中"
STATUS_REPLIED = "已回复"
STATUS_CLOSED = "已关闭"
STATUS_ORDER = [STATUS_PENDING, STATUS_PROCESSING, STATUS_REPLIED, STATUS_CLOSED]

ACTION_ACCEPT = "受理投诉"
ACTION_REPLY = "提交回复"
ACTION_CLOSE = "关闭投诉"
ACTION_TARGETS = {
    ACTION_ACCEPT: STATUS_PROCESSING,
    ACTION_REPLY: STATUS_REPLIED,
    ACTION_CLOSE: STATUS_CLOSED,
}
ACTION_SOURCE_STATUSES = {
    ACTION_ACCEPT: {STATUS_PENDING},
    ACTION_REPLY: {STATUS_PROCESSING},
    ACTION_CLOSE: {STATUS_REPLIED},
}
ACTION_REQUIRED_FIELDS = {
    ACTION_ACCEPT: ["投诉事由"],
    ACTION_REPLY: ["处理措施"],
    ACTION_CLOSE: [],
}

CREATE_REQUIRED_FIELDS = ["投诉编号", "投诉单位", "投诉事由"]
CREATE_DETAIL_FIELDS = [
    "涉及样品",
    "受理人员",
    "处理措施",
    "处理期限",
]
DETAIL_FIELDS = [
    "投诉单位",
    "投诉事由",
    *CREATE_DETAIL_FIELDS,
]
REPLY_FIELDS = ["处理措施", "处理期限", "回复内容"]
NUMBER_FIELD = "投诉编号"
DEADLINE_FIELD = "处理期限"
REPLY_FIELD = "回复内容"
CLOSED_AT_FIELD = "关闭时间"


def normalised(value: Any) -> str:
    """统一空值与空白字段的判定口径。"""
    return str(value or "").strip()


def is_blank(value: Any) -> bool:
    return normalised(value) == ""


def parse_date(value: Any) -> date | None:
    """解析 YYYY-MM-DD；处理期限为空或无法解析时不参与超期判定。"""
    text = normalised(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def is_overdue(entry: dict[str, Any], *, today: date | None = None) -> bool:
    deadline = parse_date(entry.get(DEADLINE_FIELD))
    if deadline is None:
        return False
    return (today or date.today()) > deadline


def available_actions(entry: dict[str, Any]) -> list[str]:
    """按投诉当前状态返回可执行动作；超期只标识异常，不阻断回复。"""
    current = entry.get("status")
    return [
        action
        for action in ACTION_TARGETS
        if current in ACTION_SOURCE_STATUSES[action]
    ]


def missing_required(values: dict[str, Any], fields: Iterable[str]) -> list[str]:
    return [field for field in fields if is_blank(values.get(field))]


def apply_supplied_fields(
    target: dict[str, Any],
    values: dict[str, Any],
    fields: Iterable[str],
    *,
    overwrite: bool = False,
) -> None:
    """把非空字段写回记录；默认只补齐空值，避免覆盖已有回复等内容。"""
    for field in fields:
        if field not in values:
            continue
        value = values.get(field)
        if is_blank(value):
            continue
        if overwrite or is_blank(target.get(field)):
            target[field] = value


def apply_action(
    entry: dict[str, Any],
    action: str,
    values: dict[str, Any] | None = None,
    *,
    today: date | None = None,
    now: Callable[[], date] | None = None,
) -> str | None:
    """执行一次投诉动作。

    成功时写入状态并返回 None；失败时返回中文原因，不改动记录。三个动作共用
    状态来源、必填字段、处理期限和已有回复/关闭时间保护规则。
    """
    payload = values or {}
    if action not in ACTION_TARGETS:
        return f"动作「{action}」不属于投诉处理可执行范围"

    current = entry.get("status")
    if action not in available_actions(entry):
        if current not in STATUS_ORDER:
            return f"当前状态「{current}」不在允许的状态序列里"
        return f"当前状态「{current}」不允许执行动作「{action}」"

    required_fields = ACTION_REQUIRED_FIELDS[action]
    missing = [
        field
        for field in required_fields
        if is_blank(payload.get(field)) and is_blank(entry.get(field))
    ]
    if missing:
        return f"缺少必填字段：{'、'.join(missing)}"

    if action == ACTION_CLOSE and not is_blank(entry.get(CLOSED_AT_FIELD)):
        return "投诉已关闭，不能重复关闭"

    if action == ACTION_ACCEPT:
        apply_supplied_fields(entry, payload, DETAIL_FIELDS)
    elif action == ACTION_REPLY:
        apply_supplied_fields(entry, payload, REPLY_FIELDS)
        reply_text = payload.get(REPLY_FIELD)
        if is_blank(reply_text):
            reply_text = payload.get("处理措施")
        if is_blank(entry.get(REPLY_FIELD)) and not is_blank(reply_text):
            entry[REPLY_FIELD] = normalised(reply_text)
    else:
        current_closed_at = normalised(entry.get(CLOSED_AT_FIELD))
        entry[CLOSED_AT_FIELD] = current_closed_at or (now or date.today)().isoformat()

    entry["status"] = ACTION_TARGETS[action]
    entry["投诉状态"] = entry["status"]
    entry["pending"] = entry["status"] != STATUS_CLOSED
    entry["abnormal"] = is_overdue(entry, today=today)
    return None
