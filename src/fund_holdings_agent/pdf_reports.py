from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


NAVY = colors.HexColor("#17365D")
BLUE = colors.HexColor("#4F81BD")
TEXT = colors.HexColor("#24364B")
MUTED = colors.HexColor("#60758A")
GRID = colors.HexColor("#CFD9E3")
PALE = colors.HexColor("#EAF2F8")
Q_COLORS = [colors.HexColor("#FCE4D6"), colors.HexColor("#D9EAF7"), colors.HexColor("#E2F0D9")]
PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
FONT = "FundAgentChinese"
FONT_CANDIDATES = (
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path.home() / "Library" / "Fonts" / "Arial Unicode.ttf",
)


def _register_fonts() -> None:
    if FONT not in pdfmetrics.getRegisteredFontNames():
        font_path = find_pdf_font()
        if font_path is None:
            raise FileNotFoundError("未找到可嵌入的 macOS 中文字体 Arial Unicode.ttf")
        pdfmetrics.registerFont(TTFont(FONT, str(font_path)))


def find_pdf_font() -> Path | None:
    return next((path for path in FONT_CANDIDATES if path.exists()), None)


def _styles() -> dict[str, ParagraphStyle]:
    _register_fonts()
    base = getSampleStyleSheet()
    return {
        "cover": ParagraphStyle(
            "cover",
            parent=base["Title"],
            fontName=FONT,
            fontSize=25,
            leading=34,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=6 * mm,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=14,
            leading=21,
            textColor=BLUE,
            spaceAfter=5 * mm,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName=FONT,
            fontSize=18,
            leading=24,
            textColor=NAVY,
            spaceAfter=4 * mm,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName=FONT,
            fontSize=12,
            leading=17,
            textColor=NAVY,
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9,
            leading=14,
            textColor=TEXT,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=7.5,
            leading=10,
            textColor=TEXT,
        ),
        "tiny": ParagraphStyle(
            "tiny",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=6.5,
            leading=8,
            textColor=TEXT,
        ),
        "center": ParagraphStyle(
            "center",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8,
            leading=10,
            textColor=TEXT,
            alignment=TA_CENTER,
        ),
        "note": ParagraphStyle(
            "note",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8,
            leading=12,
            textColor=MUTED,
            backColor=colors.HexColor("#F3F6F9"),
            borderPadding=7,
        ),
    }


def _p(value: Any, style: ParagraphStyle) -> Paragraph:
    text = str(value if value not in (None, "") else "-")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(text, style)


def _pct(value: Any) -> str:
    try:
        return f"{float(value or 0) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def _amount(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    return f"{number:,.0f}" if number else "-"


def _table(
    rows: list[list[Any]],
    widths: list[float],
    *,
    header_background: colors.Color = NAVY,
    font_size: float = 8,
    row_backgrounds: Iterable[colors.Color] | None = None,
) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), header_background),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("LEADING", (0, 0), (-1, -1), font_size + 2),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for index, background in enumerate(row_backgrounds or [], start=1):
        commands.append(("BACKGROUND", (0, index), (-1, index), background))
    table.setStyle(TableStyle(commands))
    return table


