# 基金持仓 Agent（确定性基础管道与季度自动化）

转交给其他AI Agent或维护人员前，请先阅读 [AI Agent转交注意事项](docs/AI_AGENT_HANDOFF.md)。

本项目把基金季度前十大重仓数据处理拆成确定性的 Python 流程：读取名单、抓取东方财富/天天基金 F10、清洗、报告期经理核验、A/C/E 份额去重、异常分类、导出正式 Excel。当前版本不调用任何大模型或 DeepSeek API。

## 快速运行

### 最近三季度简报（第一阶段第二个纵向切片）

当同一经理连续三个季度的单季标准结果已经生成后，可汇总为两张工作表的简报版 Excel，并可从同一份确定性数据生成分析 PDF：

```bash
.venv/bin/fund-three-quarter \
  --manager-root outputs/quarterly/portfolio/长安基金 \
  --manager 徐小勇 \
  --end-report-date 2026-06-30 \
  --data-output outputs/徐小勇_2025Q4-2026Q2_三季度持仓数据.json \
  --excel-output outputs/徐小勇_2025Q4-2026Q2_三季度前十大持仓简报.xlsx
```

输入根目录需包含 `徐小勇_2025Q4`、`徐小勇_2026Q1`、`徐小勇_2026Q2` 等目录，且各目录内至少有
`manager_fund_pool_data.json` 和 `industry_analysis_data.json`。简报只显示 A 股，按基础产品对 A/C/E
份额去重，并保留公开披露的原排名；非 A 股排名留空且不递补。输出固定为 `01_三季持仓` 和
`99_说明异常`，不调用 DeepSeek。

Mac 安装版无需手工准备三个目录。双击 `基金持仓Agent.command` 后选择菜单第一项，或运行：

```bash
.venv/bin/fund-agent brief --manager 徐小勇 --end-report-date 2026-06-30 --output-format both
```

程序会自动计算 2025Q4、2026Q1、2026Q2，复用已经完成的季度，只补跑缺失、等待或失败季度；
三个季度均可用后才生成正式简报。`--output-format` 可选 `excel`、`pdf` 或 `both`；PDF包含持仓比例、申万一级行业分布以及首末季度新增/退出股票。跨产品比例为各基础产品披露值的算术汇总，不代表统一组合的加权仓位。若目标季度尚未披露完整，则退出并保留续跑状态，不会用上一季度回填。

### 一条命令运行完整季度流程

基金池、持仓、行业、研究资源、历史入库、相邻季度比较和正式报告现在可以由同一命令依次完成：

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

执行阶段固定为：`fund_pool → holdings → readiness → industry → resources → history → comparison → reports`。`readiness` 按基础产品确认至少一个代表份额返回指定报告期数据；目标季度披露不完整时，以 `waiting` 状态暂停，不会入库或生成正式版。零适用股票产品会形成可审计的“无适用产品”完成记录。每个阶段完成后都会原子更新 `batch_manifest.json`；相同参数重复执行时会校验产物并跳过已完成阶段，网络抓取也优先复用本地缓存。

恢复和维护参数：

- 普通续跑：重复执行原命令，从首个失败、未完成或产物缺失的阶段继续。
- `--retry-errors`：从首个带业务错误的阶段重新执行，并重建其下游结果。
- `--force-stage holdings`：强制从指定阶段开始重跑；可选值与上述阶段名一致。
- `--refresh`：忽略抓取缓存并重新请求公开数据源。
- `--skip-reports`：只生成结构化数据和历史结果，暂不构建 Excel。
- `--allow-incomplete-disclosure`：仅供人工确认产品不适用后的例外运行；默认禁止不完整数据继续流入正式结果。

供外部定时器重复调用时，使用会自动选择最近已结束自然季度的入口：

```bash
PYTHONPATH=src python -m fund_holdings_agent.quarterly_cli \
  --manager 于威业 \
  --manager-id 30814729 \
  --output-root outputs/quarterly \
  --personnel data/personnel_internal_20260616.csv
```

