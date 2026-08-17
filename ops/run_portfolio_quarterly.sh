#!/bin/zsh
set -eu

SCRIPT_DIR=${0:A:h}
PROJECT_ROOT=${SCRIPT_DIR:h}
PYTHON_BIN=${FUND_AGENT_PYTHON:-/opt/anaconda3/bin/python}

cd "$PROJECT_ROOT"
mkdir -p outputs/quarterly/portfolio outputs/quarterly/reports

env PYTHONPATH=src "$PYTHON_BIN" -m fund_holdings_agent.portfolio_cli \
  --roster data/managers_portfolio.csv \
  --output-root outputs/quarterly/portfolio \
  --company-report-output-root outputs/quarterly/reports \
  --personnel data/personnel_internal_20260616.csv \
  --workers 4 \
  --retries 3 \
  --timeout 20 \
  --sleep 0.3 \
  --retry-errors \
  --skip-reports
