# AutoInfo 落地 Graph Engineering 实施方案（修正版，对齐 backup repo 现状）

**日期**：2026-08-30（修正版，在 2026-08-29 v2 基础上修正）｜ **作者**：default profile ｜ **读者**：code profile / coding agent
**代码基座**：`renanzai40/AutoInfo_BackUp@main`（backup/main 现为 `7003c93`；本文全部路径以 backup 为准，实测核对）
**背景**：Graph Engineering 三视图（Task Org / Agent Coord / Runtime State）在 AutoInfo 的落点 = **把已存在的 KB 关系图 + 血缘/溯源雏形，升格为覆盖"采集→Gate→KB→产物"的运行时状态图与数据血缘图**。

---

## 背景：Graph Engineering 是什么 + 本项目现状 + 差距

### Graph Engineering 是什么（30 秒）
> 继 Prompt → Context → Harness → Loop 之后的**下一代 Agent 工程范式**（来源 arXiv:2608.21156 奠基综述）。核心 = 把单 Agent 无法承担的复杂任务，**用显式的"图"来组织三件事**：
> - **Task Organization（任务组织）**：复杂目标 → 子任务图（依赖/顺序/并行/验证）
> - **Agent Coordination（Agent 协调）**：任务 → 异构 Agent 的团队/委派/通信
> - **Runtime State Management（运行时状态管理）**：进度/来源/故障可追踪、可定位、可恢复
>
> 一句话：**把隐藏在上下文和控制逻辑里的关系，外显为可操作的图**，获得单 Agent 做不到的"系统智能"。

### AutoInfo 项目现状（已实测 backup，2026-08-30，修正版）
AutoInfo 是**信息入口平台**：一串长周期管线 `多源采集 → G0-G5 质控门（G0 为入库前硬门；G1 含 ToS 合规检查）→ KB 三层入库 → 8+ 类产物生成 → 打包交付`，**21 个域**（修正：上一版作 22，实测 config 为 21）、多源/多层/长周期。
它**已经埋了 Graph Engineering 的种子**（非零起点，全部实测确认）：
- ✅ KB **关系图已存在**（`kb-graph.yaml` / `link_items` / relations 表 / `knowledge_graph_export`）
- ✅ **血缘/溯源雏形已存在**（`promotion.py` / `promotion-provenance.yaml` / `test_provenance.py`）
- ✅ **故障注入可复用**（`fault_inject.py` / `fault-injection.yaml`）
- ✅ 上次 P0（`default_language` 失效致 ai 域污染）**已修复进 backup**，回归场景 `regression-domain-language-default.yaml` 已入库

### ⚠️ 首次补充：AutoInfo 当下的真实瓶颈是「产物质量缺陷」，不是「组织范式」（2026-08-30 外部复审）
按用户既定铁律「issue→PR→opencode debug loop 优先，直到 demo package 所有产物质量达标」，AutoInfo **当下的头号任务是修复产物质量缺陷**，Graph Engineering 组织升级应排其后。已确认缺陷（均已提 issue 追踪）：
- **digest 内部字段裸露/泄漏** —— 相关修复已生效（R2 宽版泄漏 0）
- **tutorial 产物空壳 + H1 误标** `# Weekly Digest` —— 根因 `_PRODUCT_H1_WORDS` 漏 `"tutorial"`（修复中）
- **presentation 假源 / 空模板** —— 部分生成仅空模板
- **financial-intelligence 域数据全员 stale** —— 需重新采集，非代码缺陷
这些是**模板/LLM 层问题，Graph 组织能力解决不了**，须先按 debug loop 修完，再谈图化。

### 距离 Graph Engineering 的差距（缺什么）
| 维度 | 现状 | 差距 |
|---|---|---|
| **Task Organization** | 管线顺序明确（collect→Gates→KB→output）| Gate 依赖/并行未显式化成图 |
| **Agent Coordination** | 多域/多产物模块存在 | Agent/域/产物的能力边界为隐式 |
| **Runtime State** | KB 关系图只管条目关联；溯源是扁平 manifest | **"config 何时生效 / Gate 通过与否"未接进图**——历史 config 静默失效曾靠人肉排查 |
| **System Evolution** | 无 | 高阶目标，本次不做 |