如果上一次检查处于 `waiting`，该入口会自动刷新持仓数据并从 `holdings` 阶段重试。退出码 `0` 表示完成，`2` 表示等待披露，`3` 表示已完成但有业务异常，`1` 表示技术失败；`batch_summary.json` 同时提供可直接发送的通知摘要。

多位经理可使用标准名单批量运行。统一名单 `data/managers_portfolio.csv` 当前包含长安基金 5 位和广发基金 20 位经理；两个公司单独的核验名单也分别保存在 `data/managers_changan.csv` 和 `data/managers_guangfa.csv`。

```bash
PYTHONPATH=src python -m fund_holdings_agent.portfolio_cli \
  --roster data/managers_portfolio.csv \
  --output-root outputs/quarterly/portfolio \
  --personnel data/personnel_internal_20260616.csv
```

不指定 `--as-of` 时，批量入口严格使用北京时间（`Asia/Shanghai`）当天判断最近已结束季度。输出先按基金公司分目录，再按经理和季度分目录；所有经理共享网页缓存、行业缓存和 SQLite 历史库。单人失败不会阻止其余经理继续运行；总状态及逐人状态写入 `portfolio_summary_YYYYQn.json`，同时生成可直接查看的 `portfolio_notification_YYYYQn.txt` 中文回执。

生产环境可直接调用项目脚本：

```bash
./ops/run_portfolio_quarterly.sh
```

该脚本启用业务错误补跑、断点续跑和缓存，只生成经理结构化底稿及公司正式报表，避免每次重复构建全部单经理 Excel。建议由 Codex 自动化在季度结束后的披露月（1、4、7、10 月）按北京时间重复触发；无需配置 Slack。手动运行方式、披露窗口、退出码与 cron/launchd 配置示例见 [季度定时调度与部署说明](docs/scheduling_deployment.md)。

完整命令、状态定义和故障恢复说明见 [季度批处理与断点续跑](docs/batch_run.md)。当前流程仍然不调用 DeepSeek 或其他大模型。

第一阶段可使用统一验收门禁复核项目结构、名单范围、资源回填、候选确认、隐私、Excel 结构、DeepSeek 运行时边界和自动测试：

```bash
PYTHONPATH=src python -m fund_holdings_agent.acceptance_cli \
  --backfill-summary outputs/personnel_import/20260616/resource_backfill_summary_2026Q2_confirmed.json \
  --company-summary outputs/company-resources/2026Q2/company_resource_summary_2026Q2.json \
  --output outputs/phase1_acceptance_2026Q2.json \
  --run-tests
```

当前2026Q2验收结果为12项全部通过、失败0，自动测试78项通过；结论为“第一阶段可使用，带已披露边界”。

真实新季度开始前，可先运行完全离线的季度切换演练。演练不会请求天天基金／东方财富，也不会调用 DeepSeek；它验证北京时间切换、禁止上一季度回退、披露等待、从持仓阶段续跑，以及名单、人员库和候选确认关系的复用：

```bash
PYTHONPATH=src python -m fund_holdings_agent.quarter_rehearsal_cli \
  --target-report-date 2026-09-30 \
  --output-dir outputs/quarter_rehearsal_2026Q3
```

2026Q3离线演练结果为9项全部通过、失败0。系统在北京时间2026-09-30仍选择2026Q2，在2026-10-01才切换到2026Q3；上一季度响应不能代替目标季度。第一次模拟运行以退出码2停在披露等待，第二次从 `holdings` 阶段续跑并以退出码0完成，基金池阶段没有重复执行。

已披露历史季度还可以进行全量准生产回放。以下命令读取本地2026Q1和2026Q2真实结果，勾稽50个季度任务、25份逐经理比较和公司共同管理去重，并生成两家公司变化分析 Excel 与统一回放报告；默认不发起数据抓取：

```bash
PYTHONPATH=src python -m fund_holdings_agent.preproduction_replay_cli \
  --portfolio-root outputs/quarterly/portfolio \
  --roster data/managers_portfolio.csv \
  --output-dir outputs/preproduction_replay_2026Q1_to_Q2
```

