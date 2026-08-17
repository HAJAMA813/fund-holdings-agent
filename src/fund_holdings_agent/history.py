from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def connect_history(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    _create_schema(connection)
    return connection


def ingest_quarter(
    db_path: Path,
    pipeline: dict[str, Any],
    industry: dict[str, Any] | None = None,
    pipeline_path: Path | None = None,
    industry_path: Path | None = None,
) -> dict[str, Any]:
    report_date = pipeline["summary"]["report_date"]
    manager = _manager_name(pipeline)
    if not manager:
        raise ValueError("无法从季度结果识别基金经理")
    summary = pipeline["summary"]
    quality = (industry or {}).get("industry_quality", {})
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    pipeline_source = _source_info(pipeline_path)
    industry_source = _source_info(industry_path)

    connection = connect_history(db_path)
    try:
        with connection:
            existing = connection.execute(
                "SELECT run_id FROM quarter_runs WHERE manager = ? AND report_date = ?",
                (manager, report_date),
            ).fetchone()
            if existing:
                run_id = int(existing["run_id"])
                connection.execute(
                    """
                    UPDATE quarter_runs SET
                        status = ?, input_funds = ?, selected_funds = ?, successful_funds = ?, formal_funds = ?,
                        raw_holding_rows = ?, formal_holding_rows = ?, issue_count = ?, error_count = ?, warning_count = ?,
                        success_rate = ?, duplicate_product_count = ?, industry_snapshot_date = ?, industry_standard = ?,
                        industry_coverage = ?, historical_industry_point_in_time = ?, pipeline_source_path = ?,
                        pipeline_source_sha256 = ?, industry_source_path = ?, industry_source_sha256 = ?, updated_at = ?
                    WHERE run_id = ?
                    """,
                    _run_values(summary, quality, pipeline_source, industry_source, now) + (run_id,),
                )
                for table in [
                    "run_sources",
                    "industry_issues",
                    "industry_summary",
                    "holding_industries",
                    "stock_industry",
                    "run_issues",
                    "holdings",
                    "funds",
                ]:
                    connection.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
                action = "updated"
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO quarter_runs (
                        manager, report_date, status, input_funds, selected_funds, successful_funds, formal_funds,
                        raw_holding_rows, formal_holding_rows, issue_count, error_count, warning_count, success_rate,
                        duplicate_product_count, industry_snapshot_date, industry_standard, industry_coverage,
                        historical_industry_point_in_time, pipeline_source_path, pipeline_source_sha256,
                        industry_source_path, industry_source_sha256, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (manager, report_date) + _run_values(summary, quality, pipeline_source, industry_source, now)[:-1] + (now, now),
                )
                run_id = int(cursor.lastrowid)
                action = "inserted"

            _insert_quarter_children(connection, run_id, pipeline, industry)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return {
            "action": action,
            "run_id": run_id,
            "manager": manager,
            "report_date": report_date,
            "fund_count": len(pipeline.get("funds", [])),
            "holding_count": len(pipeline.get("all_holdings", [])),
            "formal_holding_count": len(pipeline.get("formal_holdings", [])),
            "industry_mapping_count": len((industry or {}).get("stock_industry_mapping", [])),
        }
    finally:
        connection.close()


def ingest_comparison(db_path: Path, comparison: dict[str, Any], comparison_path: Path | None = None) -> dict[str, Any]:
    summary = comparison["summary"]
    manager = summary["manager"]
    previous_date = summary["previous_report_date"]
    current_date = summary["current_report_date"]
    source = _source_info(comparison_path)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    connection = connect_history(db_path)
    try:
        with connection:
            previous_run = connection.execute(
                "SELECT run_id FROM quarter_runs WHERE manager = ? AND report_date = ?", (manager, previous_date)
            ).fetchone()
            current_run = connection.execute(
                "SELECT run_id FROM quarter_runs WHERE manager = ? AND report_date = ?", (manager, current_date)
            ).fetchone()
            if not previous_run or not current_run:
                raise ValueError("必须先将比较涉及的两个季度写入历史数据库")
            previous_run_id = int(previous_run["run_id"])
            current_run_id = int(current_run["run_id"])
            existing = connection.execute(
                "SELECT comparison_id FROM comparisons WHERE manager = ? AND previous_report_date = ? AND current_report_date = ?",
                (manager, previous_date, current_date),
            ).fetchone()
            values = (
                previous_run_id,
                current_run_id,
                summary["status"],
                summary["company_union_count"],
                summary["new_company_count"],
                summary["exited_company_count"],
                summary["increased_company_count"],
                summary["decreased_company_count"],
                summary["unchanged_company_count"],
                summary["fund_stock_change_count"],
                summary["industry_union_count"],
                summary["new_industry_count"],
                summary["exited_industry_count"],
                summary["increased_industry_count"],
                summary["decreased_industry_count"],
                summary["industry_snapshot_date"],
                int(bool(summary["historical_industry_point_in_time"])),
                source["path"],
                source["sha256"],
                now,
            )
            if existing:
                comparison_id = int(existing["comparison_id"])
                connection.execute(
                    """
                    UPDATE comparisons SET
                        previous_run_id=?, current_run_id=?, status=?, company_union_count=?, new_company_count=?,
                        exited_company_count=?, increased_company_count=?, decreased_company_count=?, unchanged_company_count=?,
                        fund_stock_change_count=?, industry_union_count=?, new_industry_count=?, exited_industry_count=?,
                        increased_industry_count=?, decreased_industry_count=?, industry_snapshot_date=?,
                        historical_industry_point_in_time=?, source_path=?, source_sha256=?, updated_at=?
                    WHERE comparison_id=?
                    """,
                    values + (comparison_id,),
                )
                for table in ["comparison_sources", "comparison_rules", "comparison_checks", "industry_changes", "fund_stock_changes", "company_changes"]:
                    connection.execute(f"DELETE FROM {table} WHERE comparison_id = ?", (comparison_id,))
                action = "updated"
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO comparisons (
                        manager, previous_report_date, current_report_date, previous_run_id, current_run_id, status,
                        company_union_count, new_company_count, exited_company_count, increased_company_count,
                        decreased_company_count, unchanged_company_count, fund_stock_change_count, industry_union_count,
                        new_industry_count, exited_industry_count, increased_industry_count, decreased_industry_count,
                        industry_snapshot_date, historical_industry_point_in_time, source_path, source_sha256,
                        created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (manager, previous_date, current_date) + values[:-1] + (now, now),
                )
                comparison_id = int(cursor.lastrowid)
                action = "inserted"

            _insert_comparison_children(connection, comparison_id, comparison)
        return {
            "action": action,
            "comparison_id": comparison_id,
            "manager": manager,
            "previous_report_date": previous_date,
            "current_report_date": current_date,
            "company_change_count": len(comparison.get("company_changes", [])),
            "fund_stock_change_count": len(comparison.get("fund_stock_changes", [])),
            "industry_change_count": len(comparison.get("industry_changes", [])),
        }
    finally:
        connection.close()


def history_status(db_path: Path) -> dict[str, Any]:
    connection = connect_history(db_path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        quarters = [dict(row) for row in connection.execute(
            """
            SELECT run_id, manager, report_date, status, formal_funds, raw_holding_rows, formal_holding_rows,
                   error_count, warning_count, industry_snapshot_date, historical_industry_point_in_time,
                   pipeline_source_sha256, industry_source_sha256, updated_at
            FROM quarter_runs ORDER BY manager, report_date
            """
        )]
        comparisons = [dict(row) for row in connection.execute(
            """
            SELECT comparison_id, manager, previous_report_date, current_report_date, status, company_union_count,
                   new_company_count, exited_company_count, increased_company_count, decreased_company_count,
                   industry_union_count, updated_at
            FROM comparisons ORDER BY manager, current_report_date
            """
        )]
        counts = {}
        for table in [
            "quarter_runs", "funds", "holdings", "run_issues", "stock_industry", "holding_industries",
            "industry_summary", "comparisons", "company_changes", "fund_stock_changes", "industry_changes",
        ]:
            counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return {
            "database": str(db_path.resolve()),
            "schema_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "integrity_check": integrity,
            "counts": counts,
            "quarters": quarters,
            "comparisons": comparisons,
        }
    finally:
        connection.close()


def _run_values(
    summary: dict[str, Any],
    quality: dict[str, Any],
    pipeline_source: dict[str, str],
    industry_source: dict[str, str],
    now: str,
) -> tuple[Any, ...]:
    status = "通过" if summary.get("error_count", 0) == 0 else "有错误"
    return (
        status,
        summary.get("input_funds", 0),
        summary.get("selected_funds", 0),
        summary.get("successful_funds", 0),
        summary.get("formal_funds", 0),
        summary.get("raw_holding_rows", 0),
        summary.get("formal_holding_rows", 0),
        summary.get("issue_count", 0),
        summary.get("error_count", 0),
        summary.get("warning_count", 0),
        summary.get("success_rate", 0.0),
        summary.get("duplicate_product_count", 0),
        quality.get("snapshot_date", ""),
        quality.get("standard", ""),
        quality.get("holding_coverage"),
        int(bool(quality.get("historical_point_in_time"))),
        pipeline_source["path"],
        pipeline_source["sha256"],
        industry_source["path"],
        industry_source["sha256"],
        now,
    )


def _insert_quarter_children(connection: sqlite3.Connection, run_id: int, pipeline: dict[str, Any], industry: dict[str, Any] | None) -> None:
    connection.executemany(
        """
        INSERT INTO funds (
            run_id, fund_code, fund_name, manager, fund_type, inception_date, selected, selection_reason,
            verified_manager, manager_status, manager_source_url, fetch_status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                run_id, row["fund_code"], row["fund_name"], row["manager"], row.get("fund_type", ""),
                row.get("inception_date", ""), int(bool(row.get("selected"))), row.get("selection_reason", ""),
                row.get("verified_manager", ""), row.get("manager_status", ""), row.get("manager_source_url", ""), row.get("fetch_status", ""),
            )
            for row in pipeline.get("funds", [])
        ],
    )
    connection.executemany(
        """
        INSERT INTO holdings (
            run_id, fund_code, fund_name, manager, report_date, rank, stock_code, stock_name, shares_10k,
            market_value_10k, nav_ratio, market, duplicate_group, representative, source_url
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                run_id, row["fund_code"], row["fund_name"], row["manager"], row["report_date"], row["rank"],
                row["stock_code"], row["stock_name"], row.get("shares_10k"), row.get("market_value_10k"),
                row.get("nav_ratio"), row.get("market", ""), row.get("duplicate_group", ""), row.get("representative", ""), row.get("source_url", ""),
            )
            for row in pipeline.get("all_holdings", [])
        ],
    )
    connection.executemany(
        """
        INSERT INTO run_issues (run_id, severity, category, fund_code, fund_name, manager, report_date, message, source_url, action)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (run_id, row["severity"], row["category"], row.get("fund_code", ""), row.get("fund_name", ""), row.get("manager", ""), row.get("report_date", ""), row.get("message", ""), row.get("source_url", ""), row.get("action", ""))
            for row in pipeline.get("issues", [])
        ],
    )
    sources = list(pipeline.get("sources", []))
    if industry:
        sources.extend(industry.get("industry_sources", []))
    connection.executemany(
        "INSERT INTO run_sources (run_id, item, url, note) VALUES (?,?,?,?)",
        [(run_id, row.get("item", ""), row.get("url", ""), row.get("note", "")) for row in sources],
    )
    if not industry:
        return
    connection.executemany(
        """
        INSERT INTO stock_industry (
            run_id, stock_code, stock_name, market, sw_level1, sw_level2, sw_level2_code,
            classification_status, source_url, industry_source_id, industry_snapshot_date
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                run_id, row["stock_code"], row["stock_name"], row.get("market", ""), row.get("sw_level1", ""),
                row.get("sw_level2", ""), row.get("sw_level2_code", ""), row.get("classification_status", ""),
                row.get("source_url", ""), row.get("industry_source_id", ""), row.get("industry_snapshot_date", ""),
            )
            for row in industry.get("stock_industry_mapping", [])
        ],
    )
    connection.executemany(
        """
        INSERT INTO holding_industries (
            run_id, fund_code, rank, stock_code, representative, sw_level1, sw_level2, sw_level2_code,
            industry_snapshot_date, industry_status, industry_source_id, industry_source_url
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                run_id, row["fund_code"], row["rank"], row["stock_code"], row.get("representative", ""),
                row.get("sw_level1", ""), row.get("sw_level2", ""), row.get("sw_level2_code", ""),
                row.get("industry_snapshot_date", ""), row.get("industry_status", ""), row.get("industry_source_id", ""), row.get("industry_source_url", ""),
            )
            for row in industry.get("all_holdings_industry", [])
        ],
    )
    connection.executemany(
        """
        INSERT INTO industry_summary (run_id, fund_code, fund_name, sw_level1, holding_count, market_value_10k, nav_ratio)
        VALUES (?,?,?,?,?,?,?)
        """,
        [
            (run_id, row["fund_code"], row["fund_name"], row["sw_level1"], row["holding_count"], row["market_value_10k"], row["nav_ratio"])
            for row in industry.get("industry_summary", [])
        ],
    )
    connection.executemany(
        """
        INSERT INTO industry_issues (run_id, severity, category, stock_code, stock_name, message, source_url, action)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        [
            (run_id, row["severity"], row["category"], row.get("stock_code", ""), row.get("stock_name", ""), row.get("message", ""), row.get("source_url", ""), row.get("action", ""))
            for row in industry.get("industry_issues", [])
        ],
    )


