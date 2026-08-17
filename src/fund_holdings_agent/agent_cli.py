from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import run_agent
from .quarterly_cli import beijing_now, latest_closed_quarter


def main() -> None:
    parser = argparse.ArgumentParser(description="多步工具编排 Agent：模型自主调用确定性工具回答问题")
    parser.add_argument("--question", required=True, help="自然语言问题")
    parser.add_argument("--portfolio-root", type=Path, default=Path("outputs/quarterly/portfolio"))
    parser.add_argument("--roster", type=Path, default=Path("data/managers_portfolio.csv"))
    parser.add_argument("--model", help="DeepSeek 模型名；默认取环境变量 DEEPSEEK_MODEL 或 deepseek-chat")
    parser.add_argument("--base-url", help="DeepSeek API 基础地址；默认 https://api.deepseek.com")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--output-json", type=Path, help="可选：把完整过程写入该 JSON 文件")
    args = parser.parse_args()

    result = run_agent(
        args.question,
        portfolio_root=args.portfolio_root,
        roster_path=args.roster,
        base_url=args.base_url,
        model=args.model,
        timeout=args.timeout,
        max_steps=args.max_steps,
    )

    if not result["used_llm"]:
        print("未配置 DEEPSEEK_API_KEY，无法运行多步 Agent；请先在 .env 或环境变量中配置。")
        raise SystemExit(2)

    print(result["answer"])
    print("\n---")
    print(f"工具调用 {result['tool_calls']} 次：")
    for step in result["steps"]:
        print(f"  - {step['tool']}({json.dumps(step['args'], ensure_ascii=False)}) {'ok' if step['ok'] else 'FAILED'}")
    print(f"生成时间（北京时间）：{beijing_now().isoformat(timespec='seconds')}")

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"结果已写入：{args.output_json}")


if __name__ == "__main__":
    main()
