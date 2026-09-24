"""SQLite-backed bill normalization, persistence, and dashboard aggregation."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


SCHEMA_VERSION = 1
CATEGORIES = (
    "餐饮", "发红包", "服饰", "服务", "工资", "购物", "奖金", "交通", "教育", "酒店",
    "旅行", "其他", "生活缴费", "退款", "医疗", "娱乐", "转账", "房租", "公积金",
)
DIRECTIONS = ("收入", "支出", "不计入收支")

ALIASES = {
    "transaction_id": ("transaction_id", "transactionId", "id", "交易单号"),
    "counterparty": ("counterparty", "交易对方"),
    "transaction_time": ("transaction_time", "transactionTime", "交易时间"),
    "channel": ("channel", "交易渠道"),
    "category": ("category", "交易类型"),
    "record_created_time": ("created_time", "createdTime", "创建时间"),
    "item": ("item", "product", "description", "商品"),
    "remark": ("remark", "备注"),
    "status": ("status", "当前状态"),
    "payment_method": ("payment_method", "paymentMethod", "支付方式"),
    "direction": ("direction", "收入/支出"),
    "amount": ("amount", "金额(元)"),
}


class BillValidationError(ValueError):
    """Raised when a bill record cannot be normalized safely."""


@dataclass(frozen=True)
class BillRecord:
    transaction_id: str
    counterparty: str
    transaction_time: str
    transaction_year: int
    transaction_month: int
    channel: str
    category: str
    record_created_time: str
    item: str
    remark: str
    status: str
    payment_method: str
    direction: str
    amount_cents: int


def resolve_data_dir() -> Path:
    override = os.environ.get("HERMES_BILL_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
    return hermes_home / "plugin-data" / "hermes-bill"


def _value(data: Mapping[str, Any], field: str, default: Any = None) -> Any:
    for key in ALIASES[field]:
        if key in data and data[key] is not None:
            return data[key]
    return default


def _text(value: Any) -> str:
    return "" if value is None else str(value).lstrip("\ufeff").strip()


def parse_datetime(value: Any) -> datetime:
    text = _text(value)
    try:
        parsed_iso = datetime.fromisoformat(text)
        if parsed_iso.tzinfo is None:
            parsed_iso = parsed_iso.astimezone()
        return parsed_iso
    except ValueError:
        pass
    match = re.match(
        r"^(\d{2,4})\s*(?:/|-|年)\s*(\d{1,2})\s*(?:/|-|月)\s*(\d{1,2})日?"
        r"(?:[ T]+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?$",
        text,
    )
    if not match:
        raise BillValidationError("缺少有效交易时间，需提供完整年份、月份和日期")
    year, month, day, hour, minute, second = match.groups(default="0")
    if len(year) == 2:
        year = f"20{year}"
    try:
        return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second)).astimezone()
    except ValueError as exc:
        raise BillValidationError(f"无效交易时间: {text}") from exc


def parse_amount_cents(value: Any) -> int:
    cleaned = re.sub(r"[^\d.\-]", "", _text(value).replace(",", ""))
    if not cleaned:
        raise BillValidationError("缺少有效金额")
    try:
        amount = abs(Decimal(cleaned)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise BillValidationError(f"无效金额: {value}") from exc
    cents = int(amount * 100)
    if cents <= 0:
        raise BillValidationError("金额必须大于 0")
    return cents


def infer_direction(text: str) -> str:
    if re.search(r"收到|收款|收入|工资|奖金|退款到账", text):
        return "收入"
    if re.search(r"不计|报销", text):
        return "不计入收支"
    return "支出"


def transaction_prefix(payment_method: str) -> str:
    lowered = payment_method.lower()
    if re.search(r"微信|wechat|weixin|\bwx\b", lowered):
        return "wx-"
    if re.search(r"支付宝|alipay|\bzfb\b|\bali\b", lowered):
        return "zfb-"
    return "qt-"


def normalize_record(data: Mapping[str, Any]) -> BillRecord:
    if not isinstance(data, Mapping):
        raise BillValidationError("账单记录必须是对象")
    transaction_at = parse_datetime(_value(data, "transaction_time"))
    counterparty = _text(_value(data, "counterparty"))
    category = _text(_value(data, "category"))
    item = _text(_value(data, "item", ""))
    remark = _text(_value(data, "remark", ""))
    payment_method = _text(_value(data, "payment_method", "手动记录")) or "手动记录"
    channel = _text(_value(data, "channel", "其他")) or "其他"
    status = _text(_value(data, "status", "手动记录")) or "手动记录"
    created_value = _value(data, "record_created_time")
    created_at = parse_datetime(created_value) if _text(created_value) else transaction_at
    direction = _text(_value(data, "direction")) or infer_direction(f"{counterparty} {item} {remark}")
    amount_cents = parse_amount_cents(_value(data, "amount"))

    if not counterparty:
        raise BillValidationError("缺少交易对方")
    if category not in CATEGORIES:
        raise BillValidationError(f"交易类型必须是允许值之一，收到: {category or '(空)'}")
    if direction not in DIRECTIONS:
        raise BillValidationError(f"收入/支出必须是收入、支出或不计入收支，收到: {direction or '(空)'}")

    amount_text = f"{Decimal(amount_cents) / 100:.2f}"
    transaction_time = transaction_at.isoformat(timespec="seconds")
    supplied_id = _text(_value(data, "transaction_id"))
    prefix = transaction_prefix(payment_method)
    if supplied_id:
        transaction_id = prefix + re.sub(r"^(?:wx|zfb|qt)-", "", supplied_id, flags=re.I)
    else:
        digest_parts = (
            prefix, transaction_time, counterparty, category, item, remark,
            payment_method, direction, amount_text,
        )
        digest = hashlib.sha1("|".join(digest_parts).encode("utf-8")).hexdigest()[:16]
        transaction_id = f"{prefix}{digest}"

    return BillRecord(
        transaction_id=transaction_id,
        counterparty=counterparty,
        transaction_time=transaction_time,
        transaction_year=transaction_at.year,
        transaction_month=transaction_at.month,
        channel=channel,
        category=category,
        record_created_time=created_at.isoformat(timespec="seconds"),
        item=item or category,
        remark=remark,
        status=status,
        payment_method=payment_method,
        direction=direction,
        amount_cents=amount_cents,
    )


class BillStore:
    def __init__(self, database_path: Path | str | None = None) -> None:
        self.database_path = Path(database_path) if database_path else resolve_data_dir() / "bills.sqlite3"
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY,
                    counterparty TEXT NOT NULL,
                    transaction_time TEXT NOT NULL,
                    transaction_year INTEGER NOT NULL,
                    transaction_month INTEGER NOT NULL CHECK(transaction_month BETWEEN 1 AND 12),
                    channel TEXT NOT NULL,
                    category TEXT NOT NULL,
                    record_created_time TEXT NOT NULL,
                    item TEXT NOT NULL,
                    remark TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payment_method TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                    inserted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_transactions_period
                    ON transactions(transaction_year, transaction_month, transaction_time DESC);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, datetime.now().astimezone().isoformat(timespec="seconds")),
            )
            connection.commit()

    @staticmethod
    def _insert(connection: sqlite3.Connection, record: BillRecord) -> bool:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO transactions (
                transaction_id, counterparty, transaction_time, transaction_year, transaction_month,
                channel, category, record_created_time, item, remark, status, payment_method,
                direction, amount_cents, inserted_at, updated_at
            ) VALUES (
                :transaction_id, :counterparty, :transaction_time, :transaction_year, :transaction_month,
                :channel, :category, :record_created_time, :item, :remark, :status, :payment_method,
                :direction, :amount_cents, :inserted_at, :updated_at
            )
            """,
            {**asdict(record), "inserted_at": now, "updated_at": now},
        )
        return cursor.rowcount == 1

    def add_record(self, data: Mapping[str, Any], dry_run: bool = False) -> dict[str, Any]:
        record = normalize_record(data)
        with self.connect() as connection:
            if not dry_run:
                connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                "SELECT 1 FROM transactions WHERE transaction_id = ?", (record.transaction_id,)
            ).fetchone() is not None
            if not dry_run and not duplicate:
                added = self._insert(connection, record)
                connection.commit()
            else:
                added = False
                if not dry_run:
                    connection.rollback()
        return {
            "added": added,
            "updated": False,
            "duplicate": duplicate,
            "dry_run": dry_run,
            "transaction_id": record.transaction_id,
        }

    def import_records(self, records: Sequence[Mapping[str, Any]], dry_run: bool = False) -> dict[str, Any]:
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes)) or not records:
            raise BillValidationError("导入记录必须是非空数组")
        normalized = [normalize_record(record) for record in records]
        added = 0
        duplicates = 0
        results: list[dict[str, Any]] = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                seen: set[str] = set()
                for record in normalized:
                    duplicate = record.transaction_id in seen or connection.execute(
                        "SELECT 1 FROM transactions WHERE transaction_id = ?", (record.transaction_id,)
                    ).fetchone() is not None
                    if duplicate:
                        duplicates += 1
                    else:
                        seen.add(record.transaction_id)
                        if not dry_run:
                            self._insert(connection, record)
                        added += 1
                    results.append({"transaction_id": record.transaction_id, "duplicate": duplicate})
                if dry_run:
                    connection.rollback()
                else:
                    connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {
            "added": 0 if dry_run else added,
            "would_add": added if dry_run else 0,
            "updated": False,
            "duplicate": duplicates > 0,
            "duplicates": duplicates,
            "total": len(normalized),
            "dry_run": dry_run,
            "transaction_id": None,
            "results": results,
        }

    def update_record(self, transaction_id: str, updates: Mapping[str, Any], dry_run: bool = False) -> dict[str, Any]:
        target_id = _text(transaction_id)
        if not target_id:
            raise BillValidationError("缺少交易单号")
        if not isinstance(updates, Mapping) or not updates:
            raise BillValidationError("更新字段必须是非空对象")
        known_update_keys = {alias for aliases in ALIASES.values() for alias in aliases} - set(ALIASES["transaction_id"])
        unknown_keys = sorted(set(updates) - known_update_keys)
        if unknown_keys:
            raise BillValidationError(f"不支持的更新字段: {', '.join(unknown_keys)}")
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM transactions WHERE transaction_id = ?", (target_id,)).fetchone()
            if row is None:
                raise BillValidationError(f"未找到交易单号: {target_id}")
            base = self._record_to_public(row)
            normalized_updates = dict(updates)
            for field, aliases in ALIASES.items():
                for alias in aliases:
                    if alias in normalized_updates:
                        base[field] = normalized_updates[alias]
                        break
            base["transaction_id"] = target_id
            next_record = replace(normalize_record(base), transaction_id=target_id)
            if not dry_run:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    UPDATE transactions SET
                        counterparty=:counterparty, transaction_time=:transaction_time,
                        transaction_year=:transaction_year, transaction_month=:transaction_month,
                        channel=:channel, category=:category, record_created_time=:record_created_time,
                        item=:item, remark=:remark, status=:status, payment_method=:payment_method,
                        direction=:direction, amount_cents=:amount_cents, updated_at=:updated_at
                    WHERE transaction_id=:transaction_id
                    """,
                    {**asdict(next_record), "updated_at": datetime.now().astimezone().isoformat(timespec="seconds")},
                )
                connection.commit()
        return {
            "added": False,
            "updated": not dry_run,
            "duplicate": False,
            "dry_run": dry_run,
            "transaction_id": target_id,
        }

    @staticmethod
    def _record_to_public(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "transaction_id": row["transaction_id"],
            "counterparty": row["counterparty"],
            "transaction_time": row["transaction_time"],
            "channel": row["channel"],
            "category": row["category"],
            "created_time": row["record_created_time"],
            "item": row["item"],
            "remark": row["remark"],
            "status": row["status"],
            "payment_method": row["payment_method"],
            "direction": row["direction"],
            "amount": row["amount_cents"] / 100,
        }

    def overview(self, year: int | None = None, month: int | None = None) -> dict[str, Any]:
        now = datetime.now().astimezone()
        with self.connect() as connection:
            years = [row[0] for row in connection.execute(
                "SELECT DISTINCT transaction_year FROM transactions ORDER BY transaction_year DESC"
            )]
            selected_year = year if year is not None else (now.year if now.year in years else (years[0] if years else now.year))
            if selected_year < 1900 or selected_year > 9999:
                raise BillValidationError("year 必须是四位年份")
            recorded_months = [row[0] for row in connection.execute(
                "SELECT DISTINCT transaction_month FROM transactions WHERE transaction_year = ? ORDER BY transaction_month",
                (selected_year,),
            )]
            previous_month = 12 if now.month == 1 else now.month - 1
            previous_month_year = now.year - 1 if now.month == 1 else now.year
            default_month = previous_month if selected_year == previous_month_year else (max(recorded_months) if recorded_months else previous_month)
            selected_month = month if month is not None else default_month
            if selected_month < 1 or selected_month > 12:
                raise BillValidationError("month 必须在 1 到 12 之间")
            current_rows = connection.execute(
                "SELECT * FROM transactions WHERE transaction_year = ? ORDER BY transaction_time DESC",
                (selected_year,),
            ).fetchall()
            previous_rows = connection.execute(
                "SELECT * FROM transactions WHERE transaction_year = ? ORDER BY transaction_time",
                (selected_year - 1,),
            ).fetchall()

        expenses = [row for row in current_rows if row["direction"] == "支出"]
        refunds = [row for row in current_rows if row["direction"] == "收入" and row["category"] == "退款"]
        gross_cents = sum(row["amount_cents"] for row in expenses)
        refund_cents = sum(row["amount_cents"] for row in refunds)
        monthly_net = self._monthly_net(current_rows)
        previous_net = self._monthly_net(previous_rows)
        annual_categories = self._categories(expenses)
        month_expenses = [row for row in expenses if row["transaction_month"] == selected_month]
        cumulative = 0
        previous_cumulative = 0
        months_payload = []
        for number in range(1, 13):
            current_amount = monthly_net.get(number)
            previous_amount = previous_net.get(number)
            if current_amount is not None:
                cumulative += current_amount
            if previous_amount is not None:
                previous_cumulative += previous_amount
            months_payload.append({
                "month": number,
                "label": f"{number}月",
                "amount": None if current_amount is None else current_amount / 100,
                "cumulative": None if current_amount is None else cumulative / 100,
                "lastYearAmount": None if previous_amount is None else previous_amount / 100,
                "lastYearCumulative": None if previous_amount is None else previous_cumulative / 100,
            })
        populated_months = [item for item in months_payload if item["amount"] is not None]
        peak = max(populated_months, key=lambda item: item["amount"], default=None)
        net_cents = gross_cents - refund_cents
        summary = {
            "totalExpense": net_cents / 100,
            "grossExpense": gross_cents / 100,
            "refundTotal": refund_cents / 100,
            "averageMonthlyExpense": net_cents / max(len(populated_months), 1) / 100,
            "topCategory": annual_categories[0] if annual_categories else None,
            "transactionCount": len(current_rows),
            "peakMonth": peak,
            "monthsWithData": len(populated_months),
        }
        return {
            "schemaVersion": SCHEMA_VERSION,
            "availableYears": years,
            "selectedYear": selected_year,
            "selectedMonth": selected_month,
            "availableMonths": list(range(1, 13)),
            "summary": summary,
            "months": months_payload,
            "categories": annual_categories,
            "monthlyCategories": self._categories(month_expenses),
            "monthlyGrossExpense": sum(row["amount_cents"] for row in month_expenses) / 100,
            "recent": [self._record_to_public(row) for row in current_rows[:5]],
        }

    @staticmethod
    def _monthly_net(rows: Sequence[Mapping[str, Any]]) -> dict[int, int]:
        totals: dict[int, int] = {}
        for row in rows:
            is_expense = row["direction"] == "支出"
            is_refund = row["direction"] == "收入" and row["category"] == "退款"
            if not is_expense and not is_refund:
                continue
            month = int(row["transaction_month"])
            totals[month] = totals.get(month, 0) + (row["amount_cents"] if is_expense else -row["amount_cents"])
        return totals

    @staticmethod
    def _categories(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        overall = 0
        for row in rows:
            totals[row["category"]][0] += row["amount_cents"]
            totals[row["category"]][1] += 1
            overall += row["amount_cents"]
        return [
            {
                "type": category,
                "amount": amount / 100,
                "count": count,
                "percent": amount / overall * 100 if overall else 0,
            }
            for category, (amount, count) in sorted(totals.items(), key=lambda item: item[1][0], reverse=True)
        ]
