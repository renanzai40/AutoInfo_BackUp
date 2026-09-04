# AutoInfo 后续开发报告（开发视角）

> **日期**：2026-09-02 · **基于**：商业论证报告（autoinfo-business-validation-20260902.md）
> **定位**：聚焦开发的路线图——现有 feature 补强 + 新 feature 加入，每项含优先级/任务/验收标准
> **原则**：只列"启动阶段验证付费意愿"所需的最小开发集，不堆功能（商业结论：质量门控是护城河）

---

## 现状锚定（开发基线）

| 项 | 现状 | 位置 |
|:---|:-----|:-----|
| 代码规模 | [已修正 2026-09-04] 665 commits / 247 测试文件（665 = git rev-list --count HEAD @ 2026-09-04 基线实测） | `git log` / `tests/` |
| Validation 场景 | 130（65 功能 + 65 回归）[已修正 2026-09-04]（verified-correct, keep：截至 2026-09-04 实测 130 = 65 功能 + 65 回归——README/AGENTS 的旧计数是过时方，已由单独任务修正为 130，本行保持 130 不动）| `src/autoinfo/mcp/scenarios/` |
| MCP 工具 | 146 / 35 类别 | README |
| 采集器 | 30 handlers / 21 内置域 | README |
| Demo 包 | R5(1) 通过独立审查，437 文件 4 域 24 产物[已修正 2026-09-04：该文件在本仓库与 $HOME 均不存在，deliverables/ 目录亦不存在；最近似真实交付物为 outputs/autoinfo-deliverable-13domains-20260810.zip；且 R5 独立审查报告未归档（demo-release-standard.md:12 仅为自查勾选行），R5 通过非已验证事实] | `deliverables/`[已修正 2026-09-04：该目录不存在，路径无效] |
| 交付脚本 | `scripts/validation_delivery.py` / `coverage_matrix.py` / `coverage_audit.py` | `scripts/` |

---

## 一、现有 feature 补强

### P0-1：质量门控可视化（把"看不见的门控"变成"交付物"）
> **依据**：商业结论——质量门控（[已修正 2026-09-04] L0 gate F1-F4/C1-C6/X1 + G0-G5 + D1-D3）是唯一不可复制的护城河，但当前只存在于内部流程，用户感知不到。

**任务**：在 `scripts/validation_delivery.py` 的交付包中，新增 `01-QA-GATES/` 目录（[已修正 2026-09-04] 现状注记：当前 `scripts/validation_delivery.py` 交付包仅含 01-RAW/02-PROCESSED/03-KB/04-MATRIX/06-REJECTED + validation-report.md + manifest.json，`01-QA-GATES` 全仓零引用——本任务为全新建而非补强），每次生成 PROCESSED 产物时输出一份 **gate 通过报告**：
- 每份产物列出：过了哪些门控（G0-G5/D1-D3）、每道门控的判定、被拦掉的候选条目及原因
- 格式：`gate-report-<product>.md`（人读）+ `gate-report-<product>.json`（agent 读）

**验收标准**：
- [ ] demo 包包含 `01-QA-GATES/`，每个 processed 产物有对应 gate 报告
- [ ] [已修正 2026-09-04] 被拒产物（manifest.json 的 `rejected` 键 + `06-REJECTED/` 目录）与 gate 报告 rejected 列表一致（可追溯；rejected 是 manifest.json 内的列表键而非独立文件，`_rejected/` 并非交付包路径——process 层失败目录为 `collections/<domain>/_failed/`）
- [ ] 跑 `python scripts/validation_delivery.py` 能生成完整包

### P0-2：溯源清单默认化
> **依据**：market-positioning §7.2——客户 A/B 都关切"来源可溯"；对标 AlphaSense traceability。

