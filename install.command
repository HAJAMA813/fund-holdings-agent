#!/bin/zsh
set -eu

SCRIPT_DIR=${0:A:h}
cd "$SCRIPT_DIR"

PYTHON_BIN=${FUND_AGENT_PYTHON:-}
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3.13 python3.12 python3.11 python3; do
    resolved=$(command -v "$candidate" 2>/dev/null) || continue
    # 逐个实际执行验证：跳过架构不匹配（如 Apple Silicon 上的 Intel 版 Anaconda）或版本过低的解释器
    if ! "$resolved" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      echo "跳过不可用的 Python：$resolved（CPU 架构不匹配或版本低于 3.11）"
      continue
    fi
    PYTHON_BIN=$resolved
    break
  done

  if [[ -z "$PYTHON_BIN" ]]; then
    echo "未找到可用的 Python 3.11 或更高版本，请先安装后重试。"
    echo "提示：Apple Silicon 需要 arm64 版解释器；Intel 版 Python（如部分 Anaconda 安装）缺少 Rosetta 时无法运行。"
    read -r "?按回车退出..."
    exit 2
  fi
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "指定的 Python 无法运行或版本低于 3.11：$PYTHON_BIN"
  echo "提示：Apple Silicon 需要 arm64 版解释器；可用 FUND_AGENT_PYTHON 指定其他解释器。"
  read -r "?按回车退出..."
  exit 2
fi

echo "正在创建独立 Python 环境..."
"$PYTHON_BIN" -m venv .venv
echo "正在安装基金持仓 Agent..."
.venv/bin/python -m pip install --upgrade .

if ! .venv/bin/python -c 'import fund_holdings_agent, lxml, openpyxl, reportlab'; then
  echo "安装校验失败：Python 无法加载基金持仓 Agent。"
  echo "请保留本窗口内容并联系维护人员。"
  read -r "?按回车退出..."
  exit 3
fi

.venv/bin/fund-agent init --project-root "$SCRIPT_DIR"

if ! .venv/bin/fund-agent doctor; then
  echo ""
  echo "基础安装已完成，但环境诊断存在阻断项。请按上方 FAIL 提示处理后重新运行 doctor。"
  read -r "?按回车结束..."
  exit 3
fi

echo ""
echo "安装完成。请双击‘基金持仓Agent.command’，或在本目录运行："
echo ".venv/bin/fund-agent doctor"
read -r "?按回车结束..."
