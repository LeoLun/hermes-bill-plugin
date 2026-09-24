from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from bill_store import BillStore, BillValidationError, normalize_record, parse_amount_cents


def record(**overrides):
    base = {
        "transactionTime": "2026/9/24 12:30:00",
        "counterparty": "测试食堂",
        "category": "餐饮",
        "paymentMethod": "微信支付",
        "direction": "支出",
        "amount": "28.50",
    }
    base.update(overrides)
    return base


class NormalizationTests(unittest.TestCase):
    def test_aliases_and_stable_wechat_id(self):
        english = normalize_record(record())
        chinese = normalize_record({
            "交易时间": "2026/9/24 12:30:00", "交易对方": "测试食堂", "交易类型": "餐饮",
            "支付方式": "微信支付", "收入/支出": "支出", "金额(元)": "¥28.50",
        })
        self.assertEqual(english.transaction_id, chinese.transaction_id)
        self.assertTrue(english.transaction_id.startswith("wx-"))
        self.assertEqual(english.amount_cents, 2850)

    def test_payment_prefixes(self):
        self.assertTrue(normalize_record(record(paymentMethod="支付宝")).transaction_id.startswith("zfb-"))
        self.assertTrue(normalize_record(record(paymentMethod="银行卡")).transaction_id.startswith("qt-"))

    def test_amount_rounding_and_invalid_values(self):
        self.assertEqual(parse_amount_cents("￥1,234.565元"), 123457)
        with self.assertRaises(BillValidationError):
            parse_amount_cents("0")

    def test_invalid_date_category_and_direction(self):
        with self.assertRaises(BillValidationError):
            normalize_record(record(transactionTime="2026/2/30"))
        with self.assertRaises(BillValidationError):
            normalize_record(record(category="未知分类"))
        with self.assertRaises(BillValidationError):
            normalize_record(record(direction="借方"))

    def test_csv_like_text_is_preserved(self):
        normalized = normalize_record(record(item='套餐,含"饮料"', remark="第一行\n第二行"))
        self.assertEqual(normalized.item, '套餐,含"饮料"')
        self.assertEqual(normalized.remark, "第一行\n第二行")

    def test_family_card_rule_input(self):
        normalized = normalize_record(record(counterparty="家庭成员", category="转账", item="", remark="亲情卡交易"))
        self.assertEqual(normalized.category, "转账")
        self.assertEqual(normalized.direction, "支出")
        self.assertEqual(normalized.remark, "亲情卡交易")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "bills.sqlite3"
        self.store = BillStore(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_add_duplicate_dry_run_and_restart(self):
        preview = self.store.add_record(record(), dry_run=True)
        self.assertFalse(preview["added"])
        self.assertFalse(preview["duplicate"])
        added = self.store.add_record(record())
        self.assertTrue(added["added"])
        self.assertTrue(self.store.add_record(record())["duplicate"])
        restarted = BillStore(self.database)
        self.assertEqual(restarted.overview(2026, 9)["summary"]["transactionCount"], 1)

    def test_atomic_batch_rejects_all_on_validation_error(self):
        with self.assertRaises(BillValidationError):
            self.store.import_records([record(), record(counterparty="第二家", category="无效")])
        self.assertEqual(self.store.overview(2026, 9)["summary"]["transactionCount"], 0)

    def test_batch_duplicate_inside_same_request(self):
        result = self.store.import_records([record(), record()])
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["duplicates"], 1)

    def test_update_preserves_id_and_moves_period(self):
        transaction_id = self.store.add_record(record())["transaction_id"]
        result = self.store.update_record(transaction_id, {"amount": 35, "transactionTime": "2026/10/1 08:00:00"})
        self.assertTrue(result["updated"])
        self.assertEqual(result["transaction_id"], transaction_id)
        overview = self.store.overview(2026, 10)
        self.assertEqual(overview["summary"]["grossExpense"], 35)

    def test_overview_refunds_income_and_categories(self):
        self.store.import_records([
            record(amount=100, category="餐饮"),
            record(counterparty="服装店", amount=50, category="服饰", transactionTime="2026/10/1 10:00:00"),
            record(counterparty="退款商户", amount=20, category="退款", direction="收入", transactionTime="2026/10/2 10:00:00"),
            record(counterparty="公司", amount=1000, category="工资", direction="收入", transactionTime="2026/10/3 10:00:00"),
        ])
        data = self.store.overview(2026, 10)
        self.assertEqual(data["summary"]["grossExpense"], 150)
        self.assertEqual(data["summary"]["refundTotal"], 20)
        self.assertEqual(data["summary"]["totalExpense"], 130)
        self.assertEqual(data["summary"]["averageMonthlyExpense"], 65)
        self.assertEqual(data["categories"][0]["type"], "餐饮")
        self.assertEqual(data["monthlyGrossExpense"], 50)

    def test_concurrent_writes(self):
        errors = []

        def add(index):
            try:
                BillStore(self.database).add_record(record(counterparty=f"商户{index}", amount=index + 1))
            except Exception as exc:  # pragma: no cover - assertion reports details
                errors.append(exc)

        threads = [threading.Thread(target=add, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.store.overview(2026, 9)["summary"]["transactionCount"], 8)


if __name__ == "__main__":
    unittest.main()

