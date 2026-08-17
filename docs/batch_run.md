# 季度批处理与断点续跑

## 1. 目标

`fund_holdings_agent.batch_cli` 将已验证的确定性模块串联成一个季度任务。它只负责调度 Python 数据工具，不调用 DeepSeek，也不让模型修改基金池、持仓、行业或数值结果。

## 2. 完整命令

```bash
PYTHONPATH=src python -m fund_holdings_agent.batch_cli \
  --manager 于威业 \
  --manager-id 30814729 \
  --report-date 2026-03-31 \
  --output-dir outputs/runs/于威业_2026Q1 \
  --raw-cache-dir outputs/cache/raw \
  --industry-cache-dir outputs/cache/industry \
  --personnel data/personnel_internal_20260616.csv \
  --history-db outputs/fund_holdings_history.sqlite \
  --previous-dir outputs/runs/于威业_2025Q4
```

`--previous-dir` 可省略；省略时只完成本季度处理和历史入库，不生成相邻季度比较。项目生产运行使用已导入的券商研究所研究条线人员库（内部数据）；也可以显式改用空模板，届时所有行业和公司需求会进入待补充项，不会生成虚构姓名。

## 3. 阶段和依赖

| 阶段 | 主要输入 | 主要产物 |
|---|---|---|
| `fund_pool` | 基金经理、报告期 | `manager_fund_pool_data.json` |
| `holdings` | 报告期基金池 | `pipeline_data.json`、`run_summary.json` |
| `readiness` | 持仓抓取结果 | `disclosure_readiness.json`；不完整时暂停 |
| `industry` | 正式持仓 | `industry_analysis_data.json` |
| `resources` | 行业分析、人员库 | `resource_matching_data.json` |
| `history` | 本期及可选上期结构化数据 | SQLite 历史库 |
| `comparison` | 相邻季度持仓和行业结果 | `quarter_comparison_data.json` |
| `reports` | 各阶段结构化结果 | 4 份正式 Excel |

阶段严格按上述顺序执行。下游阶段不会在上游失败时继续运行，也不会在目标季度披露不完整时提前生成正式结果。

## 4. 任务清单

输出目录中的 `batch_manifest.json` 是可恢复任务清单，记录：

- 固定后的运行参数；
- 每个阶段的 `pending`、`running`、`waiting`、`completed`、`completed_with_errors`、`failed` 或 `skipped` 状态；
- 阶段开始和完成时间、尝试次数及错误信息；
- 需要存在的结构化文件和报告文件。

任务清单采用临时文件替换方式更新，避免进程中断后留下半写入 JSON。`batch_summary.json` 记录本次调用实际执行和跳过的阶段，可用于外层调度或通知。

`batch_summary.json` 还包含 `exit_code`、`next_action` 和 `notification_summary`。退出码约定如下：

| 退出码 | 含义 | 外层调度建议 |
|---:|---|---|
| 0 | 全部完成 | 发送成功通知，等待下一季度 |
| 1 | 技术失败 | 告警并保留现场，修复后续跑 |
| 2 | 披露未完整 | 不告警；下一检查窗口再次运行 |
| 3 | 完成但有业务异常 | 发送待核查通知 |

## 5. 恢复规则

### 5.1 普通断点续跑

进程中断后原样重复运行命令。系统检查任务清单及阶段产物，从首个失败、未完成或缺少产物的阶段继续；此前已经完成且产物仍存在的阶段会被跳过。

### 5.2 重试业务错误

```bash
PYTHONPATH=src python -m fund_holdings_agent.batch_cli [原参数] --retry-errors
```

系统从首个 `completed_with_errors` 阶段开始重跑，并重新执行依赖该结果的所有下游阶段。成功请求继续使用缓存，因此不会无条件重抓全部基金。

### 5.3 强制重跑指定阶段

```bash
PYTHONPATH=src python -m fund_holdings_agent.batch_cli [原参数] --force-stage holdings
```

该参数会从指定阶段开始重跑并重建下游结果。修改基金经理、报告期或关键输入路径时，应使用新的输出目录，避免混用不同任务的清单。

### 5.4 披露等待和人工例外

持仓接口可能一次返回同一年多个季度。解析器必须命中指定报告期，不会在目标季度缺失时回退到最新季度。披露闸门按基础产品而非份额数量判断：同一 A/C/E 产品只要一个代表份额成功即可；所有代表份额均无目标季度持仓、请求失败或报告期不一致时，默认流程停在 `readiness=waiting`。基金池为空时输出“无适用产品”并正常完成。

下一检查窗口应重新请求持仓：

```bash
PYTHONPATH=src python -m fund_holdings_agent.batch_cli [原参数] \
  --refresh --force-stage holdings
```