def _kpi_cards(cards: list[tuple[str, str]], style: ParagraphStyle) -> Table:
    cells = []
    for label, value in cards:
        cells.append([_p(value, ParagraphStyle("kpi", parent=style, fontSize=16, leading=19, textColor=NAVY, alignment=TA_CENTER)), _p(label, ParagraphStyle("kpilabel", parent=style, fontSize=8, leading=10, textColor=MUTED, alignment=TA_CENTER))])
    table = Table([cells], colWidths=[(PAGE_WIDTH - 34 * mm) / len(cells)] * len(cells))
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F6F9")),
        ("BOX", (0, 0), (-1, -1), 0.6, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def _bar_chart(rows: list[dict[str, Any]], *, width: float = 245 * mm, height: float = 45 * mm) -> Drawing:
    drawing = Drawing(width, height)
    values = [float(row.get("nav_ratio_sum") or 0) for row in rows[:8]]
    maximum = max(values, default=1) or 1
    left = 33 * mm
    usable = width - left - 22 * mm
    row_height = height / max(len(values), 1)
    for index, (row, value) in enumerate(zip(rows[:8], values)):
        y = height - (index + 1) * row_height + 2
        bar_width = usable * value / maximum
        drawing.add(String(0, y + 2, str(row.get("sw_level1") or "待核查")[:10], fontName=FONT, fontSize=7, fillColor=TEXT))
        drawing.add(Rect(left, y, max(bar_width, 1), row_height - 5, fillColor=BLUE, strokeColor=None))
        drawing.add(String(left + bar_width + 4, y + 2, _pct(value), fontName=FONT, fontSize=7, fillColor=TEXT))
    return drawing


def _header_footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setStrokeColor(GRID)
    canvas.line(14 * mm, 11 * mm, PAGE_WIDTH - 14 * mm, 11 * mm)
    canvas.setFont(FONT, 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(14 * mm, 7 * mm, "公开披露信息整理 | 不构成投资建议")
    canvas.drawRightString(PAGE_WIDTH - 14 * mm, 7 * mm, f"第 {document.page} 页")
    canvas.restoreState()


def build_three_quarter_pdf_report(input_path: Path, output_path: Path) -> Path:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    summary = data["summary"]
    quarters = summary["quarters"]
    analytics = data.get("analytics", {})
    stock_summary = analytics.get("stock_summary_by_quarter", {})
    industry_summary = analytics.get("industry_summary_by_quarter", {})
    changes = analytics.get("stock_changes", {})
    styles = _styles()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    doc = SimpleDocTemplate(
        str(temporary),
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=13 * mm,
        bottomMargin=16 * mm,
        title=f"{summary.get('company', '')}{summary.get('manager', '')}三季度持仓分析报告",
        author="基金持仓 Agent",
    )
    story: list[Any] = []

    company = str(summary.get("company") or "基金公司").replace("管理有限公司", "")
    manager = str(summary.get("manager") or "基金经理")
    span = f"{quarters[0]}至{quarters[-1]}"
    latest_stocks = stock_summary.get(quarters[-1], [])
    story.extend([
        Spacer(1, 16 * mm),
        _p(f"{company}经理 {manager}", styles["cover"]),
        _p(f"{span} 三季度前十大持仓分析报告", styles["subtitle"]),
        _kpi_cards(
            [
                ("基础产品", str(summary.get("product_count", 0))),
                ("披露季度", str(len(quarters))),
                ("A股持仓记录", str(summary.get("a_share_holding_rows", 0))),
                ("最新季度股票", str(len(latest_stocks))),
                ("异常事项", str(summary.get("issue_count", 0))),
            ],
            styles["body"],
        ),
        Spacer(1, 8 * mm),
        _p("报告范围与方法", styles["h2"]),
        _table(
            [
                ["项目", "正式口径"],
                ["基金范围", "报告期内由指定基金经理管理、通过筛选的公募基金基础产品"],
                ["份额处理", "同一基础产品的A/C/E等份额去重，仅保留正式代表份额"],
                ["持仓范围", "每只基础产品公开披露的季度前十大持仓，仅展示A股，港股及其他市场不递补"],
                ["行业分类", "申万一级行业，沿用各单季度行业快照"],
                ["分析方式", "确定性规则计算，未调用DeepSeek或其他大模型"],
            ],
            [42 * mm, 205 * mm],
            font_size=8.5,
            row_backgrounds=[colors.white, PALE, colors.white, PALE, colors.white],
        ),
        Spacer(1, 6 * mm),
        _p(
            "重要说明：本报告中的跨产品持仓市值和占净值比例均为各基础产品披露值的算术汇总，适合观察共同持仓和变化方向，不代表基金经理统一组合的真实加权仓位。",
            styles["note"],
        ),
        Spacer(1, 10 * mm),
        _p(f"生成日期：{dt.date.today().isoformat()}", styles["small"]),
        PageBreak(),
    ])

    story.extend([_p(f"{manager} | 三季度核心持仓", styles["h1"])])
    story.append(
        _kpi_cards(
            [
                ("最新季度股票", str(len(latest_stocks))),
                ("新增股票", str(changes.get("new_count", 0))),
                ("退出股票", str(changes.get("exited_count", 0))),
                ("连续出现", str(changes.get("continuing_count", 0))),
            ],
            styles["body"],
        )
    )
    story.append(Spacer(1, 5 * mm))
    top_rows: list[list[Any]] = [["排名"]]
    for label in quarters:
        top_rows[0].extend([f"{label} 股票", "申万一级", "披露市值合计(万元)", "净值比例合计"])
    maximum_rows = min(10, max((len(stock_summary.get(label, [])) for label in quarters), default=0))
    for index in range(maximum_rows):
        row: list[Any] = [str(index + 1)]
        for label in quarters:
            values = stock_summary.get(label, [])
            item = values[index] if index < len(values) else {}
            row.extend([
                item.get("stock_name", "-"),
                item.get("sw_level1", "-"),
                _amount(item.get("market_value_10k_sum")),
                _pct(item.get("nav_ratio_sum")),
            ])
        top_rows.append(row)
    story.append(
        _table(
            top_rows,
            [9 * mm] + [20 * mm, 18 * mm, 22 * mm, 20 * mm] * 3,
            font_size=6.4,
            row_backgrounds=[colors.white if i % 2 else PALE for i in range(maximum_rows)],
        )
    )
    story.extend([
        Spacer(1, 4 * mm),
        _p("排序优先使用各产品披露持仓市值之和；缺少市值时依次使用净值比例合计、覆盖产品数和最佳名次。", styles["small"]),
        PageBreak(),
    ])

    latest_industries = industry_summary.get(quarters[-1], [])
    story.extend([
        _p(f"{manager} | 行业结构与季度变化", styles["h1"]),
        _p(f"{quarters[-1]} 申万一级行业分布（按各产品披露净值比例算术合计）", styles["h2"]),
        _bar_chart(latest_industries),
        Spacer(1, 2 * mm),
    ])
    industry_names: list[str] = []
    for label in quarters:
        for item in industry_summary.get(label, []):
            name = str(item.get("sw_level1") or "待核查")
            if name not in industry_names:
                industry_names.append(name)
    industry_names.sort(
        key=lambda name: -next((float(item.get("nav_ratio_sum") or 0) for item in latest_industries if item.get("sw_level1") == name), 0)
    )
    industry_rows: list[list[Any]] = [["申万一级行业"] + [f"{label} 比例合计" for label in quarters] + ["最新覆盖产品"]]
    for name in industry_names[:12]:
        values = []
        latest_product_count = 0
        for label in quarters:
            item = next((row for row in industry_summary.get(label, []) if row.get("sw_level1") == name), {})
            values.append(_pct(item.get("nav_ratio_sum")))
            if label == quarters[-1]:
                latest_product_count = int(item.get("product_count") or 0)
        industry_rows.append([name, *values, str(latest_product_count)])
    story.append(_table(industry_rows, [45 * mm, 40 * mm, 40 * mm, 40 * mm, 40 * mm], font_size=7.5, row_backgrounds=[PALE if i % 2 else colors.white for i in range(len(industry_rows) - 1)]))
    new_names = "、".join(item["stock_name"] for item in changes.get("new", [])[:8]) or "无"
    exited_names = "、".join(item["stock_name"] for item in changes.get("exited", [])[:8]) or "无"
    top_industries = "、".join(item["sw_level1"] for item in latest_industries[:3]) or "暂无"
    story.extend([
        Spacer(1, 4 * mm),
        _p(
            f"规则化观察：最新季度披露比例合计居前的行业为{top_industries}。与{quarters[0]}相比，新增股票{changes.get('new_count', 0)}只（{new_names}），退出股票{changes.get('exited_count', 0)}只（{exited_names}）。该结论仅描述公开前十大持仓集合变化。",
            styles["note"],
        ),
        PageBreak(),
    ])

    for product in _product_names(data.get("rows", [])):
        product_rows = [row for row in data.get("rows", []) if row.get("product_name") == product]
        codes = sorted({code for row in product_rows for code in row.get("product_fund_codes", [])})
        story.extend([
            _p(f"{manager} | {product}", styles["h1"]),
            _p(f"基础产品份额代码：{'、'.join(codes) or '-'}", styles["small"]),
            Spacer(1, 3 * mm),
        ])
        table_rows: list[list[Any]] = [["排名"]]
        for label in quarters:
            table_rows[0].extend([f"{label} 持仓", "申万一级", "占基金净值"])
        for row in product_rows:
            values: list[Any] = [str(row.get("rank", ""))]
            for label in quarters:
                holding = row.get("quarters", {}).get(label) or {}
                values.extend([
                    holding.get("stock_name", "-"),
                    holding.get("sw_level1", "-"),
                    _pct(holding.get("nav_ratio")),
                ])
            table_rows.append(values)
        story.append(
            _table(
                table_rows,
                [11 * mm] + [35 * mm, 27 * mm, 23 * mm] * 3,
                font_size=7.5,
                row_backgrounds=[colors.white if i % 2 else PALE for i in range(len(table_rows) - 1)],
            )
        )
        story.extend([
            Spacer(1, 4 * mm),
            _p("空白表示该季度该排名没有满足正式口径的A股记录；港股及其他市场不会用第11名以后持仓递补。", styles["note"]),
            PageBreak(),
        ])

    issues = data.get("issues", [])
    story.extend([
        _p("附录 | 数据质量与审计说明", styles["h1"]),
        _kpi_cards(
            [
                ("A股记录", str(summary.get("a_share_holding_rows", 0))),
                ("排除非A股", str(summary.get("non_a_holding_rows_excluded", 0))),
                ("空白排名单元", str(summary.get("empty_quarter_rank_cells", 0))),
                ("异常事项", str(len(issues))),
            ],
            styles["body"],
        ),
        Spacer(1, 5 * mm),
        _p(f"异常与待核查事项（展示前{min(len(issues), 12)}项，共{len(issues)}项）", styles["h2"]),
    ])
    issue_rows = [["季度", "级别", "分类", "对象", "说明", "处理建议"]]
    for item in issues[:12]:
        issue_rows.append([
            item.get("quarter", ""),
            item.get("severity", ""),
            _p(item.get("category", ""), styles["tiny"]),
            _p(item.get("name") or item.get("code") or "-", styles["tiny"]),
            _p(item.get("message", ""), styles["tiny"]),
            _p(item.get("action", ""), styles["tiny"]),
        ])
    if len(issue_rows) == 1:
        issue_rows.append(["-", "-", "无", "-", "本次运行未记录异常", "无需处理"])
    story.append(_table(issue_rows, [20 * mm, 15 * mm, 35 * mm, 28 * mm, 82 * mm, 67 * mm], font_size=6.7, row_backgrounds=[PALE if i % 2 else colors.white for i in range(len(issue_rows) - 1)]))
    story.extend([
        Spacer(1, 5 * mm),
        _p("可审计性", styles["h2"]),
        _p("PDF、Excel与三季度JSON均由同一份标准数据生成。源数据目录、报告期、抓取来源、行业快照和异常记录均保留在JSON及Excel说明页中，便于复核与重新运行。", styles["body"]),
        Spacer(1, 3 * mm),
        _p("本报告不构成投资建议。基金历史持仓不代表当前持仓，公开季度数据存在披露时滞。", styles["note"]),
    ])

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    temporary.replace(output_path)
    return output_path


def _product_names(rows: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for row in rows:
        name = str(row.get("product_name") or "")
        if name and name not in result:
            result.append(name)
    return result
