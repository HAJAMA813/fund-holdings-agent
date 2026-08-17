# 季度定时调度与部署说明

> 本文说明如何把「每季度披露后自动抓取」真正跑起来。调度能力（自动选择最近季度、
> 披露等待、断点续跑、退出码）**已经实现**；常驻定时任务（cron / launchd / 服务器）
> **尚未配置**，当前以手动运行为主。

## 1. 当前状态

- 手动运行就绪：`READY_WITH_WARNINGS`
- 自动化部署状态：`NOT_DEPLOYED`（未配置实际 cron / launchd / 容器 / CI 调度）

「有可执行脚本」不等于「已部署」。只有在目标主机配置了真实定时调度、日志留存和失败
通知，并在该主机完成真实网络探测后，才算部署完成。

## 2. 手动运行（当前推荐）

### 方式 A：Mac 菜单

双击 `基金持仓Agent.command`，选 `3. 运行全部25位基金经理（单季度）`，再输入 `RUN` 确认。

### 方式 B：命令行（生产脚本）

```bash
./ops/run_portfolio_quarterly.sh
```

该脚本等价于按北京时间选择最近已结束季度，对 25 位经理依次执行
`fund_pool → holdings → readiness → industry → resources → history → comparison → reports`，
启用业务错误补跑、断点续跑和网页缓存，只生成经理结构化底稿及公司正式报表。

### 方式 C：单经理 / 单季度

```bash
PYTHONPATH=src python -m fund_holdings_agent.quarterly_cli \
  --manager 徐小勇 --manager-id 30046790 \
  --output-root outputs/quarterly --personnel data/personnel_internal_20260616.csv
```

## 3. 披露窗口与北京时间

- 业务时区固定 `Asia/Shanghai`，不随运行机器时区改变。
- 季度末为 03-31 / 06-30 / 09-30 / 12-31；披露窗口通常在季度结束后（1、4、7、10 月）。
- `quarterly_cli` 自动选择最近**已结束**自然季度：北京时间 2026-09-30 仍选 2026Q2，
  到 2026-10-01 才切换到 2026Q3。
- 目标季度披露不完整时，任务以 `waiting`（退出码 2）暂停，不生成正式版、不回填上一季度；
  下一检查窗口自动刷新持仓并从 `holdings` 阶段续跑，基金池不重复执行。

## 4. 退出码与通知

| 退出码 | 含义 | 外层调度建议 |
|---:|---|---|
| 0 | 全部完成 | 发送成功通知，等下一季度 |
| 1 | 技术失败 | 告警并保留现场，修复后续跑 |
| 2 | 披露未完整 | 不告警；下一窗口再跑 |
| 3 | 完成但有业务异常 | 发送待核查通知 |

机器可读通知摘要见 `batch_summary.json` / `portfolio_summary_YYYYQn.json`；中文回执见
`portfolio_notification_YYYYQn.txt`。当前不接 Slack 等外部通知渠道。

## 5. 如何配置定时任务（参考，尚未部署）

以下示例仅作为上线参考，正式配置前需先在部署主机完成 `--check-network` 真实探测。

### 5.1 macOS launchd（推荐，本机常驻）

新建 `~/Library/LaunchAgents/com.fundholdings.quarterly.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.fundholdings.quarterly</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>/path/to/fund-holdings-agent/ops/run_portfolio_quarterly.sh</string>
  </array>
  <!-- 每季度披露窗口的 1、4、7、10 月 1 日 08:30（北京时间由脚本内部处理） -->
  <key>StartCalendarInterval</key>
  <dict>
    <key>Month</key><integer>1</integer>
    <key>Day</key><integer>1</integer>
    <key>Hour</key><integer>8</integer>
    <key>Minute</key><integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/tmp/fundholdings-quarterly.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/fundholdings-quarterly.err</string>
</dict>
</plist>
```

加载：

```bash
launchctl load ~/Library/LaunchAgents/com.fundholdings.quarterly.plist
```

> 注意：launchd 的 `StartCalendarInterval` 一次只能写一个月份；如需覆盖 1/4/7/10 四个月，
> 需在同一个 plist 里写四个 `StartCalendarInterval` 数组条目（Apple 支持多 interval）。

### 5.2 服务器 cron（Linux）

```cron
# 每季度披露窗口的 1、4、7、10 月 1 日 08:30
30 8 1 1,4,7,10 * /path/to/fund-holdings-agent/ops/run_portfolio_quarterly.sh >> /var/log/fundholdings-quarterly.log 2>&1
```

## 6. 上线前检查

```bash
PYTHONPATH=src python -m fund_holdings_agent.deployment_healthcheck_cli \
  --project-root . \
  --portfolio-root outputs/quarterly/portfolio \
  --report-date 2026-06-30 \
  --run-tests
```

只有在目标运行主机配置实际季度调度、日志留存和失败通知，并在该主机完成真实外部数据源
连通性检查后，`automation_deployment_status` 才会变为 `DEPLOYED`。

## 7. 为什么不现在配置常驻调度

- 下一披露窗口（2026Q3）在 2026 年 10 月，当前配置基本闲置。
- 没有第二台长期开机的部署主机；本机定时任务受「开机、联网」条件限制。
- 单机产品先以手动运行交付，定时调度作为上线阶段事项，按需在目标主机启用。
