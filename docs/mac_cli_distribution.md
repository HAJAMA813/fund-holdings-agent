# Mac CLI 分发与使用说明

## 1. 定位

本项目当前可作为面向技术用户的 Mac 命令行框架使用。终端只是操作入口，核心仍是确定性的基金池、季度持仓、A/C/E份额去重、行业分类、研究资源匹配、校验、异常恢复和Excel导出管道。

该形式不需要服务器，不需要 Codex 持续打开，也不调用 DeepSeek。它适合能够进行基础终端操作的内部用户；完全非技术用户仍建议后续增加图形界面。

## 2. 当前交付边界

代码可以通过私有 GitHub 仓库分发，但以下内部数据不得进入公开仓库：

- 券商研究所真实人员库（内部数据）；
- 候选确认规则及确认人员信息；
- 正式Excel、历史缓存、SQLite和运行日志；
- 受授权限制的行业数据文件。

Excel和PDF导出已经迁移为纯Python实现，正式运行依赖 `openpyxl` 和 `reportlab`，不需要 Codex、Node、`@oai/artifact-tool` 或本机外部符号链接。仓库内旧的 `.mjs` 生成器暂时作为迁移对照保留，但所有Python入口均不再调用它们。

## 3. 安装

前置条件：

- macOS；
- Python 3.11 或更高版本；
- 可通过 `pip` 安装项目声明的Python依赖；
- 能够访问天天基金／东方财富的网络。

从私有仓库下载后，可以双击 `install.command`。脚本会在项目目录创建 `.venv`、以普通 wheel 方式安装当前项目、验证包可加载、初始化Mac用户目录，并执行离线环境诊断。安装不使用 editable `.pth`，避免 macOS 隐藏目录标记导致 Python 3.13 跳过包路径。也可以在终端运行：

```bash
./install.command
```

维护人员也可以直接发送构建好的 ZIP，不要求接收者使用 GitHub。解压后保留整个文件夹，首次使用右键打开 `install.command`，安装成功后双击 `基金持仓Agent.command`。两种交付包的边界如下：

- `mac-framework`：开发框架版，包含25位基金经理名单，但研究人员库和候选确认关系是空模板；适合二次开发、演示或不使用研究资源匹配的用户。
- `mac-internal`：内部完整版，包含研究人员库和已经确认的对接关系；只能发送给获授权的内部用户，不得上传公开仓库或公共网盘。

构建命令：

```bash
PYTHONPATH=src python -m fund_holdings_agent.distribution --output-dir dist
PYTHONPATH=src python -m fund_holdings_agent.distribution --output-dir dist --include-internal-data
```

每个 ZIP 都包含 `PACKAGE_INFO.txt` 和带SHA-256的 `PACKAGE_MANIFEST.json`，且不会打包 `.venv`、缓存、历史报告、日志、测试产物或本机配置。

用户配置和运行数据默认保存在：

```text
~/Library/Application Support/FundHoldingsAgent/
├── config.json
├── portfolio/
├── state/
└── logs/
```

正式Excel和PDF默认保存在：

```text
~/Documents/FundHoldingsAgent/
```

测试、CI或受控部署可使用 `FUND_AGENT_APP_HOME`、`FUND_AGENT_REPORT_ROOT`、`FUND_AGENT_PROJECT_ROOT` 覆盖路径，不修改系统的 `HOME`。

## 4. 使用

双击 `基金持仓Agent.command` 可进入中文菜单。完整CLI命令如下：

菜单第一项为“生成最近三季度持仓报告（可选Excel或分析PDF，推荐）”。用户选择基金公司、基金经理和截止报告期后，可继续选择：Excel持仓简报、PDF分析报告（含持仓比例、行业分布和季度新增/退出）或两者都要。程序自动计算连续三个自然季度；已有季度结果直接复用，只对缺失、等待或失败季度调用原确定性管道，三个季度均可用后才生成正式报告。完成后自动打开Excel/PDF结果目录。

“生成单季度完整分析”保留原完整管道；“运行全部25位基金经理（单季度）”需要二次输入 `RUN` 确认。运行期间会显示当前经理、总人数和基金池、持仓、行业、资源、历史库等阶段进度。网络短暂失败会显示为“正在自动重试”，无需在任务运行中输入菜单数字；如需停止使用 `Control+C`。

```bash
.venv/bin/fund-agent doctor
.venv/bin/fund-agent doctor --check-network
.venv/bin/fund-agent brief --manager 徐小勇 --end-report-date 2026-06-30 --output-format both
.venv/bin/fund-agent brief --company 长安 --end-report-date 2026-06-30
.venv/bin/fund-agent run --report-date 2026-06-30
.venv/bin/fund-agent run --company 长安 --report-date 2026-06-30
.venv/bin/fund-agent run --manager 徐小勇 --report-date 2026-06-30
.venv/bin/fund-agent retry --manager 徐小勇 --report-date 2026-06-30
.venv/bin/fund-agent status
.venv/bin/fund-agent results
.venv/bin/fund-agent open-results
```

`brief` 是日常默认入口，`--output-format` 可选 `excel`、`pdf` 或 `both`。Excel是每位经理一份两张工作表的持仓简报；PDF是每位经理一份分析报告。PDF中跨产品的持仓市值与占净值比例是各基础产品披露值的算术汇总，只用于观察共同持仓和变化方向，不代表统一组合的加权配置比例。补跑某季度遇到披露等待时，任务以退出码 `2` 停止，不会用旧季度或不完整数据生成正式报告。`run` 默认跳过逐经理Excel，但保留公司正式Excel，从而减少重复报告。`--data-only` 会进一步跳过公司Excel，只生成JSON、异常、缓存和历史库；该选项不能作为正式业务交付。

`doctor` 默认不联网。增加 `--check-network` 后才真实访问公开网站。

## 5. GitHub 分发建议

第一版采用私有仓库和固定版本标签：

1. 代码与业务数据分离；
2. 每次交付使用明确版本号和变更说明；
3. 先在没有既有Python虚拟环境、Node依赖和Codex运行时的干净Mac上测试；
4. 使用少量基金验证网络、断点续跑和正式Excel；
5. 再由1—2位内部用户试用；
6. 暂不提供自动 `git pull`，避免代码升级与数据库迁移不同步。

## 6. 完成标准

Mac CLI 跨电脑版本只有在以下条件全部满足时才可正式交付：

- 干净Mac能完成安装和初始化；
- `fund-agent doctor --check-network` 没有 `FAIL`；
- 无需 Codex 本机缓存或外部符号链接即可生成Excel和PDF；
- 两个测试经理能够完成真实抓取、缓存、续跑、校验和导出；
- 升级程序不会删除用户历史库和报告；
- 内部人员库没有进入公开仓库；
- 卸载和故障取证步骤已文档化。

## 7. 给接收者的最短说明

```text
1. 解压收到的ZIP，并保留整个文件夹。
2. 确认Mac已安装Python 3.11或更高版本。
3. 首次使用：右键 install.command，选择“打开”。
4. 安装完成后：双击 基金持仓Agent.command。
5. 选择基金公司、基金经理、报告期，再选择Excel、PDF或两者都要。
6. 结果保存在“文稿/FundHoldingsAgent”目录。
```
