<!-- doc-type: best-practice-review -->

# AutoInfo 业界最佳实践复盘(独立维度)

> **Independent review dimension.** 本维度独立于以项目预期/验收为视角的 `acceptance-framework.md`(AC1-AC9)。它以**业界最佳实践**为标尺审查 AutoInfo 系统——哪些地方做得好、哪些做得不好、哪些需要重构、哪些需要提升。判据来自外部权威来源(Anthropic / OpenAI / MCP spec / Google / IEEE/ACM 实证研究等),不是项目自身承诺。
>
> **Status:** Baseline 2026-08-14(director request)。定期复跑(见 §9)。
>
> **Relationship to other docs:**
> - `docs/dev/acceptance-framework.md`(AC1-AC9)— **预期驱动**验收:判据是项目自我定义的标准。**本维度**是**事实驱动**复盘:判据是业界最佳实践。二者互补、互不取代;AC8/AC9 引用的"industry best practice"是内部工程组织原则,本维度是首次把最佳实践作为**系统价值标尺**。
> - `docs/dev/validation-scenario-contract.md` — agent-as-tester 机制层,本维度对其审查(维度 3)。
> - `docs/dev/七阶段AI开发流程-用CodingAgent交付成品的方法论.md` + `.opencode/skills/deep-modules-skill` — 本地代码质量视角的载体,本维度审查其对业界实践的对齐度(维度 1)。
> - `docs/dev/specs/user-lifecycle-definition.md` / `docs/dev/specs/mcp-tools.md` — agent-first 设计的规格载体,本维度审查其对业界 agent 工具设计的对齐度(维度 2)。

> **Change process:** 本维度是盘点文档(baseline + 复跑),不是验收判据。差距项进入工程 backlog 由 feature wave 处理;本文档本身的修订(维度定义、判据、来源替换)建议经 director-user 确认。

---

## Table of Contents

