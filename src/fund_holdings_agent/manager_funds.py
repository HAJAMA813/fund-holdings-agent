from __future__ import annotations

import datetime as dt
import calendar
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from lxml import html as lxml_html

from .cache_utils import atomic_write_cache, read_cache_text
from .dedup import base_name
from .eastmoney import fetch_url, parse_manager_at_date
from .io import clean_text


MANAGER_SUGGEST_URL = (
    "https://fund.eastmoney.com/Data/FundDataPortfolio_Interface.aspx"
    "?dt=15&input={manager}&count=20"
)
MANAGER_PROFILE_URL = "https://fund.eastmoney.com/manager/{manager_id}.html"
FUND_INFO_URL = "https://fundf10.eastmoney.com/jbgk_{code}.html"
FUND_MANAGER_URL = "https://fundf10.eastmoney.com/jjjl_{code}.html"


@dataclass
class ManagerCandidate:
    name: str
    pinyin: str
    manager_id: str


@dataclass
class FundTenure:
    manager: str
    manager_id: str
    company: str
    fund_code: str
    fund_name: str
    fund_type: str
    tenure_start: str
    tenure_end: str
    active_on_report_date: bool = False
    inception_date: str = ""
    product_base_name: str = ""
    product_group: str = ""
    verified_manager: str = ""
    manager_verification: str = "未核验"
    selected: bool = False
    selection_reason: str = ""
    manager_profile_url: str = ""
    fund_info_url: str = ""
    manager_history_url: str = ""


def parse_manager_suggestions(text: str) -> list[ManagerCandidate]:
    match = re.search(r"\(\s*(\[.*\])\s*\)\s*;?", text, flags=re.S)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    result: list[ManagerCandidate] = []
    for item in payload:
        parts = [clean_text(part) for part in str(item).split(",")]
        if len(parts) >= 3 and parts[0] and parts[2].isdigit():
            result.append(ManagerCandidate(parts[0], parts[1], parts[2]))
    return result


def _date(value: str) -> dt.date | None:
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", clean_text(value))
    return dt.date(*map(int, match.groups())) if match else None


def _add_months(value: dt.date, months: int) -> dt.date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def disclosure_exemption_reason(inception_date: str, report_date: str) -> str:
    """Return the deterministic period exemption used by the quarterly gate."""
    inception = _date(inception_date)
    target = _date(report_date)
    if inception and target and inception <= target < _add_months(inception, 2):
        return "基金合同生效不足两个月，当期定期报告可不编制"
    return ""


def product_exclusion_reason(fund_type: str) -> str:
    """Classify types that do not belong in a direct-stock holdings report."""
    normalized = clean_text(fund_type).upper()
    if "FOF" in normalized:
        return "FOF 不纳入直接股票持仓口径"
    if "货币" in normalized:
        return "货币基金不纳入股票持仓口径"
    if "指数型-固收" in normalized or "固收指数" in normalized:
        return "固收指数基金不纳入股票持仓口径"
    if normalized.startswith("债券型") and "混合二级" not in normalized and "可转债" not in normalized:
        return "非二级债基不纳入直接股票持仓口径"
    if any(label in normalized for label in ("商品", "期货")):
        return "商品或期货基金不纳入普通股票持仓口径"
    return ""


