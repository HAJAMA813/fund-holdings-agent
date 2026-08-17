#!/bin/zsh
set -u

SCRIPT_DIR=${0:A:h}
cd "$SCRIPT_DIR"

if [[ ! -x .venv/bin/fund-agent ]]; then
  echo "尚未安装。请先双击 install.command。"
  read -r "?按回车退出..."
  exit 2
fi

.venv/bin/fund-agent
EXIT_CODE=$?
echo ""
echo "程序退出码：$EXIT_CODE"
read -r "?按回车关闭窗口..."
exit "$EXIT_CODE"