1. [§0 目的、原则与判据来源](#0-目的原则与判据来源)
2. [§1 三维度框架](#1-三维度框架)
3. [§2 维度 1:基础代码最佳实践](#2-维度-1基础代码最佳实践)
4. [§3 维度 2:面向 Agent 项目最佳实践](#3-维度-2面向-agent-项目最佳实践)
5. [§4 维度 3:Validation 与 agent-as-tester 最佳实践](#4-维度-3validation-与-agent-as-tester-最佳实践)
6. [§5 差距分级清单](#5-差距分级清单)
7. [§6 基线盘点结论(做得好 / 差 / 需重构 / 需提升)](#6-基线盘点结论做得好--差--需重构--需提升)
8. [§7 教训与对策](#7-教训与对策)
9. [§8 复跑节奏协议](#8-复跑节奏协议)
10. [§9 证据与来源索引](#9-证据与来源索引)

---

## §0 目的、原则与判据来源

### 为什么需要这个维度

AGENTS.md 与验收框架已确认:AutoInfo 的 direct user 是 **Agent**(agent-first 设计);end user(B1)是人类消费者。项目已有成熟的**预期驱动验收**(AC1-AC9,覆盖范围由付费意愿研究锚定)。但:

1. "业界最佳实践"在验收体系中只在两处被引用(AC8 文档健康、AC9 测试金字塔),且都是**内部工程组织原则**;
2. 没有任何维度回答"AutoInfo 与业界同类平台相比质量处于什么水平"——`market-positioning.md` 虽含竞品 landscape,但被显式标注 "not operational",不参与验收判据;
3. 项目大量创新设计(agent-as-tester validation、146 工具 MCP、unified error envelope)需要外部标尺来确认"这是否是业界前沿,还是孤例";

→ 本维度填补该结构性空位。

### 判据来源(外部权威)

| 来源类型 | 代表 |
|---------|------|
| Agent 架构 | Anthropic "Building Effective Agents"/"Writing effective tools for agents"/"Effective context engineering";MCP spec(2025-06-18 & 2026-07-28 RC);OpenAI "A practical guide to building agents" |
| 代码质量 | Ousterhout《A Philosophy of Software Design》;Google eng-practices;PEP 8;Meta Typed Python Survey;IEEE/ACM 实证(Shepperd 1988、TSE 2005/2009、tertiary study 2023、USENIX 2025) |
| Validation | Google Testing Blog;Martin Fowler;Anthropic "Demystifying evals";OpenAI evals;τ-bench;AutoCover(ICSE 2026);SpecOps;TestExplora;LLM-as-judge 偏见研究(2025-2026) |

### 证据强度分级(本维度所有对照项统一使用)

| 符号 | 含义 | 使用规则 |
|------|------|---------|
| 🔬 实证 | 有 peer-reviewed 研究 / 大规模数据支持 | 可作差距论证的硬依据;可用于门禁决策 |
| 📐 惯例 | 权威经验总结(Google/Anthropic/MCP spec),无严格对照实验 | 可作差距论证的软依据;作改进方向,不作门禁 |
| ⚖️ 争议 | 权威间明确分歧(如 Ousterhout vs Clean Code) | 只作设计权衡提示,不作差距判据 |

对照结论统一三态:**✅ 已满足 / 🟡 部分 / ❌ 差距**。

---

## §1 三维度框架

| 维度 | 标尺回答的问题 | 本地对应载体 |
|------|--------------|-------------|
| **D1 基础代码最佳实践** | 代码写得好不好:模块设计、错误处理、命名、度量、AI 代码审查 | `deep-modules-skill`、方法论 §3.1、AC8/AC9、ruff+mypy |
| **D2 面向 Agent 项目最佳实践** | 系统对 direct user(Agent)友好吗:工具设计、错误信封、长任务语义、可观测性 | `user-lifecycle-definition`、`mcp-tools`、ADR-0005、`mcp-usage-examples` |
| **D3 Validation 与 agent-as-tester** | 验证体系本身符合业界吗:LLM-judge 校准、scenario 设计、agent-as-tester 先例、CI 质量门 | `acceptance-framework`、`validation-scenario-contract`、117 场景、2 次运行报告 |

---

## §2 维度 1:基础代码最佳实践

> 本地现状基线:唯一成文的代码质量 doctrine 是 **Ousterhout 深模块**(方法论 §3.1 + deep-modules-skill v1.1.0,含 7 步程序、watch-list、4 守卫)。风格由 ruff + mypy(strict)工具门强制,无 prose 编码规范文档。阶段 7 Review 是流程改进导向,无代码侧评审环节。plans 归档表为空(`*(none yet)*`)。

### D1-1 深模块(小接口大实现) 📐

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| 深模块 = 接口远简单于实现;浅模块("scattered, coupled, thin")是病态 | Ousterhout《APOSD》;APOSD-vs-Clean-Code 辩论 | 已有完整 doctrine + 实操 skill;范例 kb.py/llm.py/quality.py/delivery.py/promotion.py;watch-list cli/collectors/output | ✅ 已满足(此条是本地强项) |
| 向下压复杂度:让错误不可能发生优于到处 catch | Ousterhout《APOSD》 | `process_collection` 无缓存返回 `{status:"noop"}` 而非报错 — 正面实例 | ✅ 已满足 |
| 信息隐藏与信息泄漏(change amplification) | Parnas 1972;Ousterhout | `VALID_SOURCE_TYPES` frozenset 单一事实源 ✅;但 collectors/ 30 handler、output/ 多格式是否共享同份知识则**未验证** | 🟡 部分(需扫描重复知识) |

### D1-2 可维护性度量:证据 vs 教条 🔬

| 业界主张 | 来源(证据强度) | AutoInfo 对照 | 结论 |
|---------|--------------|--------------|------|
| LOC/耦合/复杂度与可维护性有一致正面关联;继承/内聚指标证据不一致 | tertiary study 2023(Information & Software Technology) | 无系统度量程序;无模块健康报告 | ❌ 差距(可选改进:规模>耦合>复杂度优先级) |
| 圈复杂度阈值无科学依据(是 LOC 代理,被 LOC 击败);类大小会混杂一切 OO 度量 | Shepperd 1988;Zhou et al. TSE 2009 | 未设 CC 阈值门禁 — 避免了一个反模式 | ✅ 已满足(刻意不为) |
| 耦合×内聚必须联合评估,不能单指标设阈值 | TSE 2005 受控实验 | 无指标程序,不适用 | — 不适用 |

> 度量教训:若未来引入 metric 门禁,必须是"发现审查对象的探针"而非"自动阻断的裁决";阈值全部是惯例数字。

### D1-3 错误处理 📐

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| 永不静默失败;尽早抛错;不吞根因 | Google tech-writing;OWASP | G0/G4 硬门 3× retry → block + `_failed/`;`SourceFailure` fail-fast | ✅ 已满足 |
| 错误四问模型:人类可读 message + 机器可读 code + 4xx/5xx 分层 + 可操作下一步;不泄漏堆栈/内部 ID | OWASP(信息泄漏=A10:2025);Reclear;AgentPlaybook | `{success,error:{code,message,actionable}}` + 28 ErrorCode + `LLM_NOT_CONFIGURED` 带提示 — 基本实现 | 🟡 部分(需核对:错误码是否 snake_case 可机器处理?429 是否带 Retry-After?堆栈是否可能泄漏到 REST 响应?) |
| 类型化异常;只在能恢复时捕获;裸重抛保留栈 | Microsoft .NET;OWASP dev guide | `ErrorCode` 枚举 + `SourceFailure` 类型化 ✅;但全库裸 `except: pass` / log-and-throw / Pokemon 捕获需扫描 | 🟡 部分(需代码扫描验证) |

### D1-4 命名/注释/一致性(含 AI 代码) 📐 / ⚖️

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| 一致性层级:模块内 > 项目内 > PEP 8;命名反映用法而非实现 | PEP 8(Emerson 引语) | ruff 强制格式;命名规则(N 系列)是否启用未验证 | 🟡 部分 |
| 注释解释 why 不解释 what;但接口头注释是抽象核心(Ousterhout vs Clean Code 分歧) | Google eng-practices;APOSD 辩论 ⚖️ | 模块边界注释(工具文档/数据模型)存在 ✅;函数体内复述注释(AI 生成重灾区)未审计 | 🟡 部分 |
| **AI 生成代码专项审查**:命名不一致达人类 2x(CodeRabbit 470PR);幻觉包名 5.2%(USENIX 2025);同义反复测试;跨文件副作用 | CodeRabbit;USENIX Security 2025;Tenki;Microsoft .NET blog | 项目是 agent 密集开发;无专项 AI 代码审查清单 | ❌ 差距(高 ROI) |

### D1-5 Python 工程现状 📐 / 🔬

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| 类型检查已主流化(86-88% 采用);mypy 仍主流,Rust 系检查器上升 | Meta Typed Python Survey 2024/2025 🔬 | ruff + mypy strict — 与主流一致 | ✅ 已满足 |
| src layout 是事实默认(pytest/PyPA 官方推荐) | pytest goodpractices;pydevtools | `src/autoinfo/` — 已用 | ✅ 已满足 |
| 覆盖率是探针不是裁决,不设全局门槛 | Fowler;Google | G0-G5 不用覆盖率做门 | ✅ 已满足(刻意不为) |
| 测试断言行为而非实现细节;防 AI 生成"自我验证"测试 | deep-modules-skill;AI 评审共识 | ~4345 测试;测试质量(mutation 视角)未系统验证 | 🟡 部分 |

### D1-6 代码评审实践 🔬 / 📐

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| Small CL + 评审标准(不追求完美,只求整体健康随时间改善)+ CL 必须含测试 | Google eng-practices 📐 | 项目 CI + Makefile 有 make test/lint;无评审 checklist 文档 | 🟡 部分 |
| **实证校准**:PR 大小与合并时间无关(845,316 PR,ρ=0.26);PR 描述质量解释 ~46% 评审延迟;可维护性问题占评审问题 75% | Kudrjavets 2022 🔬;Caulo et al. 🔬 | 未发现 PR 模板强制"为什么+影响面+局限" | ❌ 差距(低成本高回报) |
| 语义化提交(Conventional Commits)与 SemVer 对应 | Conventional Commits 📐 | CHANGELOG 有版本化;提交规范未强制 | 🟡 部分 |

---

## §3 维度 2:面向 Agent 项目最佳实践

> 本地现状基线:agent-first 是**系统性贯穿**(根规格 B2 定义 + AC1 FAIL 门槛 + ADR-0005 envelope 以 agent 为理由 + dispatch 层代码强制)。但**无成文的 MCP 工具设计准则**(AX 在 glossary 仅一行);agent 身份/限流全规格态;B2.5 Monitor/B2.6 Report 未交付;A2A 未做。2026-08-14 已修复 2 处文档自相矛盾(promote 授权边界),见 §5 D-债-1。

### D2-1 MCP 工具设计 🔵 共识度最高项

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| 工具是"确定性系统↔非确定性 agent"的契约,不是 API 包装;按 agent 感知方式设计(search_contacts 优于 list_contacts) | Anthropic "Writing effective tools"(2025-09) | 146 工具;是否有"原样包装 API"的工具未审计 | 🟡 部分 |
| 描述像给新员工写文档:动词化命名;参数 ≤8(AWS)/≤5(Grizzly);有限值用 enum + default;描述含"何时用"与示例;40+ 词描述与选择准确率正相关 | AWS;RaftLabs;Grizzly Peak;Anthropic | ✅ **已审计 2026-08-14**(`scripts/tool_desc_audit.py`,146 工具全量):99.3% 动词风格命名(唯一违规 `email_config`);参数均值 2.68、>8 仅 4 个(`add_source`/`generate_digest`/`generate_report`/`search_knowledge_base`);⚠️ **36 个工具描述 <10 词**(短描述无"何时用"信号;2026-08-14 消歧后 40→36)与 **103 个工具零 enum 参数**(有限值未声明 enum)——这两项是高 ROI 改进点 | 🟡 部分(命名/参数已达标,描述与 enum 待提升) |
| 可操作错误信息:错误码 + 人类/LLM 可读消息 + 建议修复;不返回裸 HTTP 状态码 | Anthropic;AWS | envelope 已实现;28 ErrorCode message 是否都含"具体修复"需核对 | 🟡 部分 |
| 返回高信号字段:UUID 换语义可读标识;response_format concise/detailed(1/3 token) | Anthropic | `summary_id`/条目 ID 对模型语义友好度未验证;concise 模式无 | 🟡 部分 |
| 工具合并与拆分:单一清晰目的;合并频繁链式调用;相似工具 <10 个就会让 agent 迷惑 | Anthropic;OpenAI | 35 类别 146 工具;相似度审计(list_summaries/get_summary/search_knowledge_base 边界)未做 | 🟡 部分 |

### D2-2 错误信封与协议 🔵

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| 双通道错误:协议错误(JSON-RPC error,模型无法修复)vs 工具执行错误(isError + message,模型可自纠)| MCP spec;MCP TS SDK | envelope 是结果通道;协议级错误路径待核对 | 🟡 部分 |
| Security MUSTs:输入校验、访问控制、**工具调用限流**、输出清洗;安全注解不可信 | MCP spec | LLM 层有 per-provider semaphore ✅;工具调用层限流未确认 | 🟡 部分 |
| tools/list 分页 + listChanged 通知;命名空间化(前缀)提升选率 | MCP spec | 146 工具横跨 35 类别;前缀命名空间化未系统化 | 🟡 部分 |

### D2-3 长任务语义(2026 新共识) 🟢

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| **Poll-first 是真相源,webhook 只是优化**(agent 常无入站路由;webhook at-most-once) | dreaming.press 2026-07;MCP Tasks;Anthropic/OpenAI Batch | `get_collection_progress` 轮询 ✅ + `set_agent_callback` durable outbox ✅ — 双轨正确;需核对 callback 失败有轮询回退 | ✅ 已满足(设计方向正确) |
| 异步请求-应答:202 Accepted + Location + 状态端点;终态不可变;指数退避+jitter;总尝试上限 | Async Agent Workflows 2026 | job 模型存在;状态端点/Retry-After/不可变终态语义待核对 | 🟡 部分 |
| **幂等键是硬要求**(agent 超时必然重试;flaky 网络 spawn 重复任务) | Async Agent Workflows;dreaming.press | `add_source` idempotent ✅;`collect_sources` dedup ✅;显式 Idempotency-Key 语义/覆盖度未确认 | 🟡 部分 |
| 持久任务状态 + 检查点恢复(状态绝不能只存内存) | Cloudflare;Async Agent Workflows | SQLite job 状态持久化 ✅ | ✅ 已满足 |
| 合作式取消(信号而非同步状态查询) | MCP Tasks;Async APIs | 无取消工具(clean_cache 是清理非取消) | ❌ 差距 |
| MCP progress 通知:opt-in token、单调递增、完成后停止 | MCP spec | `get_collection_progress` 是拉取式 ✅;流式通知未实现(SSE future) | 🟡 部分 |
| webhook 可靠性工程:签名/事件 ID 去重/时间戳拒旧/重试/replay 端点;SSRF 防护 | A2A protocol;Meshy | durable outbox 落库 ✅;签名/去重/replay 未确认 | 🟡 部分 |
| 时长分层:<10s 同步;分钟级轮询;小时级 workflow 引擎 | Async Agent Workflows | collect/process 分钟级 → 轮询 ✅;video 生成是否需独立语义待评估 | ✅ 已满足 |

### D2-4 可观测性与 eval 闭环 🟢

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| run/trace/thread 三级观测原语;评估粒度与之一一映射 | LangChain agent evals 2026 | trace_id 业务级贯穿 ✅;缺 thread(会话级分组)与 span 树 | 🟡 部分 |
| 生产 trace 转回归数据集(flywheel) | LangChain;OpenAI cookbook | `scenarios/regression/` 回归飞轮 ✅ + bug_report 模板强制回归场景 ✅ | ✅ 已满足(业界前沿形态) |

### D2-5 agent 身份与反馈环 🟡

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| per-agent 身份、限流、审计归因 | multi-tenancy-auth §2.6(项目自己) | 全规格态,零实现(stdin 假设可信) | ❌ 差距(已知设计,未落地) |
| B2.5 Monitor / B2.6 Report 交付 | user-lifecycle-definition §3.2 | B2.6 Report ❌(无结构化汇报机制);B2.5 🟡 | ❌ 差距(文档自认) |

---

## §4 维度 3:Validation 与 agent-as-tester 最佳实践

> 本地现状基线:agent-as-tester 是**最成熟的维度**——AC1-AC9 判据 + validation-scenario-contract 机制 + 117 场景(65 functional + 52 regression)+ 2 次实跑 + 诚实性机制(unconfigured/RED-GREEN/SUSPECT)。业界先例确认这不是孤例(Anthropic evals、τ-bench、AutoCover、SpecOps 都是同行)。

### D3-1 agent-as-tester 业界先例确认 🔬

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| scenario/task-based agent 验证是 2024-2026 标准形态:Anthropic evals、τ-bench(数据库终态比对 + pass^k)、AutoCover(Uber,5-agent + mutation 质量门)、SpecOps(4-agent,F1=0.89)、TestExplora(主动找 bug F2P 仅 16%) | Anthropic;τ-bench;ICSE 2026 | 117 场景 + agent-tester 执行 + LLM-judge + 验收报告 — **与业界前沿同形态** | ✅ 已满足(强项,可引为行业先例) |
| **grade outcome,别 grade path**(过度断言工具调用顺序 → 测试过脆) | Anthropic "Demystifying evals" | 需核对:场景是否断言"必须调用 X 工具"(路径断言) | 🟡 部分 |
| 隔离环境防共享状态/作弊(Claude 曾看 git history 取巧) | Anthropic | 场景隔离/环境重置机制需核对 | 🟡 部分 |
| 0% pass@100 通常是坏任务而非坏 agent;grader bug 是回归源(CORE-Bench 42→95%) | Anthropic;aiarch.dev | 场景作者需读失败 transcript 区分"agent 错 vs grader 错" | 🟡 部分 |
| **AI 主动找 bug 能力仍弱**:agent-as-tester 适合验证已知期望,不适合发现未知缺陷 | TestExplora F2P 16%;Anthropic "Claude is a poor QA agent out of the box" | validation 定位为验收/回归 ✅;探索性测试留白 | ✅ 已满足(定位正确) |

### D3-2 LLM-as-judge 校准(本维度最大事实缺口) 🔬

| 业界主张 | 来源(证据强度) | AutoInfo 对照 | 结论 |
|---------|--------------|--------------|------|
| LLM-judge 有系统性偏差:单次翻转率 13.6%、28% 问题 >20% 翻转;跨 judge κ=0.51;style bias 0.76-0.92 是主导;需要 11 次重复投票恢复 95% 置信 | arXiv 2606.13685;2604.23178 等 🔬 | G4/G5 用 LLM-judge(`JUDGMENT_MODEL` 固定);无 golden-set 校准证据、无多试次聚合 | ❌ 差距(事实缺口) |
| **校准是信任前提**:golden set 50-100 例(必须含坏例)、目标 agreement 80-90s%、kappa 度量、定期重校准;未校准 judge "比没有更糟" | Airbnb EDD;Anthropic | 无校准证据记录 | ❌ 差距(事实缺口) |
| 缓解:CoT 唯一全无害策略;rubric;escape hatch("可以答 Unknown");维度隔离,不用 God judge | Anthropic;LLM-judge 研究 | escape hatch/维度隔离未记录 | 🟡 部分 |
| 确定性 grader 优先(code-based > LLM judge > human 校准);LLM 擅长比较/[分类] 而非开放生成 | OpenAI;Anthropic | G0 schema/G2 dedup 是 code-based ✅;G4/G5 主观维度 LLM ✅ 结构正确 | ✅ 已满足(结构正确) |
| capability evals(从低 pass 测进步)vs regression evals(~100% 防回退);饱和后晋升 | Anthropic | 117 场景已分 functional + regression ✅;capability/regression 双套件显式化 + 饱和轮换机制未文档化 | 🟡 部分 |

### D3-3 测试分层与 AI 时代调整 🔬 / 📐

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| 金字塔是成本模型不是比率;AI 生成测试会系统性放错层级(写 15 分钟套件) | Fowler;Nick Perkins 2026 | 4345 pytest + 117 场景分层结构未显式文档化 | 🟡 部分 |
| E2E 脆性实证:Google 0.5% 小 vs 14% 大 flaky;不可靠测试移出 CI gate | Google Testing Blog 🔬 | 117 场景是 large tests;flaky 处理机制(多跑统计/移出 gate)未文档化 | 🟡 部分 |
| TDD 实证校准:收益来自节奏非顺序;测试先行不是银弹;ATDD 十年后单一来源理想未兑现 | TSE 2013;Karac 2018;Gojko Adzic 🔬 | RED→GREEN + regression flywheel ✅(节奏价值有实证支撑) | ✅ 已满足 |
| 覆盖率是探针;mutation testing 是解药(Google 15M mutants;70% 真实 bug 与 mutant 耦合) | Fowler;Google 🔬 | 未用 mutation;G4 factual 自审是自证性 | 🟡 部分 |

### D3-4 CI/CD 质量门 📐

| 业界主张 | 来源 | AutoInfo 对照 | 结论 |
|---------|------|--------------|------|
| hard/soft 拆分 + retry-first block-last 符合"per-release criteria + owner + 证据链" | Rex Black;Harness | G0-G5(硬/软)+ D1-D3 + 3×retry → block — 结构完全符合 | ✅ 已满足 |
| gate 阈值按基线校准:先 advisory 两周再 blocking,再 ratchet | Implera;SonarQube CAYC | 阈值/过渡机制未文档化 | 🟡 部分 |
| 错误预算作 meta-gate(预算耗尽暂停 feature,不看测试) | Rex Black;SRE | LLM token 成本有 metering;成本耗尽暂停 promotion 无 | 🟡 部分 |
| 质量门是 safety net 不是 productivity target;太紧诱发 bypass | Matty Stratton | 设计哲学已符合(retry-first) | ✅ 已满足 |

---

## §5 差距分级清单

### 🩹 D-债(文档债 — 立即修复,低成本)

| ID | 差距 | 事实 | 处置 |
|----|------|------|------|
| D-债-1 | promote 授权边界文档自相矛盾 | `director-user-guide.md` §5.1/§10 与 `docs/archive/enduser-capabilities-guide.md`(归档前 §3/§5)前后冲突(human-only vs agent-driven) | ✅ **已修复 2026-08-14**:统一为 agent 操作(`promote_kb_draft`,无人类门) |
| D-债-2 | master-plan 目录过期仍标 active | `autoinfo-validation-master-plan/` 4 文件数据停在 2026-07-31(141 工具/47 场景),与现行 146/68 冲突 | ✅ **已处置 2026-08-14**:git mv 至 `docs/archive/autoinfo-validation-master-plan/`,全部标注 superseded |
| D-债-3 | `docs/agent-tester-validation-guide.md` 游离 | git untracked、不在 doc-inventory 的 66 文件清单 | ✅ **已处置 2026-08-14**:独有事实(§8.3 citation traps)并入 contract,文件入库并归档至 `docs/archive/` |
| D-债-4 | validation-reports/README closure 状态落后 | B-01/B-02/R-01 已关闭但 README 标 open | ✅ **已修复 2026-08-14** |
| D-债-5 | AC9 "best-practice research" 来源不可核查 | 只标日期无来源/方法/范围 | ✅ **已处置 2026-08-14**:本维度 §9 作为其来源索引,AC9 已加交叉链接 |

### 🔧 D-工(工程债 — 需代码/审计工作,按 ROI 排序)

| ID | 差距 | 来源证据 | 工作量级 | ROI | 状态 |
|----|------|---------|---------|-----|------|
| D-工-1 | **146 工具描述/参数审计**(命名动词化、参数 ≤8、enum/default、description 含示例与"何时用") | AWS/RaftLabs/Anthropic — 共识度最高项;Anthropic 实测描述改进降 40% 任务时间 | 中(可脚本化半自动) | 极高 | ✅ **审计已落地** → `scripts/tool_desc_audit.py`(2026-08-14 落地,2026-08-23 重跑,146 工具,回归测试 7 例);剩余短描述/enum 差距转 backlog |
| D-工-2 | **LLM-judge 校准证据**(golden set 50-100 例、kappa、多试次) | Airbnb EDD;arXiv 2025-2026 偏见研究 | 中 | 高(直接提升 G4/G5 可信度) | ✅ **已校准(真实运行)** → `scripts/llm_judge_calibration.py`(2026-08-14:8 例 seed golden set × 3 试次,accuracy 1.0 / kappa 1.0 / spread 0.0,证据 `validation-runs/coverage/llm-judge-calibration-2026-08-14.json`(未重跑——需 LLM key;D-工-2 证据保持 08-14 最新),回归测试 9 例);扩充至 50-100 例为后续 backlog |
| D-工-3 | **AI 代码专项审查清单**(命名一致、幻觉包名、同义反复测试) | CodeRabbit;USENIX 2025 | 低(文档 + PR 模板) | 高 | ⏳ 待落地 |
| D-工-4 | 错误信息一致性审计(28 ErrorCode 的 message 是否全含修复指引;429 Retry-After;堆栈泄漏) | OWASP;MCP spec | 低-中 | 高 | ✅ **已修复** → `scripts/error_message_audit.py`(2026-08-14 落地,2026-08-23 重跑,0 缺修复指引,**0 裸异常**——65 处 `_error_dict(exc)` 全部替换为 `_error_from_exc(exc, context)` 统一模板(context + 异常 + retry 指引),回归测试 9 例) |
| D-工-5 | 场景路径断言审计(grade outcome 别 grade path)+ 隔离环境防作弊 | Anthropic | 低-中 | 中 | ✅ **审计已落地** → `scripts/scenario_outcome_audit.py`(2026-08-14 落地,2026-08-23 重跑:117 场景/450 步,outcome 断言 ≥95%,0 未门控 llm_assert/http,回归测试 9 例) |
| D-工-6 | 幂等键显式语义 + 合作式取消 | MCP Tasks;Async workflows | 中 | 中 | ⏳ 待落地 |
| D-工-7 | 工具相似度审计(35 类别 146 工具边界) | Anthropic;OpenAI | 中 | 中 | ✅ **已修复** → `scripts/tool_similarity_audit.py`(2026-08-14 落地,2026-08-23 重跑:146 工具,0 名称边界碰撞,**0 高描述重叠对**——10 个工具描述用独有词汇消歧,回归测试 7 例) |
| D-工-8 | capability/regression 双套件 + 饱和轮换机制文档化 | Anthropic | 低 | 中 | ⏳ 待落地 |
| D-工-9 | PR 模板强制"为什么+影响面+局限" | Kudrjavets 2022(446% 评审延迟解释) | 低 | 中 | ⏳ 待落地 |

### 🏗️ D-构(结构性空位 — 需设计决策)

| ID | 差距 | 事实 | 建议 |
|----|------|------|------|
| D-构-1 | watchdog 外部质量基准锚(AC5 判据自证 + market-positioning 被标 not operational) | explore 盘点 & market-positioning L12 | 本维度即为该锚的第一版;后续可加竞品对照阅读证据 |
| D-构-2 | agent 身份/限流/审计归因零实现 | multi-tenancy-auth 全规范态 | 路由到既有 multi-tenancy 规划,不在本维度落地 |
| D-构-3 | B2.6 Report / B2.5 Monitor 未交付 | user-lifecycle-definition §3.2 ❌/🟡 | agent 自身反馈环;接 topic proposal |
| D-构-4 | 消费反馈闭环(CD-040)缺 MCP 查询 | cross-dimensional-catalog | 接 feature wave |

---

## §6 基线盘点结论(做得好 / 差 / 需重构 / 需提升)

### ✅ 做得好(业界前沿或对齐,引用可背书)

1. **agent-as-tester validation 体系** — 与 Anthropic/τ-bench/AutoCover/SpecOps 同形态;117 场景真实面 + 诚实性机制 + 回归飞轮,是行业前沿而非孤例(D3-1)。
2. **统一错误信封** — `{success, error:{code,message,actionable}}` + ADR-0005 以 agent 为理由;命中 MCP 双通道错误 + OWASP 四问模型(D2-2/D1-3)。
3. **深模块 doctrine** — 项目化 Ousterhout 实践(7 步程序 + watch-list + 可测试性陷阱守卫),超过多数仓库的"风格文档"(D1-1)。
4. **Poll-first + 持久 job + 幂等 dedup + 回归飞轮** — 全中 2026 新共识(D2-3/D2-4)。
5. **质量门哲学** — hard/soft 拆分 + retry-first block-last,符合 Rex Black 退出门标准(D3-4)。

### ❌ 做得不好(事实缺口 — 应立即处理)

1. **LLM-judge 校准证据已落地** — 2026-08-14 真实运行(8 例 seed golden set × 3 试次,accuracy 1.0 / kappa 1.0 / spread 0.0,证据 JSON 入库,回归测试 9 例);仍待扩至 50-100 例且覆盖更多 task 类型(D3-2)。
2. **36 个工具描述 <10 词、103 个工具零 enum 参数** — 审计已证实(2026-08-14,`scripts/tool_desc_audit.py`;描述消歧后 40→36);命名(99.3% 动词风格)与参数数(均值 2.68)已达标,但短描述与缺失 enum 是 D-工-1 剩余的高 ROI 差距(D2-1)。
3. **AI 代码专项审查缺失** — 项目是 agent 密集开发,却无针对 AI 生成代码的审查清单(D1-4)。

### 🔧 需重构(有明确业界模式可对齐;审计证据均已落地,重构本身转 backlog)

1. 工具命名空间化 + 描述消歧(35 类别 → 前缀分组 + 合并重叠)—— 边界审计已证实 0 名称碰撞;**8 高描述重叠对已消歧为 0**(2026-08-14,10 个工具描述独有词汇化,`scripts/tool_similarity_audit.py`,D2-1)。
2. 场景从"路径断言"转向"outcome 断言"—— 已 ≥95% 达标(2026-08-23 重跑 117 场景/450 步),残余 12 步无 success 键(`scripts/scenario_outcome_audit.py`,D3-1)。
3. 错误处理审计(裸 except、log-and-throw、429 Retry-After)—— 0 缺修复指引;**65 处 `_error_dict(exc)` 裸异常泄漏已全部替换为 `_error_from_exc(exc, context)` 统一模板(0 裸异常,2026-08-14 落地,2026-08-23 重跑,`scripts/error_message_audit.py`,D1-3)**。

### 📈 需提升(渐进改进,非缺陷)

1. PR 描述质量强制 + AI 审查清单入 PR 模板(D1-6/D2-1)。
2. capability/regression 双套件显式化 + 饱和轮换(D3-2)。
3. 门禁 advisory→blocking 过渡机制 + 错误预算 meta-gate(D3-4)。
4. 度量程序(LOC/耦合探针,明确"非裁决"定位)(D1-2)。

---

## §7 教训与对策

> **本维度自身的教训(基于盘点过程的事实)**

1. **"最佳实践"引用必须可核查** — AC9 的 "external best-practice research" 无来源是反面案例;本维度所有判据带来源与证据强度(§2-§4),来源索引见 §9。
2. **先立稳视角,再谈提升** — 本次盘点证明本地"预期驱动"视角成熟,但外部标尺是空位;你的直觉(补第三维)得到文档事实支持。
3. **文档矛盾是信任杀手** — 2 处 promote 自相矛盾削弱整个 agent 视角可信度;已修复,复跑时纳入检查项。
4. **业界事实库会过时** — 2026 年 poll-first 反转 webhook 建议就是例证;§9 来源索引标注检索日期,复跑时刷新。

---

## §8 复跑节奏协议

| 项 | 内容 |
|----|------|
| 触发 | 每 feature wave 结束(与 AC1-AC9 验收报告同步);或重大架构变更后 |
| 动作 | ① 刷新 §9 来源(新增 2026-2027 共识);② 重跑可脚本化审计(D-工-1/4/5/7);③ 更新对照表结论;④ 生成"差异报告"(本次 vs 上次) |
| 输出 | 本文档的修订 + 差距清单增删(§5) |
| 自动化候选 | ✅ 工具描述审计 → `scripts/tool_desc_audit.py`(2026-08-14,146 工具,回归 7 例);✅ 错误信息审计 → `scripts/error_message_audit.py`(2026-08-14 落地,2026-08-23 重跑,回归 9 例);✅ 场景 outcome 审计 → `scripts/scenario_outcome_audit.py`(2026-08-14 落地,2026-08-23 重跑:117 场景/450 步,回归 9 例);✅ 工具相似度审计 → `scripts/tool_similarity_audit.py`(2026-08-14,146 工具,回归 7 例);✅ LLM-judge 校准 → `scripts/llm_judge_calibration.py`(2026-08-14,seed golden set + kappa,回归 9 例)。全部输出 `validation-runs/coverage/*-<date>.json` |
| 与验收框架关系 | 本维度**不**设 FAIL/PASS 判据;差距项转为工程 backlog 由 wave 处理,最终状态仍由 AC1-AC9 判定 |

---

## §9 证据与来源索引

> 检索日期:2026-08-14。分维度组织;每条含来源与证据强度。复跑时刷新。

### 代码质量(D1)

| 来源 | 类型 | 引用项 |
|------|------|--------|
| Ousterhout《A Philosophy of Software Design》+ [official site](https://stanford.edu/~ouster/cgi-bin/aposd.php) | 📐 | D1-1 |
| [APOSD vs Clean Code 官方辩论](https://github.com/johnousterhout/aposd-vs-clean-code/) | ⚖️ | D1-1/D1-4 |
| [Shepperd 1988, "A critique of cyclomatic complexity"](https://www.cs.du.edu/~snarayan/sada/teaching/COMP3705/lecture/p1/cycl-1.pdf) | 🔬 | D1-2 |
| [Zhou et al. TSE 2009, class size confounding](https://dl.acm.org/doi/10.1109/TSE.2009.32) | 🔬 | D1-2 |
| [TSE 2005, coupling×cohesion interaction](https://dl.acm.org/doi/10.1109/TSE.2005.130) | 🔬 | D1-2 |
| [Tertiary study 2023, source code metrics](https://www.sciencedirect.com/science/article/pii/S0950584923002033) | 🔬 | D1-2 |
| [Google eng-practices](https://google.github.io/eng-practices/) | 📐 | D1-4/D1-6 |
| [PEP 8](https://peps.python.org/pep-0008/) | 📐 | D1-4 |
| [OWASP Error Handling Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html) + [Dev Guide](https://devguide.owasp.org/en/04-design/02-web-app-checklist/10-handle-errors-exceptions/) | 📐/🔬 | D1-3 |
| [Microsoft .NET exceptions best practices](https://learn.microsoft.com/en-us/dotnet/standard/exceptions/best-practices-for-exceptions) | 📐 | D1-3 |
| [CodeRabbit — naming inconsistency study](https://gitautoreview.com/blog/code-review-checklist-ai-generated-code)(2x 人类基线,470 PR) | 🔬 | D1-4 |
| [USENIX Security 2025 — hallucinated packages](https://www.usenix.org/system/files/usenixsecurity25-lekies.pdf)(5.2%) | 🔬 | D1-4 |
| [Meta Typed Python Survey 2024/2025](https://engineering.fb.com/2024/12/09/developer-tools/typed-python-2024-survey-meta/) | 🔬 | D1-5 |
| [pytest Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html) | 📐 | D1-5 |
| [Fowler — Test Coverage](https://martinfowler.com/bliki/TestCoverage.html) | 📐 | D1-5 |
| [Kudrjavets 2022 "Do Small Code Changes Merge Faster?"](https://arxiv.org/html/2203.05045)(845,316 PR) | 🔬 | D1-6 |
| [Caulo et al., knowledge transfer in code review](https://www.inf.usi.ch/lanza/PUBS/P/Caul2020a.pdf)(75% 可维护性) | 🔬 | D1-6 |

### 面向 Agent(D2)

| 来源 | 类型 | 引用项 |
|------|------|--------|
| [Anthropic — Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) | 📐 | D2 原则 |
| [Anthropic — Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents) | 📐/🔬(40% 描述改进) | D2-1 |
| [Anthropic — Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | 📐 | D2-1(高信号字段) |
| [MCP spec(2025-06-18 tools)](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) | 📐 | D2-2 |
| [MCP 2026-07-28 RC + Tasks extension](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/);[Tasks spec](https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks);[SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2663-tasks-extension.md) | 📐(draft) | D2-3 |
| [AWS MCP tool design](https://aws.amazon.com/blogs/machine-learning/mcp-tool-design-practical-approaches-and-tradeoffs/)(2026-07-09) | 📐 | D2-1 |
| [Webhooks vs Polling for Long-Running Agent Tasks](https://dreaming.press/posts/webhooks-vs-polling-for-long-running-agent-tasks.html)(2026-07)| 🟢 📐 | D2-3 |
| [Async Agent Workflows](https://tianpan.co/blog/2026-03-07-async-agent-workflows-long-running-task-design) | 📐 | D2-3 |
| [Cloudflare — Long-running agents](https://developers.cloudflare.com/agents/concepts/agentic-patterns/long-running-agents/) | 📐 | D2-3 |
| [A2A Protocol — Streaming & Async](https://a2a-protocol.org/latest/topics/streaming-and-async/)(Linux Foundation) | 📐 | D2-3 |
| [LangChain — Agent evals(run/trace/thread)](https://www.langchain.com/resources/agent-evals) | 📐 | D2-4 |
| [OpenAI — Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) | 📐 | D2-4 |
| [OpenAI — A practical guide to building agents](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/) | 📐 | D2-1 |

### Validation / agent-as-tester(D3)

| 来源 | 类型 | 引用项 |
|------|------|--------|
| [Anthropic — Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)(outcome/trajectory、隔离、grader 校准) | 📐 | D3-1/D3-2 |
| [Anthropic — Harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)(generator/evaluator 分离、default-FAIL) | 📐 | D3-1 |
| [Anthropic — Multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | 📐 | D3-1 |
| [τ-bench(Sierra)](https://arxiv.org/pdf/2406.12045)(数据库终态 + pass^k) | 🔬 | D3-1 |
| [AutoCover(Uber, ICSE 2026)](https://homes.cs.washington.edu/~rjust/publ/auto_cover_icse_2026.pdf)(5-agent + mutation 门) | 🔬 | D3-1 |
| [SpecOps(ICSE 2026)](https://arxiv.org/abs/2603.10268v1)(4-agent GUI 测试,F1=0.89) | 🔬 | D3-1 |
| [TestExplora(Microsoft, MSR)](https://www.microsoft.com/en-us/research/publication/testexplora-benchmarking-llms-for-proactive-bug-discovery-via-repository-level-test-generation/)(F2P 16%) | 🔬 | D3-1 |
| [LLM-as-judge 偏见研究:arXiv 2606.13685(翻转率 13.6%)](https://doi.org/10.48550/arxiv.2606.13685);[2604.23178(κ=0.51)](https://doi.org/10.48550/arxiv.2604.23178);[2509.26072](https://arxiv.org/html/2509.26072v2) | 🔬 | D3-2 |
| [Airbnb — Eval-driven development](https://airbnb.tech/ai-ml/eval-driven-development-lessons-from-evaluating-genai-at-scale/)(golden set 校准) | 📐 | D3-2 |
| [Google Testing Blog — flaky tests](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html);[where flaky come from(2017)](https://testing.googleblog.com/2017/04/where-do-our-flaky-tests-come-from.html) | 🔬 | D3-3 |
| [Karac & Turhan "What Do We (Really) Know about TDD"(IEEE Software 2018)](https://ieeexplore.ieee.org/document/8405634) | 🔬 | D3-3 |
| [TSE 2013 TDD meta-analysis](https://dl.acm.org/doi/10.1109/TSE.2012.28) | 🔬 | D3-3 |
| [Google mutation testing(ICSE-SEIP 2018)](https://research.google/pubs/pub46584/);[arXiv 2103.07189](https://ar5iv.labs.arxiv.org/html/2103.07189) | 🔬 | D3-3 |
| [Nick Perkins — Testing Pyramid still matters(AI)](https://nickperkins.au/article/testing-pyramid-ai-development/) | 📐 | D3-3 |
| [Block — Testing Pyramid for AI Agents](https://engineering.block.xyz/blog/testing-pyramid-for-ai-agents)(确定性/可复现/概率/自测四层) | 📐 | D3-3 |
| [Rex Black — Exit and Release Criteria](https://rexblack.com/resources/writing/exit-and-release-criteria) | 📐 | D3-4 |
| [Implera — PR Quality Gates](https://implera.ai/blog/pr-quality-gates-a-complete-guide) | 📐 | D3-4 |
| [Matty Stratton — decouple release from deploy](https://www.mattstratton.com/writing/decouple-release-from-deploy/) | 📐 | D3-4 |

---

**Status:** Baseline 2026-08-14;§8 复跑执行于 **2026-08-23**(文档架构精简 wave)——刷新场景/测试/审计统计至 117/4345 及 08-23 重跑证据。下次复跑:随下一 feature wave 验收报告。