当前回放结果为9项全部通过、失败0：25位经理两期共50个任务全部完成，25份逐经理比较齐全；逐经理正式持仓由750行增至770行，公司级消除共同管理重复后由730行增至750行，两期各移除20行且数值冲突为0。两期A股申万一级当前快照覆盖率均为100%。

网络、网页、空持仓和缓存恢复可使用离线故障注入命令复核：

```bash
PYTHONPATH=src python -m fund_holdings_agent.failure_rehearsal_cli \
  --report-date 2026-06-30 \
  --output-dir outputs/failure_rehearsal
```

演练不会联网，覆盖临时／持续网络失败、失败阶段续跑、网页字段变化、A/C/E单份额空页、全部份额空页、原始及行业缓存物理损坏和旧季度缓存。空文件、乱码或含空字节的缓存会被移动为同目录 `.corrupt` 审计副本，新内容通过临时文件原子替换；可读取但结构变化的页面仍由解析器和披露门禁阻断，不会被静默覆盖。

### 分步运行

先按“基金经理 + 报告期”生成历史时点基金池：

```bash
PYTHONPATH=src python -m fund_holdings_agent.fund_pool_cli \
  --manager 于威业 \
  --report-date 2026-03-31 \
  --output-dir outputs/local-run
```

该命令输出 `manager_fund_pool_data.json`、审计 Excel 和网页原始缓存。基金池以经理档案的完整任职历史为主来源，再用基金基本概况和经理变动历史交叉核验；不会仅根据当前在管列表倒推历史报告期。

持仓抓取命令：

```bash
python -m fund_holdings_agent \
  --input data/funds_sample.csv \
  --report-date 2026-03-31 \
  --output-dir outputs/local-run
```

也可以把上一步生成的基金池 JSON 直接传给持仓管道，无需人工制作 CSV：

```bash
PYTHONPATH=src python -m fund_holdings_agent \
  --input outputs/local-run/manager_fund_pool_data.json \
  --report-date 2026-03-31 \
  --output-dir outputs/local-run
```

持仓抓取完成后，可追加申万一级行业当前快照分析：

```bash
PYTHONPATH=src python -m fund_holdings_agent.industry_cli \
  --input outputs/local-run/pipeline_data.json \
  --output-dir outputs/local-run
```

行业模块使用公开页面识别申万二级行业，再确定性映射到申万一级行业，并输出覆盖率、勾稽检查和行业异常。未配置带纳入/剔除日期的数据源时，结果会明确标记为“当前快照”，不得冒充报告期历史行业归属。

行业分析完成后，可生成研究员／专家对接需求。当前允许使用只有表头的空人员库运行；系统会输出完整的行业需求、公司需求和待补充项，不会虚构人员姓名。券商研究所通讯录（内部数据，不进入公开仓库）可先通过确定性导入工具转换为标准人员库：

```bash
PYTHONPATH=src python -m fund_holdings_agent.personnel_import_cli \
  --input "<内部通讯录XLSX路径>" \
  --output data/personnel_internal_20260616.csv \
  --summary outputs/personnel_import/20260616/personnel_import_summary.json \
  --organization "某券商研究所" \
  --email-domain "broker.example.com" \
  --source-date 2026-06-16 \
  --overrides data/personnel_manual_overrides.csv
```

默认导入研究条线人员，排除销售、运营、业务协同和合规质控人员；电话和邮箱不复制到项目人员库，联系权限统一为“需审批”。原研究分组映射到申万一级行业时保留映射依据：直接或组合映射作为组级推定，得 40 分；宽口径候选映射得 30 分并标记待确认。`personnel_manual_overrides.csv` 只保存业务人员明确确认的补充口径（具体人员与公司映射属于内部数据，保存在内部工作文档中，不进入公开仓库）；未确认字段保持为空。

如需把新人员库应用到已经完成的历史季度，可只重算研究资源阶段，不重新联网抓取基金或行业数据：