> **最核心差距**：AutoInfo 已有"知识图谱 + 溯源雏形"，但**没有把"运行状态（config 快照、Gate 结果）"接进图**。落地 = 让 config 失效/数据污染这类问题，从"人肉 read_file 逐层查"变成"图上一个可见断裂"。

---

## 0. 重要前提（先澄清，避免空谈）

> **AutoInfo_BackUp 已有 Graph Engineering 的真实基础**（全部实测确认）：
> - ✅ `src/autoinfo/data/domains/ai-commercial/sources.yaml` **已有 `default_language: en` + exclude_keywords**——上次 P0（default_language 未同步→语言过滤失效）**代码已修复进 backup**；但**实测库中 ai-commercial 仍混有中文财经噪声标题**（生猪价格、A股涨跌等），说明过滤未完全拦净，仍是隐患
> - ✅ `src/autoinfo/mcp/scenarios/kb-graph.yaml` + `tests/kb/test_knowledge_graph.py` + `test_knowledge_graph_export.py`——**KB 关系图已存在**（create_kb_entry/link_items/query_knowledge_graph）
> - ✅ `src/autoinfo/promotion.py` + `promotion-provenance.yaml` + `tests/output/test_provenance.py`——**血缘/溯源已有雏形**
> - ✅ `src/autoinfo/output/fault_inject.py` + `mcp/scenarios/fault-injection.yaml`——**故障注入基础设施已存在**（可复用做验证）
> - ✅ `mcp/scenarios/regression/regression-domain-language-default.yaml`——上次 P0 的**验证场景已入库**
> - ✅ `mcp/scenarios/data-lifecycle-e2e.yaml`——**数据生命周期 E2E 场景已存在**
>
> **所以本方案不是"从零建图"，而是在已有 kb-graph/promotion_provenance/data-lifecycle 之上，做两件事的精准补强**：①把"血缘/来源"从 manifest 升级为图化；②把"config 快照 + Gate 结果"作为运行状态接进图，让"配置静默失效"这类问题变成图上可见的断裂。
> **但必须在调试完当前产物质量缺陷（digest/tutorial/presentation/financial stale）之后，再实施本方案。优先级：质量闭环 > 图化升级。**

---

## 1. 现状盘点（已核实）

| 组件（backup 真实路径）| 现状 | 对应 Graph Engineering |
|---|---|---|
| `mcp/scenarios/kb-graph.yaml` + `tests/kb/test_knowledge_graph*.py` | KB 条目关系图（link_items/relations table）| **知识图谱种子**（只服务条目关联，未接管线）|
| `promotion.py` + `promotion-provenance.yaml` + `test_provenance.py` | 产物来源/溯源（promote 场景）| **血缘/溯源雏形** |
| `output/fault_inject.py` + `fault-injection.yaml` | 故障注入 | **可复用的验证基础设施** |
| `data/domains/<dom>/sources.yaml` | `default_language`/`exclude_keywords`（代码已修复，数据仍有残留）| 过滤规则（config）|
| `mcp/scenarios/regression/regression-domain-language-default.yaml` | 语言默认回归场景 | 上次 P0 的验收锚点 |
| `mcp/scenarios/data-lifecycle-e2e.yaml` | 数据全生命周期 E2E | 管线的验证场景 |
| `output/__init__.py`（digest/report/... 8类 + video/ebook/localize/seo/fault_inject）| 产物生成 | Task 输出节点 |
| `mcp/scenarios/regression/regression-crossdomain-noise-filter.yaml` + `regression-18-ai-commercial-english-drift.yaml` | 跨域/英文漂移回归 | 数据污染类问题的验收锚点 |