**任务**：PROCESSED 产物（digest/report/tutorial）默认带 **Sources 清单区块**：
- 每条结论/关键句 → 对应 `source_url`（demo 已实现，需变为默认模板而非示例）
- [已修正 2026-09-04] 逐模板精确矩阵（替代笼统的"8 个全部加上（现在是部分有）"）：report(md/html)/premium-briefing/enterprise-briefing 已有完整 References；column 缺 References 区块（bug，另任务修）；magazine-digest/tutorial 需新增 Sources；digest(presentation) 行内已有 cite（digest 另补聚合尾区块，presentation 保持行内）

**验收标准**：
- [ ] 8 个 product template（digest/report/tutorial/presentation/premium-briefing/column/magazine-digest/enterprise-briefing）默认含 Sources 区块
- [ ] 抽查 3 个产物：每条关键论断都能回溯到 raw 条目 URL

### P1-1：Validation 场景公开展示
> **依据**：130 场景 = 工程证据，是对 B2B 买家（CIO/合规敏感）的最强信任状。

**任务**：`list_validation_scenarios` MCP 工具输出升级——返回每个场景的 `description + requires_env + regression 标记`，且 CLI 加 `autoinfo validation list --summary`（按域/类别分组统计）。

**验收标准**：
- [ ] MCP `list_validation_scenarios` 返回结构化场景清单（name/category/regression/env）
- [ ] CLI `autoinfo validation list --summary` 输出分组统计（功能 65 / 回归 65）[已修正 2026-09-04] 命令动词决策注记——新增 `autoinfo validation` CLI 组（区别于现有 `autoinfo validate`——后者是 matrix/diff/stability 执行器，身份不同）；验收分组计数须实时推导不硬编码

### P1-2：免费层转化设计
> **依据**：ChartMogul 2026——AI 原生产品 free-to-paid 6-8% good / 15-20% great；免费层是转化管道。

**任务**：确认 Free 层限制可配置且默认合理：
- Free = 1 域 + 1 产品（digest）+ 每周 + 无自定义
- `subscription` tier 配置里加 free 层默认值（当前"prices are placeholders"）[已修正 2026-09-04] 现状精确化——Free 定义需 schema 扩展（Subscription 加 max_products/max_frequency/allow_custom 列）+ config 默认（1 域/1 产品/weekly/无自定义）；定价确为硬编码占位：storefront `_PRODUCT_PRICING` raw=free/$0、processed=premium/$29（src/autoinfo/api/storefront.py:55-68）

**验收标准**：
- [ ] `autoinfo billing` CLI 能创建 free 订阅并正确 gate（超过限制被挡）[已修正 2026-09-04] 现状注记：当前 `autoinfo billing` 仅有只读 summary 命令，无 create——需新增 create-free 子命令，是本任务的真实增量
- [ ] [已修正 2026-09-04] 产品生成/排程路径对 free 层超限返回明确错误 (FREE_TIER_LIMIT)；`check_access` 保持布尔 gate（不是静默——限额执行不塞进布尔 fast path，错误码在生成/调度层抛出）

---

## 二、新 feature 加入

### N1：Concierge MVP 模式（启动阶段验证付费意愿的核心工具）
> **依据**：商业结论——唯一能产生"真金白银信号"的动作是 3-5 个 Concierge MVP。

**任务**：新增 `autoinfo mvp` CLI 子命令，一条命令包办"试点用户开通"：
```
autoinfo mvp init --user <id> --domain <domain> --product <digest|report|premium-briefing> --frequency <daily|weekly>
```
- 自动：创建 EndUserProfile + subscription（premium 试用）+ 配置 domain + 生成首份产物
- 自动：生成 `mvp/` 交付目录（产物 + gate 报告 + 溯源 + 用户联系方式占位）[已修正 2026-09-04] 约束注记：`mvp/` 为运行时产物目录，须加入 .gitignore（同 collections//outputs/ 纪律）且 AGENTS.md runtime-artifacts 表加行；含终端用户联系方式/PII，禁止提交仓库

**验收标准**：
- [ ] 3 条命令以内从 0 开通一个试点用户并收到首份产物
- [ ] 产物包包含 gate 报告 + 溯源（P0-1/P0-2 产出）
- [ ] 有 `autoinfo mvp list` 查看所有试点用户状态

