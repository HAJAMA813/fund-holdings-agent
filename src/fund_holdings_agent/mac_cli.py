from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .excel_reports import audit_workbook, build_three_quarter_brief_report
from .portfolio import ManagerEntry, atomic_write_json, company_directory_name, read_manager_roster
from .quarterly_cli import beijing_today, latest_closed_quarter, quarter_label
from .three_quarter import build_three_quarter_dataset, discover_quarter_inputs, save_three_quarter_dataset, three_quarter_dates


CONFIG_VERSION = 1


@dataclass(frozen=True)
class MacAgentPaths:
    app_home: Path
    report_root: Path

    @property
    def config_path(self) -> Path:
        return self.app_home / "config.json"

    @property
    def portfolio_root(self) -> Path:
        return self.app_home / "portfolio"

    @property
    def state_root(self) -> Path:
        return self.app_home / "state"

    @property
    def log_root(self) -> Path:
        return self.app_home / "logs"


def default_paths() -> MacAgentPaths:
    app_home = Path(
        os.environ.get(
            "FUND_AGENT_APP_HOME",
            str(Path.home() / "Library" / "Application Support" / "FundHoldingsAgent"),
        )
    ).expanduser()
    report_root = Path(
        os.environ.get(
            "FUND_AGENT_REPORT_ROOT",
            str(Path.home() / "Documents" / "FundHoldingsAgent"),
        )
    ).expanduser()
    return MacAgentPaths(app_home.resolve(), report_root.resolve())


def discover_project_root(start: Path | None = None) -> Path:
    candidates = []
    if os.environ.get("FUND_AGENT_PROJECT_ROOT"):
        candidates.append(Path(os.environ["FUND_AGENT_PROJECT_ROOT"]))
    if start is not None:
        candidates.extend([start, *start.parents])
    module_root = Path(__file__).resolve().parents[2]
    candidates.extend([Path.cwd(), *Path.cwd().parents, module_root])
    for candidate in candidates:
        if (candidate / "pyproject.toml").exists() and (candidate / "scripts").is_dir():
            return candidate.resolve()
    raise FileNotFoundError("找不到项目目录；请在代码仓库内运行，或设置 FUND_AGENT_PROJECT_ROOT")


