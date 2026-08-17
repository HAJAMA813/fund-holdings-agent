from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Fund:
    manager: str
    fund_code: str
    fund_name: str
    fund_type: str = ""
    inception_date: str = ""
    input_row: int = 0
    selected: bool = True
    selection_reason: str = "纳入"
    verified_manager: str = ""
    manager_status: str = "待核实"
    manager_source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Holding:
    fund_code: str
    fund_name: str
    manager: str
    report_date: str
    rank: int
    stock_code: str
    stock_name: str
    shares_10k: float | None
    market_value_10k: float | None
    nav_ratio: float | None
    market: str
    source_url: str
    duplicate_group: str = ""
    representative: str = "是"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Issue:
    severity: str
    category: str
    fund_code: str
    fund_name: str
    manager: str
    report_date: str
    message: str
    source_url: str = ""
    action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FetchResult:
    fund: Fund
    holdings: list[Holding] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    status: str = "待处理"