只有人工确认某基金产品确实不适用股票持仓后，才可显式增加 `--allow-incomplete-disclosure`。该运行仍会保留业务异常状态和待核查记录。

## 6. 定时器入口

```bash
PYTHONPATH=src python -m fund_holdings_agent.quarterly_cli \
  --manager 于威业 \
  --manager-id 30814729 \
  --output-root outputs/quarterly \
  --personnel data/personnel_internal_20260616.csv
```

该入口按运行日自动确定最近已结束的自然季度，采用 `{基金经理}_{YYYYQn}` 作为季度目录，并自动寻找上一季度目录。若上次状态为 `waiting`，本次会自动启用刷新并从持仓阶段重试，适合在季度结束后的披露窗口由 cron、任务平台或 Codex 自动化重复调用。

多经理生产任务统一调用：

```bash
./ops/run_portfolio_quarterly.sh
```

生产入口具有以下固定行为：

- 未传 `--as-of` 时，以 `Asia/Shanghai` 北京时间当天作为检查日期；不受电脑当前时区影响。
- 在上次状态为 `waiting` 时刷新持仓并从持仓阶段续跑。
- 始终带 `--retry-errors`，因此已有业务异常会在下一检查窗口重新执行，成功缓存不会无条件重抓。
- 单经理 Excel 默认跳过，但公司正式 Excel 正常生成到 `outputs/quarterly/reports`。
- 每次写出 `portfolio_notification_YYYYQn.txt` 本地中文回执，包含状态、指标、报告路径、待处理项和下一步。
- 使用 `data/personnel_internal_20260616.csv` 进行研究资源组级匹配；该文件默认不保存电话和邮箱，联系方式仍需审批。
- 不调用 DeepSeek，不向 Slack 或其他外部渠道发送内容。

推荐的 Codex 自动化节奏是：在 1、4、7、10 月的披露窗口内，以北京时间每 5 天检查一次。披露未完整时退出码为 2 并等待下一次触发；任务完成后重复调用会复用任务清单和缓存。

## 7. 缓存与历史库

- `--raw-cache-dir` 保存基金经理页面、基金基本信息和季度持仓响应。
- `--industry-cache-dir` 保存股票行业公开页面结果。
- `--refresh` 明确要求重新请求公开数据源；正常季度运行无需使用。
- SQLite 使用业务主键幂等更新。同一基金经理和报告期重复入库不会产生重复季度；同一相邻季度比较也不会重复增加记录。

生产运行建议让不同季度共用缓存目录和历史库，但为每个“基金经理 + 报告期”创建独立输出目录。

人员库更新后，如果持仓和行业数据已经完成，可使用独立回填入口只更新研究资源结果：

```bash
PYTHONPATH=src python -m fund_holdings_agent.resource_backfill_cli \
  --roster data/managers_portfolio.csv \
  --output-root outputs/quarterly/portfolio \
  --report-date 2026-06-30 \
  --personnel data/personnel_internal_20260616.csv \
  --candidate-confirmations data/resource_candidate_confirmations.csv \
  --summary outputs/personnel_import/20260616/resource_backfill_summary_2026Q2.json
```

该命令不联网、不重算基金池和持仓，也不修改原批处理任务清单；它使用独立摘要记录人员库哈希、逐经理状态、待补充行业和公司。当前业务不考虑港股资源对接：港股等申万不适用公司不形成行业或公司对接需求，但会保留在排除审计中。

需要把逐经理资源结果交付给业务人员时，再运行公司级离线汇总：

```bash
PYTHONPATH=src python -m fund_holdings_agent.company_resource_cli \
  --roster data/managers_portfolio.csv \
  --input-root outputs/quarterly/portfolio \
  --report-date 2026-06-30 \
  --output-root outputs/company-resources/2026Q2 \
  --personnel data/personnel_internal_20260616.csv
```

入口按公司读取各经理的 `resource_matching_data.json`，生成公司级 JSON 审计包和 11 页正式 Excel；全过程不联网、不调用 DeepSeek。摘要中的需求数、市值和净值比例均为经理结果算术合计，共同管理基金会在不同经理结果中重复，不能作为基金公司统一组合的去重暴露。

业务人员完成候选复核后，可在固定报告期命令中增加 `--confirm-all-candidates --confirmed-by "确认人或来源"`。该选项仅对本次输入形成的候选快照生效，并记录快照 SHA-256、确认来源和北京时间；原始30分匹配等级保持不变。