```bash
PYTHONPATH=src python -m fund_holdings_agent.resource_backfill_cli \
  --roster data/managers_portfolio.csv \
  --output-root outputs/quarterly/portfolio \
  --report-date 2026-06-30 \
  --personnel data/personnel_internal_20260616.csv \
  --summary outputs/personnel_import/20260616/resource_backfill_summary_2026Q2.json
```

回填入口逐经理覆盖原 `resource_matching_data.json`，但不伪装成原批处理任务重跑；人员库文件 SHA-256、北京时间、成功/失败经理、公司汇总和待补充行业均记录在独立审计摘要中。当前业务不考虑港股资源对接，因此 `不适用`、`申万不适用`和`待核查`既不生成申万行业需求，也不进入公司专家待补充项；原持仓仍保留，并在 `excluded_demands` 和 Excel 的“不纳入资源匹配”页中单独审计。

逐经理资源结果完成后，可离线生成每家基金公司的正式研究资源对接汇总：

```bash
PYTHONPATH=src python -m fund_holdings_agent.company_resource_cli \
  --roster data/managers_portfolio.csv \
  --input-root outputs/quarterly/portfolio \
  --report-date 2026-06-30 \
  --output-root outputs/company-resources/2026Q2 \
  --personnel data/personnel_internal_20260616.csv
```

该命令不联网、不调用 DeepSeek，每家公司生成一份含运行摘要、经理概览、行业／公司／人员汇总、匹配明细、候选项、待补充项、港股排除审计、数据校验和来源口径的 11 页 Excel。经理需求采用逐经理结果算术汇总，共同管理基金可能重复，不能解释为基金公司唯一组合持仓。

如业务人员已经逐项确认本期全部候选，可在同一固定报告期运行中增加 `--confirm-all-candidates --confirmed-by "确认人或来源"`。系统会记录候选快照 SHA-256、确认来源和北京时间；确认只改变确认状态，不提高原匹配分，也不会把30分宽口径候选改写成公司精确覆盖。

确认完成后，可把公司级审计包中的确认结果沉淀为跨季度复用的确定性规则库：

```bash
PYTHONPATH=src python -m fund_holdings_agent.candidate_confirmation_cli \
  --input outputs/company-resources/2026Q2/广发基金/广发基金_2026Q2_研究资源汇总_data.json \
  --input outputs/company-resources/2026Q2/长安基金/长安基金_2026Q2_研究资源汇总_data.json \
  --output data/resource_candidate_confirmations.csv
```

季度运行、批处理和历史回填默认读取该规则库。规则键为“需求类型 + 目标代码 + 人员姓名 + 机构”，因此只复用已确认的同一关系；系统保留原始匹配类型和30分，不把业务确认误写成精确覆盖。已确认关系会去重为可复用规则（具体数量属于内部数据，不进入公开仓库）。

使用标准人员库运行匹配：

```bash
PYTHONPATH=src python -m fund_holdings_agent.resource_cli \
  --input outputs/local-run/industry_analysis_data.json \
  --personnel data/personnel_internal_20260616.csv \
  --output-dir outputs/local-run
```

人员库必填字段为姓名、机构、人员类型、当前状态和联系权限；没有申万行业的宏观、固收等人员可以保留，但不参与行业自动匹配。具体公司代码采用带市场后缀的标准代码（如 `688072.SH`）；多个行业或公司代码用逗号、中文逗号、顿号或分号分隔。匹配仅使用在岗人员，优先级为：公司精确覆盖 100 分、申万二级覆盖 70 分、人工确认申万一级覆盖 50 分、通讯录研究分组映射 40 分、候选映射 30 分。公司或二级行业已命中时不再追加更宽泛的一级行业候选。联系方式仅在权限为“允许”时显示。该步骤同样不调用 DeepSeek 或其他大模型。

相邻季度数据均完成后，可生成确定性的持仓变化分析：

```bash
PYTHONPATH=src python -m fund_holdings_agent.compare_cli \
  --previous outputs/2025Q4/pipeline_data.json \
  --current outputs/2026Q1/pipeline_data.json \
  --previous-industry outputs/2025Q4/industry_analysis_data.json \
  --current-industry outputs/2026Q1/industry_analysis_data.json \
  --output-dir outputs/comparison
```