def _split_tenure(value: str) -> tuple[str, str]:
    dates = re.findall(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", value)
    start = _date(dates[0]).isoformat() if dates else ""
    end = _date(dates[1]).isoformat() if len(dates) > 1 else ""
    return start, end


def _header_index(headers: list[str], name: str) -> int | None:
    return next((i for i, header in enumerate(headers) if name in header), None)


def parse_manager_profile(page_html: str, manager_id: str) -> tuple[str, str, list[FundTenure]]:
    doc = lxml_html.fromstring(page_html)
    name_nodes = doc.xpath("//h3[@id='name_1']//text() | //div[contains(@class,'fundManger')]//h3//text()")
    manager_name = clean_text(" ".join(name_nodes))
    if manager_name:
        manager_name = re.sub(r"基金经理.*$", "", manager_name).strip()

    company = ""
    preferred = doc.xpath("//span[contains(normalize-space(.),'现任基金公司')]/following-sibling::a[1]")
    company_anchors = preferred or doc.xpath(
        "//a[re:test(@href, '/company/[0-9]+\\.html', 'i')]",
        namespaces={"re": "http://exslt.org/regular-expressions"},
    )
    for anchor in company_anchors:
        text = clean_text(anchor.text_content())
        if text and text != "基金公司" and ("基金" in text or "资产" in text):
            company = text
            break

    tenures: list[FundTenure] = []
    for table in doc.xpath("//table"):
        rows = table.xpath(".//tr")
        if not rows:
            continue
        headers = [clean_text(cell.text_content()) for cell in rows[0].xpath("./th|./td")]
        code_i = _header_index(headers, "基金代码")
        name_i = _header_index(headers, "基金名称")
        type_i = _header_index(headers, "基金类型")
        tenure_i = _header_index(headers, "任职时间")
        if None in {code_i, name_i, tenure_i}:
            continue
        for tr in rows[1:]:
            cells = [clean_text(cell.text_content()) for cell in tr.xpath("./th|./td")]
            if len(cells) <= max(code_i, name_i, tenure_i):
                continue
            code_match = re.search(r"\b\d{6}\b", cells[code_i])
            if not code_match:
                continue
            start, end = _split_tenure(cells[tenure_i])
            tenures.append(
                FundTenure(
                    manager=manager_name,
                    manager_id=manager_id,
                    company=company,
                    fund_code=code_match.group(),
                    fund_name=cells[name_i],
                    fund_type=cells[type_i] if type_i is not None and type_i < len(cells) else "",
                    tenure_start=start,
                    tenure_end=end,
                    manager_profile_url=MANAGER_PROFILE_URL.format(manager_id=manager_id),
                )
            )
        if tenures:
            break
    return manager_name, company, tenures


def parse_fund_info(page_html: str) -> dict[str, str]:
    doc = lxml_html.fromstring(page_html)
    text = clean_text(doc.text_content())
    result = {"fund_name": "", "fund_type": "", "inception_date": "", "company": ""}
    title_nodes = doc.xpath("//h4[contains(@class,'title')]//text() | //div[contains(@class,'fundDetail-tit')]//text()")
    title = clean_text(" ".join(title_nodes))
    if title:
        result["fund_name"] = re.sub(r"\(\d{6}\).*", "", title).strip()
    patterns = {
        "inception_date": r"成立日期[：:]?\s*(\d{4}-\d{2}-\d{2})",
        "fund_type": r"基金类型[：:]?\s*([^|\s]+(?:-?[^|\s]+)?)",
        "company": r"基金管理人[：:]?\s*([^|\s]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            result[key] = clean_text(match.group(1))
    if not result["inception_date"]:
        for tr in doc.xpath("//tr"):
            cells = [clean_text(cell.text_content()) for cell in tr.xpath("./th|./td")]
            for index, cell in enumerate(cells[:-1]):
                if "成立日期" in cell:
                    parsed = _date(cells[index + 1])
                    if parsed:
                        result["inception_date"] = parsed.isoformat()
    return result


class CachedFetcher:
    def __init__(self, cache_dir: Path, refresh: bool = False, **fetch_options: object):
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.fetch_options = fetch_options
        cache_dir.mkdir(parents=True, exist_ok=True)

    def __call__(self, url: str, referer: str = "") -> str:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cached = self.cache_dir / f"{key}.html"
        if cached.exists() and not self.refresh:
            value = read_cache_text(cached)
            if value is not None:
                return value
        value = fetch_url(url, referer=referer, **self.fetch_options)
        atomic_write_cache(cached, value)
        return value


def resolve_manager(
    manager: str,
    fetch: Callable[[str], str],
    manager_id: str = "",
) -> ManagerCandidate:
    if manager_id:
        return ManagerCandidate(clean_text(manager), "", manager_id)
    url = MANAGER_SUGGEST_URL.format(manager=quote(clean_text(manager)))
    exact = [candidate for candidate in parse_manager_suggestions(fetch(url)) if candidate.name == clean_text(manager)]
    if not exact:
        raise ValueError(f"未找到完全同名的基金经理：{manager}")
    if len(exact) > 1:
        ids = ", ".join(candidate.manager_id for candidate in exact)
        raise ValueError(f"存在多位同名基金经理，请指定 manager_id：{ids}")
    return exact[0]


def get_manager_funds(
    manager: str,
    report_date: str,
    fetch: Callable[[str], str],
    manager_id: str = "",
) -> dict[str, object]:
    target = dt.date.fromisoformat(report_date)
    candidate = resolve_manager(manager, fetch, manager_id)
    profile_url = MANAGER_PROFILE_URL.format(manager_id=candidate.manager_id)
    profile_name, company, rows = parse_manager_profile(fetch(profile_url), candidate.manager_id)
    if profile_name and profile_name != candidate.name:
        raise ValueError(f"经理ID与姓名不匹配：期望 {candidate.name}，页面为 {profile_name}")
    if not rows:
        raise ValueError(f"经理页面未解析到任职基金：{profile_url}")

    issues: list[dict[str, str]] = []
    for row in rows:
        start = _date(row.tenure_start)
        end = _date(row.tenure_end) or dt.date.max
        row.active_on_report_date = bool(start and start <= target <= end)
        row.product_base_name = base_name(row.fund_name)
        if not row.active_on_report_date:
            row.selection_reason = "报告期不在经理任职区间"
            continue

        row.fund_info_url = FUND_INFO_URL.format(code=row.fund_code)
        row.manager_history_url = FUND_MANAGER_URL.format(code=row.fund_code)
        try:
            info = parse_fund_info(fetch(row.fund_info_url))
            row.inception_date = info["inception_date"]
            row.fund_type = row.fund_type or info["fund_type"]
            inception = _date(row.inception_date)
            if inception and inception > target:
                row.selection_reason = "基金成立日晚于报告期"
                continue
        except Exception as exc:  # keep the historical manager page as the primary selection source
            issues.append(_issue("警告", "基金基本信息抓取失败", row, report_date, str(exc), row.fund_info_url))

        exemption_reason = disclosure_exemption_reason(row.inception_date, report_date)
        if exemption_reason:
            row.selection_reason = exemption_reason
            continue
        exclusion_reason = product_exclusion_reason(row.fund_type)
        if exclusion_reason:
            row.selection_reason = exclusion_reason
            continue

        try:
            verified, _ = parse_manager_at_date(fetch(row.manager_history_url), report_date)
            row.verified_manager = verified
            verified_names = {name for name in re.split(r"[,，、;；\s]+", verified) if name}
            if candidate.name in verified_names:
                row.manager_verification = "通过"
            else:
                row.manager_verification = "不一致"
                issues.append(
                    _issue(
                        "错误",
                        "报告期经理不一致",
                        row,
                        report_date,
                        f"经理档案显示当期在任，但基金经理历史页解析为：{verified or '空'}",
                        row.manager_history_url,
                    )
                )
        except Exception as exc:
            row.manager_verification = "核验失败"
            issues.append(_issue("警告", "经理历史核验失败", row, report_date, str(exc), row.manager_history_url))

        row.selected = True
        row.selection_reason = "报告期在任且成立日期有效"

    groups = {name: f"PRODUCT{index:03d}" for index, name in enumerate(sorted({r.product_base_name for r in rows if r.selected}), 1)}
    for row in rows:
        row.product_group = groups.get(row.product_base_name, "")

    selected = [row for row in rows if row.selected]
    summary = {
        "manager": candidate.name,
        "manager_id": candidate.manager_id,
        "company": company,
        "report_date": report_date,
        "historical_share_count": len(rows),
        "active_share_count": sum(row.active_on_report_date for row in rows),
        "selected_share_count": len(selected),
        "product_count": len(groups),
        "verified_count": sum(row.manager_verification == "通过" for row in selected),
        "error_count": sum(issue["severity"] == "错误" for issue in issues),
        "warning_count": sum(issue["severity"] == "警告" for issue in issues),
    }
    return {
        "summary": summary,
        "selected_funds": [asdict(row) for row in selected],
        "all_tenures": [asdict(row) for row in rows],
        "issues": issues,
        "sources": [
            {"source_id": "S01", "name": "天天基金基金经理档案", "url": profile_url, "purpose": "经理历史任职基金池"},
            {"source_id": "S02", "name": "天天基金基金基本概况", "url": "https://fundf10.eastmoney.com/jbgk_{基金代码}.html", "purpose": "成立日期交叉核验"},
            {"source_id": "S03", "name": "天天基金基金经理变动", "url": "https://fundf10.eastmoney.com/jjjl_{基金代码}.html", "purpose": "报告期基金经理交叉核验"},
        ],
    }


def _issue(severity: str, category: str, row: FundTenure, report_date: str, message: str, url: str) -> dict[str, str]:
    return {
        "severity": severity,
        "category": category,
        "fund_code": row.fund_code,
        "fund_name": row.fund_name,
        "manager": row.manager,
        "report_date": report_date,
        "message": message,
        "source_url": url,
        "action": "检查网页结构或人工复核",
    }