**结论**：AutoInfo 在"知识图 + 溯源"上有约 60% 基础，但**"运行状态（config 何时生效 / Gate 通过与否）未接进图"**是结构性缺口。但**它当前最紧的不是图化，而是把产物质量问题（digest 泄漏 / tutorial 空壳 / presentation 假源 / financial stale）修完**——这些是用户既定 debug loop 的最高优先。

---

## 2. 落地方案（3 步，全部接进现有文件；顺序：先 P0 质量闭环，再 P1-P2 图化）

### P0（当务之急，非图化）：完成产物质量 debug loop（用户既定最高优先）
按「issue→PR→opencode debug loop」把当前所有产物缺陷修复直至 demo package 全达标：
- digest 内部字段裸露/泄漏（相关修复已生效，待回归确认）
- tutorial 空壳 + H1 误标 `# Weekly Digest`（根因 `_PRODUCT_H1_WORDS` 漏 `tutorial`）
- presentation 假源 / 空模板
- financial-intelligence 域数据全员 stale（需重新采集）
**验收**：验收脚本扫描全部 deliverable，21 域×8 类 = 168 产物零空壳、零 Placeholder、Tutorial H1 语义正确、manifest 一致、relevance 非空。**先把这批跑完，再实施下方 P1-P2 图化。**

---

### P1（图化，质量闭环后）：把"config 快照 + Gate 结果"作为运行状态接进图（Runtime State）

**目标**：让"某条 raw 进产物时用了什么 config、过了哪些 Gate"在图里可见，配置静默失效→图上可见断裂。

**改动**：
1. KB relations 表**已存在** `relation_type`（默认值 `'related'`）与 `metadata`（JSON）两列（`kb.py` 建表语句，行 547-557），**无需新增列**；只需：①把 `relation_type` 枚举从单一 `related` 扩展为 `{from_source, passed_gate, produced_product, applied_config}`；②把 config 快照 / Gate 结果写入既有 `metadata` 列。现有 `link_items` 底层即 relations 表，扩展枚举不破坏 self-contained 契约。
2. 在 **process 入库 / output 生成**时，把每条 raw→product 的边记上 **config 快照哈希（P1 新增字段，当前 repo 无此概念，见下方改动文件）+ Gate 结果 + 时间戳**，写入 relations 行的 `metadata`（复用 `data/domains/*/sources.yaml` 版本 + `promotion.py` 的溯源逻辑）。
3. 提供诊断：在既有 `autoinfo knowledge graph` 命令组下新增子命令 `autoinfo knowledge graph diag <product>`（注：现有 CLI 组名是 `knowledge graph`，无顶层 `graph` 组）→ 反查血缘，标出"这条产物用了哪个 config 版本、config 与 sources.yaml 是否一致、哪条 raw 的过滤边缺 applied_config"——让"语言过滤没生效"类问题变成图上可见，而非人肉 read_file。

**改动文件**：`kb.py`（仅扩展 `relation_type` 枚举 + 写 `metadata`，无 DDL）、`promotion.py`（复用溯源逻辑）、process/output（写 config 快照哈希边至 `metadata`）、`cli/knowledge.py`（在 `knowledge graph` 组下新增 `diag` 子命令）
**验收**：复用 `fault_inject.py` + 真实场景，造一次"config 版本与 sources.yaml 不一致"→ `graph diag` 能自动标出该 config 边冲突。**真实验证，非 mock。**

---

### P2（图化，质量闭环后）：把"数据污染"类问题固化为图上的回归（System State）

**目标**：历史上"ai 域财经噪声/中英混杂"这类问题靠人肉逐层查 → 固化成"灌入一条噪声条目 → 图自动标出它污染了哪些产物"。

**改动**：
1. 复用 `regression-crossdomain-noise-filter.yaml` / `regression-18-ai-commercial-english-drift.yaml`，**在其基础上加"血缘断言"**：灌入噪声条目 → 断言图里该条目被 exclude_keywords 过滤边切断、未进产物。
2. `graph diag` 支持按"污染源"反查：给一个 entry_id → 标出它（本应被过滤却）进入了哪些 product。