公司层和基金层按披露持股数量判定新进、退出、增持、减持和持平；行业层按申万一级行业的前十大持仓净值比例算术合计判断方向。该算术合计只用于变化方向和勾稽，不代表统一组合的真实行业暴露。比较命令只接受相邻自然季度，并检查基金范围、抓取错误和行业快照日期。

季度结果和比较结果可幂等写入 SQLite 历史库：

```bash
PYTHONPATH=src python -m fund_holdings_agent.history_cli ingest-quarter \
  --db outputs/history.sqlite \
  --pipeline outputs/2026Q1/pipeline_data.json \
  --industry outputs/2026Q1/industry_analysis_data.json

PYTHONPATH=src python -m fund_holdings_agent.history_cli ingest-comparison \
  --db outputs/history.sqlite \
  --comparison outputs/comparison/quarter_comparison_data.json

PYTHONPATH=src python -m fund_holdings_agent.history_cli status --db outputs/history.sqlite
```

同一基金经理、同一报告期重复写入时更新原运行，不增加重复记录。数据库保存输入文件路径和 SHA-256，并提供正式持仓及公司变化查询视图。表结构和查询示例见 [SQLite 历史数据库](docs/history_database.md)。

若未安装为包，可使用：

```bash
PYTHONPATH=src python -m fund_holdings_agent --input data/funds_sample.csv --report-date 2026-03-31 --output-dir outputs/local-run
```

输入 CSV 必填列：`manager,fund_code,fund_name`。可选列：`fund_type,inception_date`。

输出包括：

- `fund_holdings_YYYYQn.xlsx`：正式工作簿
- `pipeline_data.json`：可审计的结构化中间结果
- `run_summary.json`：运行摘要
- `disclosure_readiness.json`：逐基金目标季度披露完整性和重试状态
- `run.log`：逐基金请求与异常日志
- `resource_matching_data.json`：研究资源需求、匹配和待补充项的结构化结果
- `data/personnel_internal_20260616.csv`：从通讯录确定性导入的研究条线标准人员库（默认不含电话和邮箱）
- `data/personnel_manual_overrides.csv`：业务人员确认的人员／行业／公司补充口径，可重复合并
- `data/resource_candidate_confirmations.csv`：已确认候选关系规则库，供后续季度确定性复用
- `outputs/personnel_import/20260616/candidate_confirmation_registry_summary_2026Q2.json`：候选确认规则去重、数量和哈希审计摘要
- `outputs/personnel_import/20260616/personnel_import_summary.json`：通讯录导入、排除、行业覆盖和隐私策略摘要
- `outputs/personnel_import/20260616/resource_backfill_summary_2026Q2.json`：25位经理研究资源历史回填审计摘要
- `研究资源对接准备.xlsx`：行业需求、公司需求、匹配结果、人员库模板和匹配口径
- `公司简称_YYYYQn_研究资源对接汇总.xlsx`：按基金公司拆分的正式研究资源汇总、候选确认和审计报告
- `quarter_comparison_data.json`：相邻季度公司、基金内持仓及行业变化明细
- `基金季度持仓变化分析.xlsx`：公式驱动的季度变化、质量检查和审计来源
- `fund_holdings_history.sqlite`：可重复写入的季度历史、行业、异常和比较结果数据库

## 数据口径

- 基金代码统一为 6 位纯数字；股票代码根据接口行情链接补 `.SH/.SZ/.BJ/.HK`，海外代码保留原样。
- 报告期必须是自然季度末（03-31、06-30、09-30、12-31）。
- 基金成立日晚于报告期时排除；成立至报告期末不足两个日历月时按当期可免编定期报告分类，不进入披露闸门。
- 每个份额的原始抓取结果完整保留；正式版按“基础基金名称 + 前十大股票代码序列”识别重复份额，优先保留 A，其次无份额后缀，再其次 E/D/H/I/Y/Z/B，最后 C。
- 默认按基金类型排除 FOF、货币、固收指数、非二级债基和商品／期货基金；二级债基、可转债基金以及直接披露股票持仓的 A 股、港股和海外产品可以进入正式版。ETF 联接等未定特殊产品仍需业务复核。
- A/C/E 等份额全部保留在底稿，披露闸门按基础产品判断；已有有效代表份额时，另一非代表份额空页不阻断。
- 少于 10 条但大于 0 条按实际披露保留并标记警告；空数据、请求失败、经理不一致、字段缺失等进入异常清单。

