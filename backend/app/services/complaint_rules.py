"""投诉处理共用口径：处理期限判定、状态流转、必填校验、编号重复合并都只此一份。

受理投诉、提交回复、关闭投诉三个动作以及投诉登记统一走这里，
保证列表、详情与各动作入口对同一条投诉给出完全一致的可操作范围与校验结果。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

# 动作与状态取值固定，不允许在重构中改名或新增中间态
ACCEPT_ACTION = "受理投诉"
REPLY_ACTION = "提交回复"
CLOSE_ACTION = "关闭投诉"
ACTIONS = [ACCEPT_ACTION, REPLY_ACTION, CLOSE_ACTION]

STATUS_PENDING = "待受理"
STATUS_PROCESSING = "处理中"
STATUS_REPLIED = "已回复"
STATUS_CLOSED = "已关闭"
STATUS_ORDER = [STATUS_PENDING, STATUS_PROCESSING, STATUS_REPLIED, STATUS_CLOSED]

ACTION_TARGET: dict[str, str] = {
    ACCEPT_ACTION: STATUS_PROCESSING,
    REPLY_ACTION: STATUS_REPLIED,
    CLOSE_ACTION: STATUS_CLOSED,
}

# 各动作执行前必须具备的字段：投诉事由、处理措施、回复内容的必填校验统一在此声明
ACTION_REQUIRED_FIELDS: dict[str, list[str]] = {
    ACCEPT_ACTION: ["投诉事由"],
    REPLY_ACTION: ["处理措施", "回复内容"],
    CLOSE_ACTION: ["处理措施"],
}

# 状态 -> 当前可执行动作。按钮可点范围与后端动作校验共用这一份映射
STATUS_ACTIONS: dict[str, list[str]] = {
    STATUS_PENDING: [ACCEPT_ACTION],
    STATUS_PROCESSING: [REPLY_ACTION],
    STATUS_REPLIED: [CLOSE_ACTION],
    STATUS_CLOSED: [],
}

NUMBER_FIELD = "投诉编号"
DEADLINE_FIELD = "处理期限"
REPLY_FIELD = "回复内容"
ACCEPTED_AT_FIELD = "受理时间"
REPLIED_AT_FIELD = "回复时间"
CLOSED_AT_FIELD = "关闭时间"

# 登记/合并时允许写入的业务字段（回复内容与各类时间戳不在此列，只能由对应动作写入）
BUSINESS_FIELDS = ["投诉单位", "投诉事由", "涉及样品", "受理人员", "处理措施", "处理期限"]
CREATE_REQUIRED_FIELDS = [NUMBER_FIELD, "投诉单位", "投诉事由"]


def parse_day(value: Any) -> date | None:
    """把处理期限解析成日期；空值或无法识别的格式一律视为没有设定期限。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def is_overdue(entry: dict[str, Any], today: date | None = None) -> bool:
    """处理期限判定：期限为空不算超期；已关闭不再追算；仅未关闭且已过期限才算超期。

    超期只作为标记，不收回「提交回复」入口——超期后仍要允许回复。
    """
    if entry.get("status") == STATUS_CLOSED:
        return False
    deadline = parse_day(entry.get(DEADLINE_FIELD))
    if deadline is None:
        return False
    return (today or date.today()) > deadline


def available_actions(entry: dict[str, Any]) -> list[str]:
    """按状态给出该投诉当前可执行的动作，任何入口都以此为准。"""
    return list(STATUS_ACTIONS.get(str(entry.get("status") or ""), []))


def missing_fields(
    entry: dict[str, Any], action: str, values: dict[str, Any] | None = None
) -> list[str] | None:
    """返回动作执行前仍缺的必填字段；动作本身不合法时返回 None（由调用方按动作校验拦截）。

    记录里已经有的内容视为已满足，不必在每次动作里重复提交。
    """
    required = ACTION_REQUIRED_FIELDS.get(action)
    if required is None:
        return None
    values = values or {}
    missing: list[str] = []
    for field in required:
        provided = str(values.get(field) or "").strip()
        existed = str(entry.get(field) or "").strip()
        if not provided and not existed:
            missing.append(field)
    return missing


def validate_transition(
    entry: dict[str, Any], action: str, values: dict[str, Any] | None = None
) -> str | None:
    """三个动作共用的前置校验：动作合法 → 状态允许 → 必填齐全；返回 None 表示可执行。"""
    if action not in ACTION_TARGET:
        return f"动作「{action}」不属于投诉处理可执行范围"
    if action not in STATUS_ACTIONS.get(str(entry.get("status") or ""), []):
        return f"投诉当前状态为「{entry.get('status')}」，不能执行「{action}」"
    missing = missing_fields(entry, action, values)
    if missing:
        return f"缺少必填字段：{'、'.join(missing)}"
    return None


def _as_today(now: datetime | date | None) -> date:
    if isinstance(now, datetime):
        return now.date()
    if isinstance(now, date):
        return now
    return date.today()


def _timestamp(now: datetime | date | str | None) -> str:
    if now is None:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(now, datetime):
        return now.strftime("%Y-%m-%d %H:%M:%S")
    return str(now)


def apply_action(
    entry: dict[str, Any],
    action: str,
    values: dict[str, Any] | None = None,
    *,
    now: datetime | date | str | None = None,
) -> str | None:
    """受理投诉、提交回复、关闭投诉的唯一落地点。

    校验通过后统一写入提交字段、推进状态并补登记时间；
    已有回复内容、回复时间与关闭时间一律保留，不会被重复执行覆盖。
    返回 None 表示成功，否则返回可读的错误说明且记录不发生任何改动。
    """
    values = values or {}
    error = validate_transition(entry, action, values)
    if error is not None:
        return error

    for field in BUSINESS_FIELDS:
        text = str(values.get(field) or "").strip()
        if text:
            entry[field] = text

    if action == ACCEPT_ACTION:
        entry.setdefault(ACCEPTED_AT_FIELD, _timestamp(now))
    elif action == REPLY_ACTION:
        content = str(values.get(REPLY_FIELD) or "").strip()
        if content:
            entry[REPLY_FIELD] = content
        entry.setdefault(REPLIED_AT_FIELD, _timestamp(now))
    else:  # CLOSE_ACTION
        entry.setdefault(CLOSED_AT_FIELD, _timestamp(now))

    target = ACTION_TARGET[action]
    entry["status"] = target
    entry["pending"] = target != STATUS_CLOSED
    entry["abnormal"] = is_overdue(entry, today=_as_today(now))
    return None


def merge_into(entry: dict[str, Any], values: dict[str, Any]) -> None:
    """投诉编号重复时的合并逻辑：只补齐空缺业务字段。

    编号、状态、已有回复内容与关闭时间等一律保留，不被新提交覆盖。
    """
    for field in BUSINESS_FIELDS:
        text = str(values.get(field) or "").strip()
        if text and not str(entry.get(field) or "").strip():
            entry[field] = text