**改动文件**：`regression-crossdomain-noise-filter.yaml`（加血缘断言）、`cli/knowledge.py` 的 `knowledge graph diag`（污染反查，复用 P1 子命令）
**验收**：跑回归场景，等价于"自动复现上次 ai 域噪声审查"，断言图上切断成立。**这直接把你上次手动通查的步骤图化、固化、可回归。**

---

### P3（图化，质量闭环后）：产物血缘图导出（DataLineage → 付费信任卖点）

**目标**：把扁平的 manifest（raw 文件名列表）升级为**图结构血缘**，支撑"每条结论可溯到源"的付费定位。

**改动**：
1. 产物生成时额外产出 `lineage.json`（图格式）：`product → 引用哪些 KB entry → 各 entry 来自哪个 source_url → 经过哪些 Gate 验证 → freshness/有效期`。
2. 复用 `knowledge_graph_export` 能力，把血缘图做成**可导出、可对用户展示**的格式。
3. 与现有 manifest 兼容：manifest 保留为交付清单；lineage 是图化升级。

**改动文件**：`output/__init__.py`（生成 lineage.json）、复用 `knowledge_graph_export`
**验收**：对一个 demo product，`lineage.json` 能回答"这条结论引用几条 KB → 各来自哪个源 → 经过哪些 Gate → freshness"，**支撑 AutoInfo 信息信任定位**。

---

## 3. 明确不做（边界）

| ❌ 不做 | 原因 |
|---|---|
| 不引入外部图数据库 | 复用现有 SQLite relations + 新 lineage.json，dict/图导出足够 |
| 不改 collect/过滤/入库的语义 | 只改"怎么记录状态/血缘"，不改"收集什么/怎么过滤"（产品级规则不动）|
| 不做自演化图系统 | 高阶目标，先做状态可记录、可定位 |
| 不改坏 kb-graph 验证场景 | 其自带 self-contained/self-cleaning 契约，扩展 type 维度不破坏 |
| 不回填历史数据 | 新图从下次产出开始记录 |

---

## 4. 一句产品价值

1. **当下最紧**：P0 把 demo package 产物质量修到达标（digest 泄漏 0 / tutorial 无空壳 / presentation 非假源 / financial 重新采集）——这是用户既定 debug loop 铁律、也是对外交付的第一前提。
2. **信任卖点强化**：P3 血缘图 = "每条结论可溯到源"的可视化证据，支撑 AutoInfo 信息入口平台的信任定位（核心付费价值）。
3. **验证固化**：P2 把过去手动的产物通查步骤，固化成可回归的血缘断言。

---

*本方案所有路径均已实测核对 `renanzai40/AutoInfo_BackUp@main`（commit `7003c93`）。实施前对照 `autoinfo-delivery-validation` skill（validate matrix 双层 + 付费 6 维验收框架）。*
*修正记录（2026-08-30）：① 域数 22→21（实测 config）；② 删去"上次 P0 已修复进 backup、问题根治"的绝对化表述，改为"代码已修复，但实测库中 ai-commercial 仍混中文财经噪声，未完全拦净"；③ 新增「当前最紧瓶颈是产物质量缺陷」章节，把 digest 泄漏/tutorial 空壳/presentation 假源/financial stale 列为 P0 当务之急，图化方案整体后移（P1-P3）；④ backup/main 版本钉死 `7003c93`；⑤ 据实测复核更正：质控门命名为 G0-G5（G0 入库前硬门、G1 含 ToS 合规），非"G1-G5"；relations 表已含 `relation_type`/`metadata` 列，P1 仅扩展枚举、免 DDL；诊断 CLI 落点为既有 `knowledge graph` 组下的 `diag` 子命令（无顶层 `graph` 组）；P0 验收口径由 18 域更正为 21 域（×8 类 = 168）。*
