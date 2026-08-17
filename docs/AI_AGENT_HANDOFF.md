# 基金持仓 Agent 转交注意事项

更新日期：2026-08-17  
接手对象：后续 AI Agent / 开发维护人员

## 1. 先明确项目的真实定位

当前项目是一个“确定性工作流 Agent”，不是已经接入大模型推理的 LLM Agent。它的 Agent 能力主要体现在：任务拆解与编排、工具调用、状态记录、披露等待、断点续跑、有限重试、异常分流、人工确认和多格式交付。

当前未配置、未调用 DeepSeek API，也没有其他大模型运行时。不要把现有规则计算描述成模型推理。未来可以增加自然语言理解、工具选择和研究摘要能力，但基金名单、持仓事实、行业分类、比例计算和异常判定必须继续由确定性代码完成。

## 2. 接手后优先阅读

按以下顺序了解项目：

1. `需求文档.md`：业务目标和正式数据口径。
2. `README.md`：完整功能、命令和历史建设过程。
3. `docs/mac_cli_distribution.md`：Mac安装、分发和数据边界。
4. `src/fund_holdings_agent/mac_cli.py`：面向用户的菜单和统一入口。
5. `src/fund_holdings_agent/three_quarter.py`：三季度标准数据集及分析指标。
6. `src/fund_holdings_agent/pdf_reports.py`、`excel_reports.py`：正式报告生成。
7. `tests/`：现有行为契约。修改代码前先阅读相关测试。

## 3. 当前已经完成

- 基金经理名单共25人：长安基金5人、广发基金20人。
- 根据基金经理和报告期建立基金池，并核验报告期任职关系。
- 抓取天天基金／东方财富季度前十大持仓。
- 基金产品筛选、A/C/E等份额去重、正式代表份额确定。
- 股票代码、市场和申万行业标准化，异常分类与审计底稿保留。
- 披露完整性门禁、缓存、失败重试和断点续跑。
- 连续三季度Excel简报及PDF分析报告。
- PDF包含持仓比例、行业分布、首末季度新增／退出股票和逐产品三季度明细。
- 研究人员库与候选确认关系匹配；港股当前不进入研究资源匹配。
- Mac中文菜单、安装脚本、框架版／内部完整版ZIP构建。
- 已使用徐小勇2025Q4至2026Q2真实数据生成并检查Excel和8页PDF。
- 当前自动测试基线：101项通过。

## 4. 不得擅自改变的业务口径

1. 业务时间统一使用 `Asia/Shanghai` 北京时间，不能使用运行机器本地时区判断季度。
2. 报告期必须是自然季度末：03-31、06-30、09-30或12-31。
3. 不得使用上一季度数据冒充目标季度；披露不完整时必须进入等待状态。
4. 基金归属必须依据报告期内任职区间，不能直接套用当前经理名单。
5. 同一基础产品的原始A/C/E份额必须保留在底稿，正式结果只使用代表份额，避免重复统计。
6. 三季度简报当前只展示A股；港股及其他市场不使用第11名以后持仓递补。
7. 申万行业沿用各季度结果中的分类快照。历史季度使用当前公开快照时必须保留警告，不能声称完全还原历史行业口径。
8. PDF中的跨产品市值和净值比例是各基础产品披露值的算术汇总，可能超过100%；它不代表基金经理统一组合的真实加权仓位。
9. 人员匹配不得根据姓名、职位或模糊标签猜测。未确认关系进入待补充项，不得由模型虚构研究员或专家。
10. 当前不考虑Slack，也不考虑港股研究资源对接。

已确认的姓名修正：长安基金经理为“林忠晶”，不是“林忠金”。

## 5. 核心代码位置

| 功能 | 主要文件 |
|---|---|
| Mac菜单与运行入口 | `src/fund_holdings_agent/mac_cli.py` |
| 多经理季度编排 | `portfolio_cli.py`、`quarterly_cli.py` |
| 单经理批处理与恢复 | `batch.py`、`batch_cli.py` |
| 基金池与经理核验 | `manager_funds.py`、`portfolio.py` |
| 持仓抓取与清洗 | `eastmoney.py`、`pipeline.py` |
| 份额去重 | `dedup.py` |
| 行业映射 | `industry.py` |
| 研究资源匹配 | `resource_matching.py`、`candidate_confirmations.py` |
| 三季度数据与变化分析 | `three_quarter.py` |
| Excel和PDF | `excel_reports.py`、`pdf_reports.py` |
| 历史库与季度比较 | `history.py`、`quarter_compare.py` |
| Mac交付包构建 | `distribution.py` |

## 6. 常用运行与验证命令

```bash
.venv/bin/fund-agent doctor
.venv/bin/fund-agent doctor --check-network
.venv/bin/fund-agent brief --manager 徐小勇 --end-report-date 2026-06-30 --output-format both
.venv/bin/fund-agent run --manager 徐小勇 --report-date 2026-06-30
.venv/bin/fund-agent retry --manager 徐小勇 --report-date 2026-06-30
.venv/bin/fund-agent status
.venv/bin/fund-agent results
.venv/bin/python -m pytest -q
```

