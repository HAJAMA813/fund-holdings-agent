from __future__ import annotations

import re
from collections import defaultdict

from .io import clean_text
from .models import FetchResult


SHARE_SUFFIX = re.compile(r"(?:\(LOF\))?(?:A/B|A|B|C|D|E|H|I|Y|Z)(?:类)?(?:人民币|美元|港币)?$", re.I)


def base_name(name: str) -> str:
    text = clean_text(name).replace("（LOF）", "(LOF)")
    text = SHARE_SUFFIX.sub("", text)
    return re.sub(r"(?:人民币|美元|港币)$", "", text)


def share_priority(name: str, code: str) -> tuple[int, str]:
    text = clean_text(name)
    if re.search(r"(?:A/B|A)(?:类)?(?:人民币|美元|港币)?$", text, re.I):
        return 0, code
    if not re.search(r"(?:B|C|D|E|H|I|Y|Z)(?:类)?(?:人民币|美元|港币)?$", text, re.I):
        return 1, code
    if re.search(r"C(?:类)?(?:人民币|美元|港币)?$", text, re.I):
        return 3, code
    return 2, code


def mark_duplicate_shares(results: list[FetchResult]) -> dict[str, str]:
    groups: dict[tuple[str, tuple[str, ...]], list[FetchResult]] = defaultdict(list)
    for result in results:
        if result.holdings:
            signature = tuple(row.stock_code for row in sorted(result.holdings, key=lambda x: x.rank))
            groups[(base_name(result.fund.fund_name), signature)].append(result)
    representative_by_code: dict[str, str] = {}
    duplicate_no = 0
    for members in groups.values():
        if len(members) == 1:
            representative_by_code[members[0].fund.fund_code] = members[0].fund.fund_code
            continue
        duplicate_no += 1
        group_id = f"DUP{duplicate_no:03d}"
        representative = min(members, key=lambda item: share_priority(item.fund.fund_name, item.fund.fund_code))
        for member in members:
            representative_by_code[member.fund.fund_code] = representative.fund.fund_code
            for holding in member.holdings:
                holding.duplicate_group = group_id
                holding.representative = "是" if member is representative else "否"
    return representative_by_code

