from __future__ import annotations

import copy
import unittest

from app.seed import SEED_ROWS
from app.services.complaint import ComplaintService
from app.store import store


class ComplaintServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        store._tables["complaint"] = [copy.deepcopy(row) for row in SEED_ROWS["complaint"]]
        self.service = ComplaintService()

    def create(self, **values: str) -> dict:
        entry, missing, merged = self.service.create_entry(values)
        self.assertFalse(missing)
        self.assertIsNotNone(entry)
        self.assertFalse(merged)
        assert entry is not None
        return entry

    def test_empty_deadline_allows_full_flow_and_preserves_reply_and_close_time(self) -> None:
        entry = self.create(
            **{"投诉编号": "COMP-T-001", "投诉单位": "委托单位", "投诉事由": "报告疑问", "处理期限": ""}
        )

        accepted, message = self.service.run_action(entry["id"], "受理投诉", {"action": "受理投诉"})
        self.assertIsNotNone(accepted)
        assert accepted is not None
        self.assertEqual(accepted["status"], "处理中")
        self.assertFalse(accepted["abnormal"])

        replied, _ = self.service.run_action(
            entry["id"],
            "提交回复",
            {"action": "提交回复", "处理措施": "电话说明", "回复内容": "已电话说明"},
        )
        assert replied is not None
        self.assertEqual(replied["status"], "已回复")
        self.assertEqual(replied["回复内容"], "已电话说明")

        closed, _ = self.service.run_action(entry["id"], "关闭投诉", {"action": "关闭投诉"})
        assert closed is not None
        self.assertEqual(closed["status"], "已关闭")
        self.assertFalse(closed["abnormal"])
        self.assertTrue(closed["关闭时间"])
        close_time = closed["关闭时间"]

        repeated, message = self.service.run_action(entry["id"], "关闭投诉", {"action": "关闭投诉"})
        self.assertIsNone(repeated)
        self.assertIn("当前状态「已关闭」不允许", message)
        self.assertEqual(closed["关闭时间"], close_time)
        self.assertEqual(closed["回复内容"], "已电话说明")

    def test_duplicate_number_merges_without_changing_id_or_status(self) -> None:
        entry = self.create(
            **{"投诉编号": "COMP-T-002", "投诉单位": "原单位", "投诉事由": "数据疑问"}
        )
        accepted, _ = self.service.run_action(entry["id"], "受理投诉", {"action": "受理投诉"})
        assert accepted is not None

        merged, missing, is_merged = self.service.create_entry(
            {
                "投诉编号": " COMP-T-002 ",
                "涉及样品": "SAMPLE-1",
                "处理措施": "复核数据",
                "status": "已关闭",
            }
        )

        self.assertTrue(is_merged)
        self.assertEqual(missing, [])
        self.assertIs(merged, accepted)
        self.assertEqual(merged["id"], entry["id"])
        self.assertEqual(merged["status"], "处理中")
        self.assertEqual(merged["涉及样品"], "SAMPLE-1")
        self.assertEqual(merged["处理措施"], "复核数据")
        self.assertEqual(len(store.rows("complaint")), len(SEED_ROWS["complaint"]) + 1)

    def test_overdue_complaint_can_still_reply_and_close(self) -> None:
        entry = self.create(
            **{
                "投诉编号": "COMP-T-003",
                "投诉单位": "委托单位",
                "投诉事由": "延期反馈",
                "处理期限": "2000-01-01",
            }
        )
        accepted, _ = self.service.run_action(entry["id"], "受理投诉", {"action": "受理投诉"})
        assert accepted is not None
        self.assertTrue(accepted["abnormal"])

        replied, message = self.service.run_action(
            entry["id"],
            "提交回复",
            {"action": "提交回复", "处理措施": "补充说明", "回复内容": "超期后的回复"},
        )
        self.assertIsNotNone(replied, message)
        assert replied is not None
        self.assertEqual(replied["status"], "已回复")
        self.assertTrue(replied["abnormal"])

        closed, _ = self.service.run_action(entry["id"], "关闭投诉", {"action": "关闭投诉"})
        assert closed is not None
        self.assertEqual(closed["status"], "已关闭")
        self.assertTrue(closed["abnormal"])
        self.assertEqual(closed["回复内容"], "超期后的回复")
        self.assertEqual(closed["投诉状态"], "已关闭")
        self.assertTrue(closed["关闭时间"])

    def test_actions_are_guarded_by_current_status(self) -> None:
        entry = self.create(
            **{"投诉编号": "COMP-T-004", "投诉单位": "委托单位", "投诉事由": "状态校验"}
        )

        _, message = self.service.run_action(entry["id"], "提交回复", {"action": "提交回复"})
        self.assertIn("当前状态「待受理」不允许", message)
        _, message = self.service.run_action(entry["id"], "关闭投诉", {"action": "关闭投诉"})
        self.assertIn("当前状态「待受理」不允许", message)

        self.service.run_action(entry["id"], "受理投诉", {"action": "受理投诉"})
        _, message = self.service.run_action(entry["id"], "受理投诉", {"action": "受理投诉"})
        self.assertIn("当前状态「处理中」不允许", message)
        _, message = self.service.run_action(entry["id"], "关闭投诉", {"action": "关闭投诉"})
        self.assertIn("当前状态「处理中」不允许", message)

    def test_reply_requires_handling_measure(self) -> None:
        entry = self.create(
            **{"投诉编号": "COMP-T-005", "投诉单位": "委托单位", "投诉事由": "必填校验"}
        )
        self.service.run_action(entry["id"], "受理投诉", {"action": "受理投诉"})

        result, message = self.service.run_action(
            entry["id"], "提交回复", {"action": "提交回复", "处理措施": "  "}
        )
        self.assertIsNone(result)
        self.assertIn("处理措施", message)


if __name__ == "__main__":
    unittest.main()