def _insert_comparison_children(connection: sqlite3.Connection, comparison_id: int, data: dict[str, Any]) -> None:
    company_columns = [
        "change_type", "stock_code", "stock_name", "market", "sw_level1", "previous_fund_count", "current_fund_count",
        "previous_fund_codes", "current_fund_codes", "previous_shares_10k", "current_shares_10k", "shares_change_10k",
        "shares_change_pct", "previous_market_value_10k", "current_market_value_10k", "market_value_change_10k",
        "market_value_change_pct", "previous_nav_ratio_sum", "current_nav_ratio_sum", "nav_ratio_change",
        "previous_best_rank", "current_best_rank", "rank_improvement",
    ]
    connection.executemany(
        f"INSERT INTO company_changes (comparison_id,{','.join(company_columns)}) VALUES ({','.join('?' for _ in range(len(company_columns) + 1))})",
        [(comparison_id, *[row.get(column) for column in company_columns]) for row in data.get("company_changes", [])],
    )
    fund_columns = [
        "change_type", "fund_code", "fund_name", "stock_code", "stock_name", "sw_level1", "previous_rank", "current_rank",
        "rank_improvement", "previous_shares_10k", "current_shares_10k", "shares_change_10k", "shares_change_pct",
        "previous_market_value_10k", "current_market_value_10k", "market_value_change_10k", "previous_nav_ratio",
        "current_nav_ratio", "nav_ratio_change",
    ]
    connection.executemany(
        f"INSERT INTO fund_stock_changes (comparison_id,{','.join(fund_columns)}) VALUES ({','.join('?' for _ in range(len(fund_columns) + 1))})",
        [(comparison_id, *[row.get(column) for column in fund_columns]) for row in data.get("fund_stock_changes", [])],
    )
    industry_columns = [
        "change_type", "sw_level1", "previous_fund_count", "current_fund_count", "previous_fund_codes", "current_fund_codes",
        "previous_holding_count", "current_holding_count", "holding_count_change", "previous_market_value_10k",
        "current_market_value_10k", "market_value_change_10k", "previous_nav_ratio_sum", "current_nav_ratio_sum", "nav_ratio_change",
    ]
    connection.executemany(
        f"INSERT INTO industry_changes (comparison_id,{','.join(industry_columns)}) VALUES ({','.join('?' for _ in range(len(industry_columns) + 1))})",
        [(comparison_id, *[row.get(column) for column in industry_columns]) for row in data.get("industry_changes", [])],
    )
    connection.executemany(
        "INSERT INTO comparison_checks (comparison_id, item, actual_json, expected_json, status, note) VALUES (?,?,?,?,?,?)",
        [
            (comparison_id, row["item"], json.dumps(row.get("actual"), ensure_ascii=False), json.dumps(row.get("expected"), ensure_ascii=False), row["status"], row.get("note", ""))
            for row in data.get("checks", [])
        ],
    )
    connection.executemany(
        "INSERT INTO comparison_rules (comparison_id, item, rule) VALUES (?,?,?)",
        [(comparison_id, row["item"], row["rule"]) for row in data.get("rules", [])],
    )
    connection.executemany(
        "INSERT INTO comparison_sources (comparison_id, item, path, report_date) VALUES (?,?,?,?)",
        [(comparison_id, row.get("item", ""), row.get("path", ""), row.get("report_date", "")) for row in data.get("sources", [])],
    )


