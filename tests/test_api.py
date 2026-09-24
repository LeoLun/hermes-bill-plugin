from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

try:
    from fastapi import Response
    from fastapi.testclient import TestClient
    from dashboard.plugin_api import router
    from fastapi import FastAPI
except ImportError:  # pragma: no cover
    Response = None

from bill_store import BillStore


@unittest.skipIf(Response is None, "fastapi test dependencies are unavailable")
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HERMES_BILL_DATA_DIR": self.temp.name})
        self.env.start()
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_empty_overview_and_no_store(self):
        response = self.client.get("/overview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        payload = response.json()
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["summary"]["transactionCount"], 0)

    def test_invalid_month(self):
        response = self.client.get("/overview?year=2026&month=13")
        self.assertEqual(response.status_code, 400)

    def test_aggregated_response(self):
        BillStore().add_record({
            "transactionTime": "2026/9/24 12:30:00", "counterparty": "测试商户",
            "category": "购物", "direction": "支出", "amount": 88,
        })
        payload = self.client.get("/overview?year=2026&month=9").json()
        self.assertEqual(payload["summary"]["grossExpense"], 88)
        self.assertEqual(payload["recent"][0]["counterparty"], "测试商户")


if __name__ == "__main__":
    unittest.main()