候选确认完成后，应使用 `fund_holdings_agent.candidate_confirmation_cli` 将一个或多个公司级 JSON 审计包合并为 `data/resource_candidate_confirmations.csv`。批处理、季度入口和资源历史回填默认读取该文件；复用仅按“需求类型 + 目标代码 + 人员姓名 + 机构”精确命中，并保留原始候选匹配类型和分数。规则库路径和 SHA-256 会写入回填摘要、逐经理资源结果及公司级正式报告的“来源与口径”。

## 8. 当前边界

- 申万行业原型使用当前公开快照；报告期历史行业归属仍需接入带纳入和剔除日期的数据源。
- 已提供可重复调用的季度入口、北京时间判断、等待状态、退出码、本地中文回执和 Codex 自动化配置；邮件／Slack／企业微信等外部通知渠道未配置。
- 通讯录本身只支持研究分组层面的人员候选匹配；`personnel_manual_overrides.csv` 可补充经资源维护者确认的 `covered_stock_codes` 和 `covered_sw_level2`。未确认内容不得自动升级为个人精确覆盖。
- DeepSeek 未来仅可用于异常解释和文字摘要，不参与确定性事实与计算。

### 8.1 第一阶段验收门禁

每次冻结季度结果后运行：

```bash
PYTHONPATH=src python -m fund_holdings_agent.acceptance_cli \
  --backfill-summary outputs/personnel_import/20260616/resource_backfill_summary_2026Q2_confirmed.json \
  --company-summary outputs/company-resources/2026Q2/company_resource_summary_2026Q2.json \
  --output outputs/phase1_acceptance_2026Q2.json \
  --run-tests
```

门禁会勾稽名单人数、逐经理回填、公司级汇总、候选规则库哈希、确认状态、原始30分、联系方式隐藏、11个工作表、公式错误和 DeepSeek 运行时配置，并保存带来源哈希的 JSON 证据。任何阻断项失败时退出码为3。

### 8.2 新季度离线切换演练

季度末前先运行以下命令，不联网验证新季度控制：

```bash
PYTHONPATH=src python -m fund_holdings_agent.quarter_rehearsal_cli \
  --project-root . \
  --target-report-date 2026-09-30 \
  --roster data/managers_portfolio.csv \
  --personnel data/personnel_internal_20260616.csv \
  --candidate-confirmations data/resource_candidate_confirmations.csv \
  --output-dir outputs/quarter_rehearsal_2026Q3
```

该命令只使用合成持仓和本地名单，不访问外部网络，不生成真实季度 Excel，不调用 DeepSeek。检查范围包括：

- 北京时间季度边界；季度末次日才把新季度识别为最近结束季度；
- 目标季度未出现时返回明确异常，禁止上一季度数据回退；
- 披露不完整时返回 `waiting` 和退出码2并暂停下游；
- 下一次检查刷新持仓，从 `holdings` 阶段续跑；
- 25位经理名单、研究所人员库和候选确认规则库可读取；
- 同一候选关系在新季度重新出现时，可复用业务确认，但仍保持原30分及候选匹配类型。

输出包括 `quarter_rehearsal_summary_YYYYQn.json`、模拟任务清单及中文上线操作清单。演练通过只表示控制流程可用，不表示目标季度真实披露已经完成。

### 8.3 已披露季度全量准生产回放

使用已披露的相邻季度真实结果执行端到端勾稽：

```bash
PYTHONPATH=src python -m fund_holdings_agent.preproduction_replay_cli \
  --project-root . \
  --portfolio-root outputs/quarterly/portfolio \
  --roster data/managers_portfolio.csv \
  --previous-report-date 2026-03-31 \
  --current-report-date 2026-06-30 \
  --output-dir outputs/preproduction_replay_2026Q1_to_Q2
```

该入口读取两期本地批次摘要、逐经理管道结果、行业结果和季度比较，不访问公开网站。它重新生成公司级共同管理去重比较，核验：经理范围、50个任务状态、报告期防串期、25份比较完整性、错误数、共同管理重复数值一致性、公司持仓勾稽和A股行业覆盖率。输出包括机器可读摘要、中文回执、统一准生产报告以及长安／广发公司级变化分析 Excel。

2026Q1至2026Q2实际回放为9项通过、0项失败。逐经理正式持仓为750／770行；公司层各移除20行共同管理重复记录后为730／750行，去重冲突0。行业比较使用同一当前快照，仍须保留历史时点限制。

### 8.4 离线故障注入与恢复演练

```bash
PYTHONPATH=src python -m fund_holdings_agent.failure_rehearsal_cli \
  --report-date 2026-06-30 \
  --output-dir outputs/failure_rehearsal
```

九个场景分别验证：

