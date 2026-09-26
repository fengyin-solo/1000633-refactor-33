"""投诉处理接口：维护投诉记录，覆盖受理投诉、提交回复、关闭投诉等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.complaint import ComplaintService
from app.services.complaint_rules import NUMBER_FIELD, STATUS_ORDER

router = APIRouter(prefix="/api/complaint", tags=["投诉处理"])

service = ComplaintService()

LIST_FIELDS = ["投诉编号", "投诉单位", "投诉事由", "涉及样品", "受理人员", "处理措施", "处理期限", "投诉状态"]
STATUSES = STATUS_ORDER


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按投诉编号检索"),
    status: str | None = Query(default=None, description="待受理、处理中、已回复、已关闭"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按投诉编号与状态过滤投诉处理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


# 固定路径必须排在 /{entry_id} 之前，否则 export 会被当成记录编号解析（历史遗留 422）
@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出投诉处理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "complaint", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条投诉记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"投诉记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条投诉记录，缺字段时说明原因而不是静默丢弃。

    投诉编号已存在时不再新建，按共用合并口径补齐空缺字段并保留原状态。
    """
    number = str(payload.values.get(NUMBER_FIELD) or "").strip()
    merged_into = service.find_by_number(number) if number else None
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if merged_into is not None and entry is merged_into:
        return ActionResult(ok=True, message=f"投诉编号 {number} 已存在，受理信息已合并到原记录", entry=entry)
    return ActionResult(ok=True, message="投诉记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条投诉记录执行受理投诉、提交回复、关闭投诉；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