def _source_info(path: Path | None) -> dict[str, str]:
    if path is None:
        return {"path": "", "sha256": ""}
    resolved = path.resolve()
    return {"path": str(resolved), "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest()}


def _manager_name(pipeline: dict[str, Any]) -> str:
    managers = sorted({str(row.get("manager", "")) for row in pipeline.get("funds", []) if row.get("manager")})
    return "、".join(managers) or str(pipeline.get("summary", {}).get("manager", ""))


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS quarter_runs (
            run_id INTEGER PRIMARY KEY,
            manager TEXT NOT NULL,
            report_date TEXT NOT NULL,
            status TEXT NOT NULL,
            input_funds INTEGER NOT NULL,
            selected_funds INTEGER NOT NULL,
            successful_funds INTEGER NOT NULL,
            formal_funds INTEGER NOT NULL,
            raw_holding_rows INTEGER NOT NULL,
            formal_holding_rows INTEGER NOT NULL,
            issue_count INTEGER NOT NULL,
            error_count INTEGER NOT NULL,
            warning_count INTEGER NOT NULL,
            success_rate REAL NOT NULL,
            duplicate_product_count INTEGER NOT NULL,
            industry_snapshot_date TEXT NOT NULL DEFAULT '',
            industry_standard TEXT NOT NULL DEFAULT '',
            industry_coverage REAL,
            historical_industry_point_in_time INTEGER NOT NULL DEFAULT 0,
            pipeline_source_path TEXT NOT NULL DEFAULT '',
            pipeline_source_sha256 TEXT NOT NULL DEFAULT '',
            industry_source_path TEXT NOT NULL DEFAULT '',
            industry_source_sha256 TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(manager, report_date)
        );
        CREATE TABLE IF NOT EXISTS funds (
            run_id INTEGER NOT NULL REFERENCES quarter_runs(run_id) ON DELETE CASCADE,
            fund_code TEXT NOT NULL,
            fund_name TEXT NOT NULL,
            manager TEXT NOT NULL,
            fund_type TEXT NOT NULL DEFAULT '',
            inception_date TEXT NOT NULL DEFAULT '',
            selected INTEGER NOT NULL,
            selection_reason TEXT NOT NULL DEFAULT '',
            verified_manager TEXT NOT NULL DEFAULT '',
            manager_status TEXT NOT NULL DEFAULT '',
            manager_source_url TEXT NOT NULL DEFAULT '',
            fetch_status TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(run_id, fund_code)
        );
        CREATE TABLE IF NOT EXISTS holdings (
            run_id INTEGER NOT NULL REFERENCES quarter_runs(run_id) ON DELETE CASCADE,
            fund_code TEXT NOT NULL,
            fund_name TEXT NOT NULL,
            manager TEXT NOT NULL,
            report_date TEXT NOT NULL,
            rank INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            shares_10k REAL,
            market_value_10k REAL,
            nav_ratio REAL,
            market TEXT NOT NULL DEFAULT '',
            duplicate_group TEXT NOT NULL DEFAULT '',
            representative TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(run_id, fund_code, rank, stock_code)
        );
        CREATE TABLE IF NOT EXISTS run_issues (
            issue_id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES quarter_runs(run_id) ON DELETE CASCADE,
            severity TEXT NOT NULL,
            category TEXT NOT NULL,
            fund_code TEXT NOT NULL DEFAULT '',
            fund_name TEXT NOT NULL DEFAULT '',
            manager TEXT NOT NULL DEFAULT '',
            report_date TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS run_sources (
            source_id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES quarter_runs(run_id) ON DELETE CASCADE,
            item TEXT NOT NULL,
            url TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS stock_industry (
            run_id INTEGER NOT NULL REFERENCES quarter_runs(run_id) ON DELETE CASCADE,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            market TEXT NOT NULL DEFAULT '',
            sw_level1 TEXT NOT NULL DEFAULT '',
            sw_level2 TEXT NOT NULL DEFAULT '',
            sw_level2_code TEXT NOT NULL DEFAULT '',
            classification_status TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            industry_source_id TEXT NOT NULL DEFAULT '',
            industry_snapshot_date TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(run_id, stock_code)
        );
        CREATE TABLE IF NOT EXISTS holding_industries (
            run_id INTEGER NOT NULL REFERENCES quarter_runs(run_id) ON DELETE CASCADE,
            fund_code TEXT NOT NULL,
            rank INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            representative TEXT NOT NULL DEFAULT '',
            sw_level1 TEXT NOT NULL DEFAULT '',
            sw_level2 TEXT NOT NULL DEFAULT '',
            sw_level2_code TEXT NOT NULL DEFAULT '',
            industry_snapshot_date TEXT NOT NULL DEFAULT '',
            industry_status TEXT NOT NULL DEFAULT '',
            industry_source_id TEXT NOT NULL DEFAULT '',
            industry_source_url TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(run_id, fund_code, rank, stock_code)
        );
        CREATE TABLE IF NOT EXISTS industry_summary (
            run_id INTEGER NOT NULL REFERENCES quarter_runs(run_id) ON DELETE CASCADE,
            fund_code TEXT NOT NULL,
            fund_name TEXT NOT NULL,
            sw_level1 TEXT NOT NULL,
            holding_count INTEGER NOT NULL,
            market_value_10k REAL NOT NULL,
            nav_ratio REAL NOT NULL,
            PRIMARY KEY(run_id, fund_code, sw_level1)
        );
        CREATE TABLE IF NOT EXISTS industry_issues (
            issue_id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES quarter_runs(run_id) ON DELETE CASCADE,
            severity TEXT NOT NULL,
            category TEXT NOT NULL,
            stock_code TEXT NOT NULL DEFAULT '',
            stock_name TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS comparisons (
            comparison_id INTEGER PRIMARY KEY,
            manager TEXT NOT NULL,
            previous_report_date TEXT NOT NULL,
            current_report_date TEXT NOT NULL,
            previous_run_id INTEGER NOT NULL REFERENCES quarter_runs(run_id),
            current_run_id INTEGER NOT NULL REFERENCES quarter_runs(run_id),
            status TEXT NOT NULL,
            company_union_count INTEGER NOT NULL,
            new_company_count INTEGER NOT NULL,
            exited_company_count INTEGER NOT NULL,
            increased_company_count INTEGER NOT NULL,
            decreased_company_count INTEGER NOT NULL,
            unchanged_company_count INTEGER NOT NULL,
            fund_stock_change_count INTEGER NOT NULL,
            industry_union_count INTEGER NOT NULL,
            new_industry_count INTEGER NOT NULL,
            exited_industry_count INTEGER NOT NULL,
            increased_industry_count INTEGER NOT NULL,
            decreased_industry_count INTEGER NOT NULL,
            industry_snapshot_date TEXT NOT NULL,
            historical_industry_point_in_time INTEGER NOT NULL,
            source_path TEXT NOT NULL DEFAULT '',
            source_sha256 TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(manager, previous_report_date, current_report_date)
        );
        CREATE TABLE IF NOT EXISTS company_changes (
            comparison_id INTEGER NOT NULL REFERENCES comparisons(comparison_id) ON DELETE CASCADE,
            change_type TEXT NOT NULL, stock_code TEXT NOT NULL, stock_name TEXT NOT NULL, market TEXT NOT NULL,
            sw_level1 TEXT NOT NULL, previous_fund_count INTEGER NOT NULL, current_fund_count INTEGER NOT NULL,
            previous_fund_codes TEXT NOT NULL, current_fund_codes TEXT NOT NULL, previous_shares_10k REAL NOT NULL,
            current_shares_10k REAL NOT NULL, shares_change_10k REAL NOT NULL, shares_change_pct REAL,
            previous_market_value_10k REAL NOT NULL, current_market_value_10k REAL NOT NULL,
            market_value_change_10k REAL NOT NULL, market_value_change_pct REAL, previous_nav_ratio_sum REAL NOT NULL,
            current_nav_ratio_sum REAL NOT NULL, nav_ratio_change REAL NOT NULL, previous_best_rank INTEGER,
            current_best_rank INTEGER, rank_improvement INTEGER,
            PRIMARY KEY(comparison_id, stock_code)
        );
        CREATE TABLE IF NOT EXISTS fund_stock_changes (
            comparison_id INTEGER NOT NULL REFERENCES comparisons(comparison_id) ON DELETE CASCADE,
            change_type TEXT NOT NULL, fund_code TEXT NOT NULL, fund_name TEXT NOT NULL, stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL, sw_level1 TEXT NOT NULL, previous_rank INTEGER, current_rank INTEGER,
            rank_improvement INTEGER, previous_shares_10k REAL NOT NULL, current_shares_10k REAL NOT NULL,
            shares_change_10k REAL NOT NULL, shares_change_pct REAL, previous_market_value_10k REAL NOT NULL,
            current_market_value_10k REAL NOT NULL, market_value_change_10k REAL NOT NULL,
            previous_nav_ratio REAL NOT NULL, current_nav_ratio REAL NOT NULL, nav_ratio_change REAL NOT NULL,
            PRIMARY KEY(comparison_id, fund_code, stock_code)
        );
        CREATE TABLE IF NOT EXISTS industry_changes (
            comparison_id INTEGER NOT NULL REFERENCES comparisons(comparison_id) ON DELETE CASCADE,
            change_type TEXT NOT NULL, sw_level1 TEXT NOT NULL, previous_fund_count INTEGER NOT NULL,
            current_fund_count INTEGER NOT NULL, previous_fund_codes TEXT NOT NULL, current_fund_codes TEXT NOT NULL,
            previous_holding_count INTEGER NOT NULL, current_holding_count INTEGER NOT NULL,
            holding_count_change INTEGER NOT NULL, previous_market_value_10k REAL NOT NULL,
            current_market_value_10k REAL NOT NULL, market_value_change_10k REAL NOT NULL,
            previous_nav_ratio_sum REAL NOT NULL, current_nav_ratio_sum REAL NOT NULL, nav_ratio_change REAL NOT NULL,
            PRIMARY KEY(comparison_id, sw_level1)
        );
        CREATE TABLE IF NOT EXISTS comparison_checks (
            check_id INTEGER PRIMARY KEY,
            comparison_id INTEGER NOT NULL REFERENCES comparisons(comparison_id) ON DELETE CASCADE,
            item TEXT NOT NULL, actual_json TEXT NOT NULL, expected_json TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS comparison_rules (
            rule_id INTEGER PRIMARY KEY,
            comparison_id INTEGER NOT NULL REFERENCES comparisons(comparison_id) ON DELETE CASCADE,
            item TEXT NOT NULL, rule TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS comparison_sources (
            source_id INTEGER PRIMARY KEY,
            comparison_id INTEGER NOT NULL REFERENCES comparisons(comparison_id) ON DELETE CASCADE,
            item TEXT NOT NULL, path TEXT NOT NULL DEFAULT '', report_date TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_holdings_stock ON holdings(stock_code, report_date);
        CREATE INDEX IF NOT EXISTS idx_holdings_fund ON holdings(fund_code, report_date);
        CREATE INDEX IF NOT EXISTS idx_industry_level1 ON stock_industry(sw_level1, industry_snapshot_date);
        CREATE INDEX IF NOT EXISTS idx_company_change_type ON company_changes(change_type);
        CREATE VIEW IF NOT EXISTS v_formal_holdings AS
            SELECT r.manager, r.report_date, h.*
            FROM holdings h JOIN quarter_runs r ON r.run_id = h.run_id
            WHERE h.representative = '是';
        CREATE VIEW IF NOT EXISTS v_company_changes AS
            SELECT c.manager, c.previous_report_date, c.current_report_date, x.*
            FROM company_changes x JOIN comparisons c ON c.comparison_id = x.comparison_id;
        """
    )