- 临时网络失败在重试上限内恢复；持续失败达到上限后明确报错；
- `holdings` 阶段失败后重复执行只重跑失败阶段及下游；
- 网页字段变化解析为0行并进入披露等待，不误判成功；
- 同一基础产品一个份额有效时，另一个空页不阻断；全部份额空页时必须等待；
- 原始网页及行业缓存出现空文件、乱码或空字节时，移动为 `.corrupt` 审计副本并原子刷新；
- 缓存只有上一季度时禁止跨季度回退。

物理缓存损坏和网页语义变化必须区别处理。前者可以安全旁路并重新获取；后者不得自动删除证据，必须保留页面、修复解析器并从相应阶段重跑。演练输出机器可读摘要和中文故障处置手册。

### 8.5 上线前健康检查

```bash
PYTHONPATH=src /opt/anaconda3/bin/python -m fund_holdings_agent.deployment_healthcheck_cli \
  --project-root . \
  --portfolio-root outputs/quarterly/portfolio \
  --roster data/managers_portfolio.csv \
  --personnel data/personnel_internal_20260616.csv \
  --candidate-confirmations data/resource_candidate_confirmations.csv \
  --backfill-summary outputs/personnel_import/20260616/resource_backfill_summary_2026Q2_confirmed.json \
  --report-date 2026-06-30 \
  --run-tests
```

门禁检查 Python、lxml、openpyxl、运行脚本权限、25位经理名单、研究所人员库、候选确认规则、磁盘空间和可写性、生产缓存、SQLite 完整性、最近季度25份逐经理产物、历史比较、阶段验收与三类演练证据，并扫描核心运行代码是否误接入 DeepSeek。

默认离线运行，真实网络探测只有增加 `--check-network` 才执行。`BLOCKED` 的退出码为3，表示存在必须先处理的阻断失败；`READY_WITH_WARNINGS` 的退出码为0，表示可手动运行但非阻断事项尚未闭环。是否已有自动调度单独输出，不会因为存在一个可执行脚本就误报为已部署。

2026-08-15实际检查结果为15项通过、0项阻断失败、4项警告或跳过，全量测试89项通过。手动运行就绪度为 `READY_WITH_WARNINGS`，自动化状态为 `NOT_DEPLOYED`。输出：

- `deployment_healthcheck.json`：机器可读结论和逐项证据；
- `上线健康检查报告.md`：完整中文检查表；
- `部署待办清单.md`：只列失败、警告和跳过项及处理动作。

## 9. 多经理批量运行

经理名单使用 CSV 保存，字段为 `company,manager,manager_id,active`。`manager_id` 必须是经过核验的天天基金经理 ID；停用记录可将 `active` 设置为 `no`。

```bash
PYTHONPATH=src python -m fund_holdings_agent.portfolio_cli \
  --roster data/managers_portfolio.csv \
  --output-root outputs/quarterly/portfolio \
  --personnel data/personnel_internal_20260616.csv
```

批量入口会顺序运行各经理，避免单人失败中止全部任务，并聚合以下结果：

- 每位经理的完成、等待披露、带异常完成或失败状态；
- 每位经理的季度输出目录和任务清单；
- 全公司的机器可读退出码和中文通知摘要；
- `portfolio_summary_YYYYQn.json` 审计文件。
- 每家公司各自的 `公司简称_YYYYQn_基金经理持仓分析.xlsx` 正式报表；即使使用统一多公司名单，也会按公司拆分生成，避免跨公司混算。

如仅需机器可读数据而暂不生成公司级 Excel，可使用 `--skip-company-report`；`--skip-reports` 只跳过单经理的三份 Excel，不影响公司级正式报表。
如需把正式公司报表与运行数据分开存放，可增加 `--company-report-output-root <目录>`；经理底稿和缓存仍留在 `--output-root`。

当前长安基金名单已完成 2026Q2 真实预检：5 位经理、34 个报告期基金份额全部披露就绪，去重后 17 个产品、170 条正式持仓，抓取错误为 0。

当前广发基金名单已完成 2026Q2 真实基准：20 位经理全部完成，纳入 108 个基金份额、60 个经理－产品组合，形成 600 条正式持仓；179 只唯一 A 股的当前申万行业匹配率为 100%，抓取错误为 0。7 位经理当期无适用直接股票产品，按正常完成记录。

统一名单当前包括：

- 长安基金管理有限公司：5 位经理；
- 广发基金管理有限公司：20 位经理；
- 合计 25 位，姓名、公司和天天基金经理 ID 均通过经理搜索接口及经理档案交叉核验。

同名经理允许存在于不同公司，但同一“公司 + 姓名”或同一经理 ID 不得重复。批量输出采用 `基金公司/经理_季度` 目录结构，避免同名经理覆盖结果。