详见 [第一阶段盘点](docs/phase1_audit.md)。

## 上线前健康检查

在本机手动运行或迁移到正式主机前，使用统一门禁检查环境、业务输入、缓存、SQLite 历史库、最近季度产物、离线演练和部署状态：

```bash
PYTHONPATH=src /opt/anaconda3/bin/python -m fund_holdings_agent.deployment_healthcheck_cli \
  --project-root . \
  --portfolio-root outputs/quarterly/portfolio \
  --report-date 2026-06-30 \
  --run-tests
```

默认不访问外部网站，也不调用 DeepSeek。迁移到正式部署主机后，可显式增加 `--check-network` 真实探测天天基金／东方财富；该选项会产生网络请求。

健康检查分别输出两个结论：

- `manual_run_readiness`：`READY`、`READY_WITH_WARNINGS` 或 `BLOCKED`，用于判断能否人工启动任务；
- `automation_deployment_status`：`DEPLOYED` 或 `NOT_DEPLOYED`，只有发现实际 cron、launchd、容器或 CI 调度配置时才视为已部署。

当前实际检查结果为 `READY_WITH_WARNINGS`／`NOT_DEPLOYED`：19项检查中15项通过、0项阻断失败、4项警告或跳过，全量自动测试89项通过。非阻断项包括人员库28条已知警告、部署主机真实网络探测未执行、尚未配置常驻季度调度，以及历史申万行业仍使用当前公开快照。

检查产物保存在 `outputs/019fff23-cef4-7d91-8837-7401263c06d4/deployment_healthcheck/`，包括机器可读 JSON、中文健康检查报告和部署待办清单。

## Mac 开发者命令行版本

项目提供统一的 `fund-agent` 入口，供内部Mac技术用户通过终端或双击菜单运行。首次使用可双击 `install.command`，之后双击 `基金持仓Agent.command` 进入中文菜单。

中文菜单默认第一项是“生成最近三季度持仓报告（可选Excel或分析PDF，推荐）”；选择经理和报告期后，用户可继续选择 Excel 持仓简报、含比例与季度变化的 PDF 分析报告或两者都要。第二项保留单季度完整分析。

```bash
fund-agent init
fund-agent doctor
fund-agent run --report-date 2026-06-30
fund-agent retry --manager 徐小勇 --report-date 2026-06-30
fund-agent brief --manager 徐小勇 --end-report-date 2026-06-30 --output-format both
fund-agent status
fund-agent results
fund-agent open-results
```

Mac用户配置、缓存和SQLite默认保存到 `~/Library/Application Support/FundHoldingsAgent/`，正式Excel和PDF保存到 `~/Documents/FundHoldingsAgent/`，因此更新代码不会直接覆盖用户历史数据。

当前Mac CLI的Excel和PDF导出已迁移为纯Python `openpyxl` 与 `reportlab` 实现。正式运行不再调用Node、`@oai/artifact-tool` 或Codex工作区依赖，仓库可以在另一台Mac通过标准Python虚拟环境安装。`doctor` 会直接检查两项生成组件。详见 [Mac CLI 分发与使用说明](docs/mac_cli_distribution.md)。

可直接构建给另一台Mac使用的ZIP。默认框架版使用空研究人员库；增加 `--include-internal-data` 才会包含内部研究人员库和已确认对接关系：

```bash
PYTHONPATH=src python -m fund_holdings_agent.distribution --output-dir dist
PYTHONPATH=src python -m fund_holdings_agent.distribution --output-dir dist --include-internal-data
```
