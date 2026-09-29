"""Hermes Bill plugin registration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bill_store import BillStore


def _result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _tool_error(error: Exception) -> str:
    return _result({"ok": False, "error": str(error), "error_type": type(error).__name__})


def _manage_bill(args: dict[str, Any], **_: Any) -> str:
    try:
        store = BillStore()
        action = args["action"]
        dry_run = bool(args.get("dry_run", False))
        if action == "add":
            return _result(store.add_record(args["record"], dry_run=dry_run))
        if action == "import":
            return _result(store.import_records(args["records"], dry_run=dry_run))
        if action == "update":
            return _result(
                store.update_record(
                    args["transaction_id"],
                    args["updates"],
                    dry_run=dry_run,
                )
            )
        raise ValueError(f"不支持的 action: {action}")
    except Exception as error:  # Hermes tool handlers must return errors, never raise.
        return _tool_error(error)


RECORD_PROPERTIES = {
    "transactionTime": {"type": "string", "description": "交易时间，如 2026/9/24 12:30:00"},
    "counterparty": {"type": "string", "description": "交易对方"},
    "category": {"type": "string", "description": "bill-manager skill 允许的交易分类"},
    "item": {"type": "string", "description": "商品或服务"},
    "remark": {"type": "string", "description": "备注"},
    "channel": {"type": "string", "description": "交易渠道"},
    "status": {"type": "string", "description": "当前状态"},
    "paymentMethod": {"type": "string", "description": "支付方式"},
    "direction": {"type": "string", "enum": ["收入", "支出", "不计入收支"]},
    "amount": {"description": "金额，必须大于 0", "anyOf": [{"type": "number"}, {"type": "string"}]},
    "transactionId": {"type": "string", "description": "可选的来源交易单号"},
}


def register(ctx: Any) -> None:
    """Register model tools and the bundled parsing skill."""
    skill_path = Path(__file__).parent / "skills" / "bill-manager" / "SKILL.md"
    ctx.register_skill("bill-manager", skill_path)

    ctx.register_tool(
        name="bill_manage",
        toolset="hermes_bill",
        handler=_manage_bill,
        description="新增、批量导入或更新远程账单。",
        schema={
            "name": "bill_manage",
            "description": "管理账单。调用前应加载 hermes-bill:bill-manager skill。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "import", "update"]},
                    "record": {
                        "type": "object",
                        "properties": RECORD_PROPERTIES,
                        "required": ["transactionTime", "counterparty", "category", "amount"],
                    },
                    "records": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "object", "properties": RECORD_PROPERTIES},
                    },
                    "transaction_id": {"type": "string"},
                    "updates": {"type": "object", "properties": RECORD_PROPERTIES},
                    "dry_run": {"type": "boolean", "default": False},
                },
                "required": ["action"],
            },
        },
        emoji="🧾",
    )