def initialize(project_root: Path, paths: MacAgentPaths) -> dict[str, Any]:
    project_root = project_root.resolve()
    inputs = {
        "roster": project_root / "data" / "managers_portfolio.csv",
        "personnel": project_root / "data" / "personnel_internal_20260616.csv",
        "candidate_confirmations": project_root / "data" / "resource_candidate_confirmations.csv",
    }
    missing = [str(path) for path in inputs.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("初始化缺少业务输入：" + "；".join(missing))
    for directory in (paths.app_home, paths.portfolio_root, paths.state_root, paths.log_root, paths.report_root):
        directory.mkdir(parents=True, exist_ok=True)
    config = {
        "config_version": CONFIG_VERSION,
        "project_root": str(project_root),
        "roster": str(inputs["roster"]),
        "personnel": str(inputs["personnel"]),
        "candidate_confirmations": str(inputs["candidate_confirmations"]),
        "portfolio_root": str(paths.portfolio_root),
        "report_root": str(paths.report_root),
        "workers": 4,
        "retries": 3,
        "timeout": 20,
        "sleep": 0.3,
    }
    atomic_write_json(paths.config_path, config)
    return config


def load_config(paths: MacAgentPaths) -> dict[str, Any]:
    if not paths.config_path.exists():
        raise FileNotFoundError(f"尚未初始化：{paths.config_path}；请先运行 fund-agent init")
    config = json.loads(paths.config_path.read_text(encoding="utf-8"))
    if config.get("config_version") != CONFIG_VERSION:
        raise ValueError("配置版本不兼容，请重新运行 fund-agent init")
    return config


def doctor(config: dict[str, Any], *, check_network: bool = False) -> dict[str, Any]:
    root = Path(config["project_root"])
    checks: list[dict[str, str]] = []

    def add(name: str, passed: bool, evidence: str, *, warning: bool = False) -> None:
        status = "PASS" if passed else ("WARN" if warning else "FAIL")
        checks.append({"name": name, "status": status, "evidence": evidence})

    add("macOS运行系统", platform.system() == "Darwin", platform.platform())
    add("Python版本", sys.version_info >= (3, 11), sys.version.split()[0])
    for key in ("roster", "personnel", "candidate_confirmations"):
        path = Path(config[key])
        add(f"业务输入 {key}", path.exists(), str(path))
    try:
        roster = read_manager_roster(Path(config["roster"]))
        add("经理名单可读取", bool(roster), f"启用 {len(roster)} 人")
    except (OSError, ValueError) as exc:
        add("经理名单可读取", False, str(exc))
    excel_module = root / "src" / "fund_holdings_agent" / "excel_reports.py"
    add("纯Python Excel模块存在", excel_module.exists(), str(excel_module))
    try:
        import openpyxl

        add("Excel生成组件可加载", True, f"openpyxl {openpyxl.__version__}")
    except ImportError as exc:
        add("Excel生成组件可加载", False, str(exc))
    pdf_module = root / "src" / "fund_holdings_agent" / "pdf_reports.py"
    add("纯Python PDF模块存在", pdf_module.exists(), str(pdf_module))
    try:
        import reportlab

        add("PDF生成组件可加载", True, f"reportlab {reportlab.Version}")
    except ImportError as exc:
        add("PDF生成组件可加载", False, str(exc))
    try:
        from .pdf_reports import find_pdf_font

        font_path = find_pdf_font()
        add("PDF中文字体可嵌入", font_path is not None, str(font_path or "未找到 Arial Unicode.ttf"))
    except ImportError as exc:
        add("PDF中文字体可嵌入", False, str(exc))
    report_ok, report_evidence = _probe_writable(Path(config["report_root"]))
    add("报告目录可写", report_ok, report_evidence)
    portfolio_ok, portfolio_evidence = _probe_writable(Path(config["portfolio_root"]))
    add("数据目录可写", portfolio_ok, portfolio_evidence)
    if check_network:
        for url in ("https://fund.eastmoney.com/", "https://fundf10.eastmoney.com/"):
            try:
                request = Request(url, headers={"User-Agent": "Mozilla/5.0 fund-agent-doctor"})
                with urlopen(request, timeout=10) as response:
                    status = int(getattr(response, "status", 200))
                    response.read(128)
                add(f"网络 {url}", 200 <= status < 400, f"HTTP {status}")
            except OSError as exc:
                add(f"网络 {url}", False, str(exc))
    else:
        checks.append({"name": "真实网络探测", "status": "SKIP", "evidence": "使用 --check-network 后才访问公开网站"})
    failed = sum(row["status"] == "FAIL" for row in checks)
    warnings = sum(row["status"] in {"WARN", "SKIP"} for row in checks)
    return {
        "status": "BLOCKED" if failed else ("RUNNABLE_WITH_WARNINGS" if warnings else "RUNNABLE"),
        "failed_count": failed,
        "warning_or_skipped_count": warnings,
        "checks": checks,
        "note": "本检查判断当前Mac的本地运行条件；Excel和PDF均由纯Python生成，不依赖Codex、Node或外部符号链接。",
    }


def _probe_writable(directory: Path) -> tuple[bool, str]:
    probe = directory / ".fund_agent_probe"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        return probe.read_text(encoding="utf-8") == "ok", str(directory)
    except OSError as exc:
        return False, str(exc)
    finally:
        probe.unlink(missing_ok=True)


def select_roster(
    roster_path: Path,
    destination: Path,
    *,
    companies: list[str] | None = None,
    managers: list[str] | None = None,
) -> list[ManagerEntry]:
    entries = read_manager_roster(roster_path)
    company_filters = {value.strip() for value in companies or [] if value.strip()}
    manager_filters = {value.strip() for value in managers or [] if value.strip()}
    selected = [
        row
        for row in entries
        if (not company_filters or row.company in company_filters or any(value in row.company for value in company_filters))
        and (not manager_filters or row.manager in manager_filters)
    ]
    if not selected:
        raise ValueError("筛选后没有基金经理，请检查 --company 或 --manager")
    _write_roster_entries(selected, destination)
    return selected


def _write_roster_entries(entries: list[ManagerEntry], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["company", "manager", "manager_id", "active"])
        writer.writeheader()
        for row in entries:
            writer.writerow({"company": row.company, "manager": row.manager, "manager_id": row.manager_id, "active": "yes"})
    temporary.replace(destination)
    return destination


def build_portfolio_command(
    config: dict[str, Any],
    selected_roster: Path,
    *,
    report_date: str | None,
    retry_errors: bool,
    refresh: bool,
    data_only: bool,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "fund_holdings_agent.portfolio_cli",
        "--roster",
        str(selected_roster),
        "--output-root",
        str(config["portfolio_root"]),
        "--company-report-output-root",
        str(config["report_root"]),
        "--personnel",
        str(config["personnel"]),
        "--candidate-confirmations",
        str(config["candidate_confirmations"]),
        "--workers",
        str(config.get("workers", 4)),
        "--retries",
        str(config.get("retries", 3)),
        "--timeout",
        str(config.get("timeout", 20)),
        "--sleep",
        str(config.get("sleep", 0.3)),
        "--skip-reports",
        "--friendly-output",
    ]
    if report_date:
        dt.date.fromisoformat(report_date)
        command.extend(["--report-date", report_date])
    if retry_errors:
        command.append("--retry-errors")
    if refresh:
        command.append("--refresh")
    if data_only:
        command.append("--skip-company-report")
    return command


def run_portfolio(
    config: dict[str, Any],
    paths: MacAgentPaths,
    *,
    report_date: str | None,
    companies: list[str] | None,
    managers: list[str] | None,
    retry_errors: bool,
    refresh: bool,
    data_only: bool,
) -> int:
    if not data_only:
        preflight = doctor(config)
        if preflight["status"] == "BLOCKED":
            _print_doctor(preflight)
            print("运行已阻止：请先修复 FAIL 项；如只需结构化数据，可显式使用 --data-only。", file=sys.stderr)
            return 3
    selected_path = paths.state_root / "selected_managers.csv"
    selected = select_roster(Path(config["roster"]), selected_path, companies=companies, managers=managers)
    names = "、".join(row.manager for row in selected)
    print(f"准备运行：{len(selected)} 位经理（{names}）", flush=True)
    print(f"正式Excel目录：{config['report_root']}", flush=True)
    print("运行期间无需输入数字；需要停止请按 Control+C。", flush=True)
    command = build_portfolio_command(
        config,
        selected_path,
        report_date=report_date,
        retry_errors=retry_errors,
        refresh=refresh,
        data_only=data_only,
    )
    completed = subprocess.run(command, cwd=config["project_root"], stdin=subprocess.DEVNULL)
    _discard_pending_input()
    return completed.returncode


def _quarter_input_ready(config: dict[str, Any], entry: ManagerEntry, report_date: dt.date) -> bool:
    directory = (
        Path(config["portfolio_root"])
        / company_directory_name(entry.company)
        / f"{entry.manager}_{quarter_label(report_date)}"
    )
    required = [directory / "manager_fund_pool_data.json", directory / "industry_analysis_data.json"]
    if not all(path.exists() and path.stat().st_size > 0 for path in required):
        return False
    manifest_path = directory / "batch_manifest.json"
    if not manifest_path.exists():
        return True
    try:
        status = json.loads(manifest_path.read_text(encoding="utf-8")).get("overall_status")
    except (OSError, json.JSONDecodeError):
        return False
    return status in {"completed", "completed_with_errors"}


def run_three_quarter_brief(
    config: dict[str, Any],
    paths: MacAgentPaths,
    *,
    end_report_date: str | None,
    companies: list[str] | None,
    managers: list[str] | None,
    refresh: bool,
    output_format: str = "excel",
) -> int:
    if output_format not in {"excel", "pdf", "both"}:
        raise ValueError("输出格式必须是 excel、pdf 或 both")
    preflight = doctor(config)
    if preflight["status"] == "BLOCKED":
        _print_doctor(preflight)
        print("运行已阻止：请先修复 FAIL 项。", file=sys.stderr)
        return 3

    end_date = dt.date.fromisoformat(end_report_date) if end_report_date else latest_closed_quarter(beijing_today())
    dates = three_quarter_dates(end_date)
    selected_path = paths.state_root / "selected_three_quarter_managers.csv"
    selected = select_roster(Path(config["roster"]), selected_path, companies=companies, managers=managers)
    span = f"{quarter_label(dates[0])}-{quarter_label(dates[-1])}"
    print(f"准备生成最近三季度简报：{span}；{len(selected)} 位经理", flush=True)
    print("系统会复用已有季度，只补跑缺失或未完成季度。", flush=True)

    acceptable_codes = {0, 3}
    for report_date in dates:
        missing = [entry for entry in selected if not _quarter_input_ready(config, entry, report_date)]
        if not missing:
            print(f"✓ {quarter_label(report_date)}：所需数据已存在，直接复用", flush=True)
            continue
        missing_roster = paths.state_root / f"three_quarter_missing_{quarter_label(report_date)}.csv"
        _write_roster_entries(missing, missing_roster)
        names = "、".join(entry.manager for entry in missing)
        print(f"· {quarter_label(report_date)}：补跑 {len(missing)} 位经理（{names}）", flush=True)
        command = build_portfolio_command(
            config,
            missing_roster,
            report_date=report_date.isoformat(),
            retry_errors=True,
            refresh=refresh,
            data_only=True,
        )
        completed = subprocess.run(command, cwd=config["project_root"], stdin=subprocess.DEVNULL)
        _discard_pending_input()
        if completed.returncode not in acceptable_codes:
            if completed.returncode == 2:
                print(f"{quarter_label(report_date)} 尚未披露完整，暂不生成三季度正式简报。", file=sys.stderr)
            else:
                print(f"{quarter_label(report_date)} 补跑失败，退出码：{completed.returncode}", file=sys.stderr)
            return completed.returncode

    failed = 0
    for entry in selected:
        company_label = company_directory_name(entry.company)
        manager_root = Path(config["portfolio_root"]) / company_label
        data_root = manager_root / "three_quarter_briefs"
        data_path = data_root / f"{entry.manager}_{span}_三季度持仓数据.json"
        excel_path = (
            Path(config["report_root"])
            / company_label
            / f"{company_label}_{entry.manager}_{span}_三季度前十大持仓简报.xlsx"
        )
        pdf_path = (
            Path(config["report_root"])
            / company_label
            / f"{company_label}_{entry.manager}_{span}_三季度持仓分析报告.pdf"
        )
        try:
            inputs = discover_quarter_inputs(manager_root, entry.manager, end_date)
            data = build_three_quarter_dataset(inputs)
            save_three_quarter_dataset(data, data_path)
            created: list[str] = []
            if output_format in {"excel", "both"}:
                build_three_quarter_brief_report(data_path, excel_path)
                audit = audit_workbook(excel_path, expected_sheets=["01_三季持仓", "99_说明异常"])
                if not audit["valid"]:
                    raise ValueError(f"Excel结构校验失败：{audit}")
                created.append(f"Excel {excel_path}")
            if output_format in {"pdf", "both"}:
                from .pdf_reports import build_three_quarter_pdf_report

                build_three_quarter_pdf_report(data_path, pdf_path)
                if not pdf_path.exists() or pdf_path.stat().st_size < 1024 or not pdf_path.read_bytes().startswith(b"%PDF"):
                    raise ValueError("PDF结构校验失败")
                created.append(f"PDF {pdf_path}")
            print(f"✓ {entry.manager}：{'；'.join(created)}", flush=True)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            failed += 1
            print(f"× {entry.manager}：{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    if failed:
        print(f"三季度简报结束：成功 {len(selected) - failed}，失败 {failed}", file=sys.stderr)
        return 1
    print(f"三季度简报完成：{len(selected)} 份；结果目录：{config['report_root']}", flush=True)
    print("简报生成使用确定性规则；如需自然语言解读，请在菜单选择「自然语言问答」或配置 DeepSeek 后自动解读。", flush=True)
    return 0


def _discard_pending_input() -> None:
    try:
        import termios
    except ImportError:
        return
    try:
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except (OSError, termios.error):
        pass


def list_status(config: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path(config["portfolio_root"])
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("portfolio_summary_*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(
            {
                "quarter": path.stem.removeprefix("portfolio_summary_"),
                "report_date": data.get("report_date", ""),
                "status": data.get("overall_status", ""),
                "manager_count": len(data.get("manager_results", [])),
                "summary": data.get("notification_summary", ""),
                "path": str(path),
            }
        )
    return rows


def list_results(config: dict[str, Any]) -> list[Path]:
    root = Path(config["report_root"])
    if not root.exists():
        return []
    return sorted(
        [*root.rglob("*.xlsx"), *root.rglob("*.pdf")],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def list_manager_runs(config: dict[str, Any]) -> list[dict[str, str]]:
    root = Path(config["portfolio_root"])
    rows: list[dict[str, str]] = []
    for path in root.rglob("batch_manifest.json") if root.exists() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        running_stage = next(
            (name for name, record in data.get("stages", {}).items() if record.get("status") in {"running", "failed", "waiting"}),
            "",
        )
        rows.append({
            "manager": str(data.get("manager", "")),
            "report_date": str(data.get("report_date", "")),
            "status": str(data.get("overall_status", "")),
            "stage": running_stage,
            "updated_at": str(data.get("updated_at", "")),
        })
    return sorted(rows, key=lambda row: row["updated_at"], reverse=True)


def _scope_manager_names(config: dict[str, Any], companies: list[str] | None, managers: list[str] | None) -> list[str]:
    entries = read_manager_roster(Path(config["roster"]))
    company_filters = {value.strip() for value in companies or [] if value.strip()}
    manager_filters = {value.strip() for value in managers or [] if value.strip()}
    return [
        row.manager
        for row in entries
        if (not company_filters or row.company in company_filters or any(value in row.company for value in company_filters))
        and (not manager_filters or row.manager in manager_filters)
    ]


def _portfolio_roots(config: dict[str, Any]) -> list[Path]:
    """LLM 只读解读的数据目录候选：优先 Mac 用户目录，回退到项目开发工作区。"""
    roots = [Path(config["portfolio_root"])]
    project_root = Path(config.get("project_root", ""))
    if project_root.is_dir():
        dev_root = project_root / "outputs" / "quarterly" / "portfolio"
        if dev_root not in roots:
            roots.append(dev_root)
    return [root for root in roots if str(root)]


def _llm_interpret_quarter(config: dict[str, Any], manager: str, report_date: str, question: str | None = None) -> bool:
    """对某经理某季度做自然语言解读；未配置 key 或失败时返回 False，不影响主流程。"""
    from .llm_agent import answer_question, llm_available

    if not llm_available():
        return False
    question = question or "请概括该经理本季度的持仓、申万行业暴露、研究资源需求、季度变化和异常，并说明需要人工关注的事项。"
    errors: list[str] = []
    for root in _portfolio_roots(config):
        try:
            result = answer_question(
                manager=manager,
                report_date=report_date,
                question=question,
                portfolio_root=root,
                roster_path=Path(config["roster"]),
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        except RuntimeError as exc:
            print(f"（大模型调用失败：{exc}）", file=sys.stderr, flush=True)
            return False
        print("\n=== 大模型解读（基于已验证季度数据）===")
        print(result["answer"])
        print(f"（模式：{result['mode']}；来源文件 {len(result['sources'])} 个）")
        return True
    print(f"（未能生成大模型解读：{'；'.join(errors)}）", file=sys.stderr, flush=True)
    return False


def _llm_interpret_status(config: dict[str, Any]) -> bool:
    """对最近运行状态做一句话解读（哪些完成/等待/失败、下一步）。"""
    from .llm_agent import ask_grounded, llm_available

    if not llm_available():
        return False
    statuses: list[dict[str, Any]] = []
    runs: list[dict[str, str]] = []
    for root in _portfolio_roots(config):
        scoped = {**config, "portfolio_root": str(root)}
        statuses.extend(list_status(scoped))
        runs.extend(list_manager_runs(scoped))
    if not statuses and not runs:
        return False
    evidence = {"portfolio_summaries": statuses, "manager_runs": runs[:30]}
    try:
        answer, used = ask_grounded(
            "请总结最近的运行状态：哪些经理已完成、等待披露或失败，需要重试或人工处理的事项是什么？",
            evidence,
        )
    except RuntimeError as exc:
        print(f"（大模型状态解读失败：{exc}）", file=sys.stderr, flush=True)
        return False
    if not used or not answer:
        return False
    print("\n=== 大模型状态解读 ===")
    print(answer)
    return True


def _prompt_manager_name(config: dict[str, Any]) -> str | None:
    entries = read_manager_roster(Path(config["roster"]))
    companies = sorted({row.company for row in entries})
    print("\n请选择基金公司：")
    for index, company in enumerate(companies, start=1):
        print(f"{index}. {company}")
    print("0. 返回")
    raw = input("请选择：").strip()
    if raw == "0":
        return None
    if not raw.isdigit() or not 1 <= int(raw) <= len(companies):
        raise ValueError("基金公司选项无效")
    company = companies[int(raw) - 1]
    managers = [row.manager for row in entries if row.company == company]
    print(f"\n请选择 {company} 的基金经理：")
    for index, manager in enumerate(managers, start=1):
        print(f"{index}. {manager}")
    print("0. 返回")
    raw = input("请选择：").strip()
    if raw == "0":
        return None
    if not raw.isdigit() or not 1 <= int(raw) <= len(managers):
        raise ValueError("基金经理选项无效")
    return managers[int(raw) - 1]


def _resolve_agent_root(config: dict[str, Any]) -> Path:
    """自主 Agent 的数据目录：优先第一个含有经理季度产物的目录。"""
    for root in _portfolio_roots(config):
        if root.exists() and any(path.is_dir() for path in root.glob("*/*")):
            return root
    return _portfolio_roots(config)[0]


def _run_agent_interactive(config: dict[str, Any]) -> None:
    from .agent import run_agent
    from .llm_agent import llm_available

    if not llm_available():
        print("未配置 DeepSeek Key，无法运行自主 Agent。")
        return
    question = input("你的问题：").strip()
    if not question:
        return
    result = run_agent(
        question,
        portfolio_root=_resolve_agent_root(config),
        roster_path=Path(config["roster"]),
    )
    if not result["used_llm"]:
        print("未配置 DeepSeek Key。")
        return
    print("\n=== 自主 Agent 回答 ===")
    print(result["answer"])
    print("\n工具调用：")
    for step in result["steps"]:
        print(f"  - {step['tool']}({json.dumps(step['args'], ensure_ascii=False)}) {'ok' if step['ok'] else 'FAILED'}")


def _print_doctor(result: dict[str, Any]) -> None:
    print(f"环境结论：{result['status']}")
    for row in result["checks"]:
        print(f"[{row['status']}] {row['name']}：{row['evidence']}")
    print(result["note"])


def _open_results(config: dict[str, Any]) -> None:
    root = Path(config["report_root"])
    root.mkdir(parents=True, exist_ok=True)
    print(f"Excel/PDF结果目录：{root}")
    if platform.system() == "Darwin":
        subprocess.run(["open", str(root)], check=False)


def _prompt_report_date(latest: dt.date) -> str:
    value = input(f"报告期（默认 {latest.isoformat()}，直接回车使用默认值）：").strip()
    report_date = dt.date.fromisoformat(value) if value else latest
    if (report_date.month, report_date.day) not in {(3, 31), (6, 30), (9, 30), (12, 31)}:
        raise ValueError("报告期必须是自然季度末：03-31、06-30、09-30或12-31")
    return report_date.isoformat()


def _prompt_brief_output() -> str | None:
    print("\n请选择输出内容：")
    print("1. Excel持仓简报（股票名称、申万一级行业）")
    print("2. PDF分析报告（含持仓比例、行业分布、季度新增与退出）")
    print("3. Excel + PDF（推荐）")
    print("0. 返回")
    choices = {"1": "excel", "2": "pdf", "3": "both"}
    raw = input("请选择：").strip()
    if raw == "0":
        return None
    if raw not in choices:
        raise ValueError("输出内容选项无效")
    return choices[raw]


def _prompt_manager_scope(config: dict[str, Any]) -> tuple[list[str], list[str]] | None:
    entries = read_manager_roster(Path(config["roster"]))
    companies = sorted({row.company for row in entries})
    print("\n请选择基金公司：")
    for index, company in enumerate(companies, start=1):
        count = sum(row.company == company for row in entries)
        print(f"{index}. {company}（{count}人）")
    print("0. 返回")
    raw = input("请选择：").strip()
    if raw == "0":
        return None
    if not raw.isdigit() or not 1 <= int(raw) <= len(companies):
        raise ValueError("基金公司选项无效")
    company = companies[int(raw) - 1]
    managers = [row.manager for row in entries if row.company == company]
    print(f"\n请选择 {company} 的基金经理（建议先运行1位）：")
    for index, manager in enumerate(managers, start=1):
        print(f"{index}. {manager}")
    print(f"{len(managers) + 1}. 运行该公司全部 {len(managers)} 位经理")
    print("0. 返回")
    raw = input("请选择：").strip()
    if raw == "0":
        return None
    if not raw.isdigit() or not 1 <= int(raw) <= len(managers) + 1:
        raise ValueError("基金经理选项无效")
    if int(raw) == len(managers) + 1:
        return [company], []
    return [], [managers[int(raw) - 1]]


def _interactive(config: dict[str, Any], paths: MacAgentPaths) -> int:
    latest = latest_closed_quarter(beijing_today())
    while True:
        print("\n基金持仓 Agent（Mac CLI）")
        print(f"最近结束季度：{quarter_label(latest)} / {latest.isoformat()}")
        print("1. 生成最近三季度持仓报告（可选Excel或分析PDF，推荐）")
        print("2. 生成单季度完整分析")
        print("3. 运行全部25位基金经理（单季度）")
        print("4. 查看运行状态（含大模型状态解读）")
        print("5. 打开Excel/PDF结果目录")
        print("6. 环境诊断")
        print("7. 自然语言问答（基于已验证季度数据）")
        print("8. 自主 Agent（多步工具编排）")
        print("0. 退出")
        choice = input("请选择：").strip()
        if choice == "1":
            scope = _prompt_manager_scope(config)
            if scope is None:
                continue
            companies, managers = scope
            end_report_date = _prompt_report_date(latest)
            output_format = _prompt_brief_output()
            if output_format is None:
                continue
            code = run_three_quarter_brief(
                config,
                paths,
                end_report_date=end_report_date,
                companies=companies,
                managers=managers,
                refresh=False,
                output_format=output_format,
            )
            print(f"任务结束，退出码：{code}")
            if code == 0:
                _open_results(config)
                for name in _scope_manager_names(config, companies, managers)[:3]:
                    _llm_interpret_quarter(config, name, end_report_date)
        elif choice == "2":
            scope = _prompt_manager_scope(config)
            if scope is None:
                continue
            companies, managers = scope
            report_date = _prompt_report_date(latest)
            code = run_portfolio(config, paths, report_date=report_date, companies=companies, managers=managers, retry_errors=True, refresh=False, data_only=False)
            print(f"任务结束，退出码：{code}")
            if list_results(config):
                _open_results(config)
            _llm_interpret_status(config)
        elif choice == "3":
            confirmation = input("这会依次运行25位经理，可能耗时较长。输入 RUN 确认：").strip()
            if confirmation == "RUN":
                code = run_portfolio(config, paths, report_date=latest.isoformat(), companies=None, managers=None, retry_errors=True, refresh=False, data_only=False)
                print(f"任务结束，退出码：{code}")
                if list_results(config):
                    _open_results(config)
                _llm_interpret_status(config)
            else:
                print("已取消。")
        elif choice == "4":
            rows = list_manager_runs(config)
            if rows:
                for row in rows[:25]:
                    stage = f" / 阶段：{row['stage']}" if row["stage"] else ""
                    print(f"{row['manager']} / {row['report_date']} / {row['status']}{stage}")
            else:
                print("暂无运行记录")
            _llm_interpret_status(config)
        elif choice == "5":
            _open_results(config)
        elif choice == "6":
            _print_doctor(doctor(config))
        elif choice == "7":
            manager = _prompt_manager_name(config)
            if manager is None:
                continue
            report_date = _prompt_report_date(latest)
            _llm_interpret_quarter(config, manager, report_date)
            print("\n可继续追问（基于同一季度数据），输入 0 结束。")
            while True:
                question = input("你的问题：").strip()
                if question in {"0", "退出", "结束"}:
                    break
                if not question:
                    continue
                _llm_interpret_quarter(config, manager, report_date, question=question)
        elif choice == "8":
            _run_agent_interactive(config)
        elif choice == "0":
            return 0
        else:
            print("无效选项，请重新输入。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fund-agent", description="基金持仓 Agent 的 Mac 开发者命令行入口")
    subparsers = parser.add_subparsers(dest="command")
    init_parser = subparsers.add_parser("init", help="初始化Mac用户目录和配置")
    init_parser.add_argument("--project-root", type=Path)
    doctor_parser = subparsers.add_parser("doctor", help="检查当前Mac运行环境")
    doctor_parser.add_argument("--check-network", action="store_true")
    run_parser = subparsers.add_parser("run", help="运行基金持仓任务")
    run_parser.add_argument("--report-date")
    run_parser.add_argument("--company", action="append", default=[])
    run_parser.add_argument("--manager", action="append", default=[])
    run_parser.add_argument("--retry-errors", action="store_true")
    run_parser.add_argument("--refresh", action="store_true")
    run_parser.add_argument("--data-only", action="store_true", help="只生成JSON和历史库，不生成Excel")
    brief_parser = subparsers.add_parser("brief", help="生成最近三个季度前十大A股持仓简报")
    brief_parser.add_argument("--end-report-date")
    brief_parser.add_argument("--company", action="append", default=[])
    brief_parser.add_argument("--manager", action="append", default=[])
    brief_parser.add_argument("--refresh", action="store_true", help="补跑缺失季度时忽略网页缓存")
    brief_parser.add_argument(
        "--output-format",
        choices=("excel", "pdf", "both"),
        default="both",
        help="输出Excel简报、PDF分析报告或两者（默认both）",
    )
    retry_parser = subparsers.add_parser("retry", help="重试首个失败或带错误阶段")
    retry_parser.add_argument("--report-date")
    retry_parser.add_argument("--company", action="append", default=[])
    retry_parser.add_argument("--manager", action="append", default=[])
    subparsers.add_parser("status", help="查看季度任务状态")
    subparsers.add_parser("results", help="列出正式Excel和PDF")
    subparsers.add_parser("open-results", help="在Finder打开正式结果目录")
    args = parser.parse_args(argv)
    paths = default_paths()

    try:
        if args.command == "init":
            root = (args.project_root or discover_project_root()).resolve()
            config = initialize(root, paths)
            print(f"初始化完成：{paths.config_path}")
            print(f"正式报告目录：{config['report_root']}")
            return 0
        config = load_config(paths)
        if args.command == "doctor":
            result = doctor(config, check_network=args.check_network)
            _print_doctor(result)
            return 3 if result["status"] == "BLOCKED" else 0
        if args.command in {"run", "retry"}:
            return run_portfolio(
                config,
                paths,
                report_date=args.report_date,
                companies=args.company,
                managers=args.manager,
                retry_errors=args.command == "retry" or args.retry_errors,
                refresh=getattr(args, "refresh", False),
                data_only=getattr(args, "data_only", False),
            )
        if args.command == "brief":
            return run_three_quarter_brief(
                config,
                paths,
                end_report_date=args.end_report_date,
                companies=args.company,
                managers=args.manager,
                refresh=args.refresh,
                output_format=args.output_format,
            )
        if args.command == "status":
            rows = list_status(config)
            print(json.dumps(rows, ensure_ascii=False, indent=2) if rows else "暂无运行记录")
            return 0
        if args.command == "results":
            results = list_results(config)
            print("\n".join(str(path) for path in results) if results else "暂无Excel/PDF结果")
            return 0
        if args.command == "open-results":
            if platform.system() != "Darwin":
                raise RuntimeError("open-results 仅支持 macOS")
            Path(config["report_root"]).mkdir(parents=True, exist_ok=True)
            return subprocess.run(["open", str(config["report_root"])]).returncode
        return _interactive(config, paths)
    except KeyboardInterrupt:
        print("\n任务已由用户停止。")
        return 130
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