### N2：MCP 优先模式（防守"DIY agent"进攻）
> **依据**：商业结论——打不过就加入，成为 agent 生态基础设施。

**任务**：新增 `autoinfo serve --agent` 启动一个**只读 MCP server**（面向外部 agent 消费 AutoInfo 数据，不开 CLI/API 权限）：
- 暴露工具：`search_knowledge_base`（只读）、`get_kb_entry`、`export_kb(format=agent)`、`list_validation_scenarios` [已修正 2026-09-04] 边界注记：只读双闸——list_tools 白名单 + call_tool 对白名单外工具返回显式错误（非静默）；明确排除 `run_validation_scenario`（其步骤含真实写操作副作用，与"只读"承诺冲突）；transport=stdio（AGENTS.md 明示 SSE 是 future，不实现 HTTP/auth）
- 目的：让 Claude Code/OpenCode/Codex 能直接调 AutoInfo 的知识库，成为 agent 的内容供给层

**验收标准**：
- [ ] `autoinfo serve --agent` 启动后，外部 agent 能通过 MCP 搜索 KB 并拿到 JSON-LD 结构化结果
- [ ] 只读（无 collect/process/generate 写操作暴露）

### N3：垂直域打穿工具包（医学 + 金融 2 域优先）
> **依据**：market-positioning §6.2——medical/financial 是最高 WTP 域。

**任务**：为 2 个旗舰域补齐"开箱即用"体验：
- `autoinfo domain init medical-research --seed`：一条命令创建域 + 预置 sources + 默认 topic 集 + 默认 extraction schema [已修正 2026-09-04] 现状精确化：medical-research 实际 7 源（PubMed/Semantic Scholar/arXiv/CrossRef/DBLP/OpenAlex/USPTO）+ 6 topics 已在盘上（原括注 3 源低估现状）——真实增量 = 缺 extract_fields 默认值 + `--seed` 封装（现仅 `domain import --from-demo`），预置源集无需重写
- 同上 `financial-intelligence --seed` [已修正 2026-09-04] 现状精确化：financial-intelligence 实际 11 源（Alpha Vantage/FRED/Finnhub/SEC EDGAR/Twelve Data/World Bank/Quandl/CNBC/TheStreet/MarketWatch/WSJ）+ 5 topics——**该域现无雅虎财经源，原括注（SEC EDGAR/雅虎财经/Quandl）与盘上配置不符**；真实增量 = 缺 extract_fields 默认值 + `--seed` 封装

**验收标准**：
- [ ] `--seed` 后 5 分钟内跑通 collect → process → 产物（无手工配置）
- [ ] 2 个域的 seed 配置在干净环境可复现（非手写路径）

---

## 三、明确不做（启动阶段，避免功能过载）

| 不做 | 原因 | 依据 |
|:-----|:-----|:-----|
| 新采集器 | 30 个已够，缺的不是源是付费用户 | 商业结论 |
| 新输出格式 | 8 格式已过载，买家要"解决痛点"非"全格式" | 商业结论 |
| 中文域打穿 | 海外先验证（市场定位）| market-positioning §7.6 |
| 多语言 UI | 非启动阶段核心 | — |

---

## 四、开发顺序与周期估算

```
P0-1 门控可视化 ──┐
P0-2 溯源默认   ──┼── 第 1 周（构建"质量可感知"基线）
                 │
P1-1 场景展示   ──┤
P1-2 免费层     ──┼── 第 2 周
                 │
N1 Concierge MVP ─┼── 第 3 周（核心：验证付费意愿）
N2 MCP 优先     ──┤
N3 垂直打穿     ──┴── 第 4 周（为 MVP 试点服务）
```

**验收里程碑**：第 4 周末，能用 `autoinfo mvp init` 开通 3-5 个试点用户并交付"含 gate 报告 + 溯源"的 PROCESSED 产物。
