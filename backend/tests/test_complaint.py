"""投诉处理共用口径的行为测试：

覆盖处理期限为空、重复受理合并、超期后仍要回复、状态流转校验，
以及既有投诉编号/状态取值、回复内容与关闭时间、接口返回结构不得改变的约束。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import SEED_ROWS
from app.services import complaint_rules as rules
from app.services.complaint import MODULE, ComplaintService
from app.store import store

client = TestClient(app)
service = ComplaintService()


@pytest.fixture(autouse=True)
def reset_complaint_rows():
    """每个用例都从干净的示例数据出发，避免动作之间互相污染。"""
    store.rows(MODULE)[:] = [dict(row) for row in SEED_ROWS[MODULE]]
    yield
    store.rows(MODULE)[:] = [dict(row) for row in SEED_ROWS[MODULE]]


def make_entry(number: str = "COMP-1001", **extra) -> dict:
    values = {"投诉编号": number, "投诉单位": "某委托单位", "投诉事由": "结果出具延迟"}
    values.update(extra)
    entry, missing = service.create_entry(values)
    assert missing == []
    return entry


# ---------------------------------------------------------------- 接口结构

def test_list_and_action_response_shapes_unchanged():
    data = client.get("/api/complaint").json()
    assert set(data.keys()) == {"items", "total", "page", "size"}
    assert data["total"] == 3

    created = client.post("/api/complaint", json={"values": {
        "投诉编号": "COMP-2001", "投诉单位": "u", "投诉事由": "r",
    }}).json()
    assert set(created.keys()) == {"ok", "message", "entry"}
    assert created["ok"] is True

    detail = client.get(f"/api/complaint/{created['entry']['id']}").json()
    assert detail["投诉编号"] == "COMP-2001"

    exported = client.get("/api/complaint/export").json()
    assert exported["module"] == "complaint" and "items" in exported


def test_create_missing_fields_returns_ok_false_with_message():
    resp = client.post("/api/complaint", json={"values": {"投诉编号": "COMP-2002"}}).json()
    assert resp == {"ok": False, "message": "缺少必填字段：投诉单位、投诉事由", "entry": None}


# ---------------------------------------------------------------- 状态取值与流转

def test_full_lifecycle_keeps_standard_status_values_and_timestamps():
    entry = make_entry()
    assert entry["status"] == "待受理"
    eid = entry["id"]

    resp = client.post(f"/api/complaint/{eid}/actions", json={"values": {"action": "受理投诉"}}).json()
    assert resp["ok"] is True
    assert resp["entry"]["status"] == "处理中"
    assert resp["entry"]["受理时间"]

    resp = client.post(f"/api/complaint/{eid}/actions", json={"values": {
        "action": "提交回复", "处理措施": "重新出具报告", "回复内容": "已向单位致歉并补寄报告",
    }}).json()
    assert resp["entry"]["status"] == "已回复"
    assert resp["entry"]["回复内容"] == "已向单位致歉并补寄报告"
    assert resp["entry"]["回复时间"]

    resp = client.post(f"/api/complaint/{eid}/actions", json={"values": {"action": "关闭投诉"}}).json()
    assert resp["entry"]["status"] == "已关闭"
    assert resp["entry"]["pending"] is False
    assert resp["entry"]["关闭时间"]

    # 已有回复内容与关闭时间在关闭后仍然保留
    detail = client.get(f"/api/complaint/{eid}").json()
    assert detail["回复内容"] == "已向单位致歉并补寄报告"
    assert detail["回复时间"] and detail["关闭时间"]
    assert detail["受理时间"]


def test_status_transitions_are_enforced_between_replied_and_closed():
    entry = make_entry()
    eid = entry["id"]

    # 待受理不能直接回复或关闭
    blocked = client.post(f"/api/complaint/{eid}/actions", json={"values": {
        "action": "提交回复", "回复内容": "x",
    }}).json()
    assert blocked["ok"] is False and "不能执行" in blocked["message"]
    blocked = client.post(f"/api/complaint/{eid}/actions", json={"values": {"action": "关闭投诉"}}).json()
    assert blocked["ok"] is False
    assert service.get_entry(eid)["status"] == "待受理"

    assert client.post(f"/api/complaint/{eid}/actions", json={"values": {"action": "受理投诉"}}).json()["ok"]

    # 处理中不能受理也不能关闭，且缺回复内容/处理措施被拦下
    bad = client.post(f"/api/complaint/{eid}/actions", json={"values": {"action": "提交回复"}}).json()
    assert bad["ok"] is False and "回复内容" in bad["message"]
    assert client.post(f"/api/complaint/{eid}/actions", json={"values": {"action": "关闭投诉"}}).json()["ok"] is False

    client.post(f"/api/complaint/{eid}/actions", json={"values": {
        "action": "提交回复", "处理措施": "m", "回复内容": "c",
    }})
    # 已回复不能重复回复；关闭后任何动作都不允许，且关闭时间不被改写
    assert client.post(f"/api/complaint/{eid}/actions", json={"values": {
        "action": "提交回复", "处理措施": "m2", "回复内容": "c2",
    }}).json()["ok"] is False
    closed = client.post(f"/api/complaint/{eid}/actions", json={"values": {"action": "关闭投诉"}}).json()
    closed_at = closed["entry"]["关闭时间"]
    again = client.post(f"/api/complaint/{eid}/actions", json={"values": {"action": "关闭投诉"}}).json()
    assert again["ok"] is False
    detail = client.get(f"/api/complaint/{eid}").json()
    assert detail["关闭时间"] == closed_at
    assert detail["回复内容"] == "c"


def test_available_actions_are_consistent_with_status():
    entry = make_entry()
    assert service.actions_for(entry) == ["受理投诉"]
    rules.apply_action(entry, "受理投诉", {"处理措施": "m"})
    assert service.actions_for(entry) == ["提交回复"]
    rules.apply_action(entry, "提交回复", {"回复内容": "c"})
    assert service.actions_for(entry) == ["关闭投诉"]
    rules.apply_action(entry, "关闭投诉", {})
    assert service.actions_for(entry) == []


# ---------------------------------------------------------------- 处理期限

def test_empty_deadline_is_never_overdue_and_still_repliable():
    entry = make_entry("COMP-3001", 处理期限="")
    assert entry["abnormal"] is False
    assert rules.is_overdue(entry, today=date(2099, 1, 1)) is False

    # 空期限即便拖到很久以后，受理与回复都仍可执行
    assert service.run_action(entry["id"], "受理投诉", now="2099-01-01")[0] is not None
    reply, msg = service.run_action(
        entry["id"], "提交回复", {"处理措施": "m", "回复内容": "c"}, now="2099-01-02"
    )
    assert reply is not None and reply["status"] == "已回复" and reply["abnormal"] is False


def test_blank_or_unparsable_deadline_counts_as_no_deadline():
    for raw in (None, "", "   ", "待定"):
        assert rules.parse_day(raw) is None


def test_overdue_does_not_block_reply_and_marks_abnormal():
    # 截止 2026-09-10，2026-09-26 受理时已超期
    entry = make_entry("COMP-3002", 处理期限="2026-09-10")
    service.run_action(entry["id"], "受理投诉", now="2026-09-20")
    reply, msg = service.run_action(
        entry["id"], "提交回复",
        {"处理措施": "m", "回复内容": "超期后的回复"},
        now="2026-09-26",
    )
    assert reply is not None, msg
    assert reply["status"] == "已回复"
    assert reply["abnormal"] is True
    assert reply["回复内容"] == "超期后的回复"

    # 关闭后不再追算超期，避免已归档记录一直挂异常
    closed, _ = service.run_action(reply["id"], "关闭投诉")
    assert closed["status"] == "已关闭"
    assert rules.is_overdue(closed) is False


def test_due_today_is_not_overdue():
    entry = make_entry("COMP-3003", 处理期限="2026-09-26")
    assert rules.is_overdue(entry, today=date(2026, 9, 26)) is False
    assert rules.is_overdue(entry, today=date(2026, 9, 27)) is True


# ---------------------------------------------------------------- 重复受理

def test_duplicate_complaint_number_merges_instead_of_creating():
    first = make_entry("COMP-4001", 涉及样品="", 处理措施="原始措施")
    before_total = client.get("/api/complaint").json()["total"]

    resp = client.post("/api/complaint", json={"values": {
        "投诉编号": "COMP-4001",
        "投诉单位": "某委托单位",
        "投诉事由": "补充说明",
        "涉及样品": "SAMP-9",
        "处理措施": "想覆盖的措施",
    }}).json()
    assert resp["ok"] is True
    assert "已合并" in resp["message"]
    assert resp["entry"]["id"] == first["id"]
    assert client.get("/api/complaint").json()["total"] == before_total

    merged = service.get_entry(first["id"])
    assert merged["涉及样品"] == "SAMP-9"           # 空缺字段被补齐
    assert merged["处理措施"] == "原始措施"          # 已有字段不被覆盖
    assert merged["status"] == "待受理"              # 原状态保留
    assert merged["投诉编号"] == "COMP-4001"         # 编号取值不变


def test_merge_preserves_reply_content_and_close_time():
    entry = make_entry("COMP-4002", 处理措施="m")
    service.run_action(entry["id"], "受理投诉", now="2026-09-05")
    service.run_action(entry["id"], "提交回复", {"回复内容": "正式答复"}, now="2026-09-06")
    service.run_action(entry["id"], "关闭投诉", now="2026-09-07")

    merged, missing = service.create_entry({
        "投诉编号": "COMP-4002", "投诉单位": "u", "投诉事由": "r2",
        "涉及样品": "SAMP-1", "回复内容": "不应写入的答复", "处理措施": "不应写入的措施",
    })
    assert missing == []
    assert merged["id"] == entry["id"]
    assert merged["status"] == "已关闭"
    assert merged["回复内容"] == "正式答复"
    assert merged["关闭时间"] == "2026-09-07"
    assert merged["回复时间"] == "2026-09-06"
    assert merged["处理措施"] == "m"
    assert merged["涉及样品"] == "SAMP-1"  # 空缺业务字段仍允许补齐


# ---------------------------------------------------------------- 既有数据与杂项

def test_seed_numbers_and_statuses_are_unchanged():
    seed = {row["id"]: row for row in SEED_ROWS[MODULE]}
    live = {row["id"]: row for row in store.rows(MODULE)}
    for eid, row in seed.items():
        assert live[eid]["投诉编号"] == row["投诉编号"]
        assert live[eid]["status"] == row["status"]
    assert {row["status"] for row in live.values()} <= set(rules.STATUS_ORDER)


def test_unknown_action_and_missing_entry_are_rejected():
    resp = client.post("/api/complaint/1/actions", json={"values": {"action": "删除投诉"}}).json()
    assert resp["ok"] is False and "可执行范围" in resp["message"]

    resp = client.post("/api/complaint/9999/actions", json={"values": {"action": "受理投诉"}}).json()
    assert resp["ok"] is False and "不存在" in resp["message"]
    assert client.get("/api/complaint/9999").status_code == 404


def test_keyword_and_status_filters_remain_working():
    assert client.get("/api/complaint", params={"keyword": "COMP-0001"}).json()["total"] == 1
    assert client.get("/api/complaint", params={"status": "已回复"}).json()["total"] == 1