构建Mac交付包：

```bash
.venv/bin/fund-build-mac-package --output-dir dist
.venv/bin/fund-build-mac-package --output-dir dist --include-internal-data
```

修改报告生成、菜单、数据结构或安装流程后，必须至少运行相关测试和全量测试；PDF修改还要渲染全部页面检查字体、截断、越界和空白页。

## 7. 用户数据与项目代码的位置

默认用户运行数据：

```text
~/Library/Application Support/FundHoldingsAgent/
├── config.json
├── portfolio/
├── state/
└── logs/
```

正式报告：

```text
~/Documents/FundHoldingsAgent/
```

更新代码或重新安装时，不得删除或覆盖上述用户历史目录。仓库中的 `.venv`、`outputs`、缓存和测试产物也不能打进正式分发包。

## 8. 敏感数据边界

以下内容不得上传公开GitHub、公共网盘或发送给未授权人员：

- `data/personnel_internal_20260616.csv`：内部研究人员库。
- `data/personnel_manual_overrides.csv`：业务确认的人员覆盖补充口径。
- `data/resource_candidate_confirmations.csv`：业务确认的人员对接关系。
- `data/internal_business_notes.json`、`docs/INTERNAL_NOTES.md`：真实机构、人员与专项覆盖口径，仅保存在本机。
- 正式Excel/PDF、SQLite历史库、缓存、日志及运行底稿。
- 后续加入的联系方式、授权行业数据和人工确认记录。

2026-08-17 已执行公开版脱敏：代码与公开文档不再出现内部机构名称和人员姓名；人员库文件已改为中性的内部文件名（旧名对照仅保存在本机内部文档）；通讯录导入的机构名与邮箱域名改为显式参数；季度演练的确认复用检查改为从规则库动态选取关系。内部原始信息统一保存在本机 gitignore 排除的 `docs/INTERNAL_NOTES.md` 与 `data/internal_business_notes.json`。

框架版ZIP必须使用空人员库和空候选确认模板；只有显式使用 `--include-internal-data` 才能构建内部完整版。内部完整版只限获授权人员使用。

## 9. 技术注意事项

- 支持Python 3.11及以上，目前在Python 3.13环境验证。
- Excel使用 `openpyxl`，PDF使用 `reportlab`；正式运行不依赖Codex、Node或工作区专用工具。
- PDF通过macOS自带的 `Arial Unicode.ttf` 嵌入中文字体；`fund-agent doctor` 会检查该字体。修改字体方案后必须再次做跨Mac验证。
- 安装必须使用普通wheel方式：`pip install --upgrade .`。不要改回 `pip install -e`，Python 3.13和macOS目录标记曾导致editable路径无法加载。
- 天天基金／东方财富可能出现限流、SSL EOF、页面结构变更或披露延迟。先判断是网络、网页结构还是业务披露问题，不要用放宽校验或伪造数据绕过。
- 工作区可能包含用户已有修改；不要使用 `git reset --hard`、批量覆盖或删除历史结果。

## 10. 仍未完成或需要真实环境确认

1. 已在本机临时干净目录模拟首次安装，但仍需至少一台其他真实Mac试装。
2. 尚未部署长期服务器、NAS或正式季度调度；当前主要是用户Mac手工启动。
3. 尚无图形界面；当前是双击 `.command` 后使用中文终端菜单。
4. 尚未完成不同macOS版本、Apple Silicon与Intel Mac的组合验证。
5. 公开网站结构发生变化时，解析器仍可能需要维护。
6. 真正的LLM Agent层尚未开发；不要在基础管道稳定性未确认前接入DeepSeek。

## 11. 建议的后续顺序

1. 在第二台Mac使用内部完整版ZIP完成安装、`doctor --check-network`和单经理真实运行。
2. 分别选择长安和广发各一位经理，验证抓取、缓存、续跑、Excel和PDF。
3. 固定版本号、变更记录和升级策略，确认升级不会破坏用户历史数据。
4. 再讨论自然语言Agent层：用户表达需求后由模型选择确定性工具，并只基于已校验JSON生成解释性摘要。
5. 大模型不得直接修改持仓事实、行业映射、异常状态或正式计算结果；所有模型文本都要标记来源和可回溯证据。

## 12. 接手完成标准

接手方至少应能回答并验证：

- 最近结束季度如何按北京时间计算；
- 某经理三季度数据缺一个季度时系统如何补跑；
- A/C/E份额为何不会重复进入正式结果；
- PDF比例为什么可能超过100%；
- 哪些数据可以进入框架版ZIP；
- 网络失败与披露未完成如何区分；
- 如何在不调用DeepSeek的情况下生成Excel和PDF；
- 如何运行101项测试并复现徐小勇样例结果。

如果上述问题尚未搞清楚，不应直接重构核心管道或接入大模型。
