from __future__ import annotations

import argparse
import json
from pathlib import Path

from .llm_agent import answer_question
from .quarterly_cli import beijing_now, latest_closed_quarter


def main() -> None:
    parser = argparse.ArgumentParser(description="基于已验证季度产物的自然语言问答（只读，可选调用 DeepSeek）")
    parser.add_argument("--manager", required=True, help="基金经理姓名")
    parser.add_argument("--report-date", help="报告期（YYYY-MM-DD）；默认按北京时间选择最近结束季度")
    parser.add_argument("--question", default="请概括该经理本季度的持仓、行业暴露、研究资源需求和异常。")
    parser.add_argument("--portfolio-root", type=Path, default=Path("outputs/quarterly/portfolio"))
    parser.add_argument("--roster", type=Path, default=Path("data/managers_portfolio.csv"))
    parser.add_argument("--model", help="DeepSeek 模型名；默认取环境变量 DEEPSEEK_MODEL 或 deepseek-chat")
    parser.add_argument("--base-url", help="DeepSeek API 基础地址；默认 https://api.deepseek.com")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--output-json", type=Path, help="可选：把问答结果与来源写入该 JSON 文件")
    args = parser.parse_args()

    report_date = args.report_date or latest_closed_quarter(beijing_now().date()).isoformat()
    result = answer_question(
        manager=args.manager,
        report_date=report_date,
        question=args.question,
        portfolio_root=args.portfolio_root,
        roster_path=args.roster,
        base_url=args.base_url,
        model=args.model,
        timeout=args.timeout,
    )

    print(result["answer"])
    print("\n---")
    print(f"模式：{result['mode']}（deepseek_used={result['deepseek_used']}）")
    print(f"来源文件：{len(result['sources'])} 个，全部为已校验季度产物")

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入：{args.output_json}")


if __name__ == "__main__":
    main()
