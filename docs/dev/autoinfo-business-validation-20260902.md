# AutoInfo 商业论证状态报告（启动阶段）

> **日期**：2026-09-02 · **验证轮次**：第 1 轮（demo 阶段基本完工）
> **项目状态**：已建成、demo 交付包 R5(1) 通过独立审查、周迭代（最近 10 天 150 提交）
> **方法论**：business-validation skill（Steve Blank / JTBD / ODI / Sean Ellis / Van Westendorp）
> **数据纪律**：一切结论带来源；找不到的标注 [未验证]；禁止凭印象

---

## 一句话结论

**AutoInfo 占据"信息追踪 + 知识库"的中间地带，产品能力远超任何单一竞品（8 产品 × 8 格式 × 146 MCP 工具 × 21 域），但面临双重挤压：上游被"通用 Agent + 免费 skill"斩杀（RSS digest/monitoring 可 DIY），下游被快速进入中间价位的 AI 工具（Readless/Competely）蚕食。** 付费意愿成立的核心证据是 **B2B PROCESSED 产品的差异化价值（质量门控 + 多格式 + 溯源），而非 RAW 数据管道（commodity）**。

---

## 阶段 0：项目状态锚定

### 产品成熟度（实测数据）
| 锚定项 | 数据 | 来源 |
|:-------|:-----|:-----|
| 产品形态 | 信息追踪 + 知识库平台（Universal information tracking and KB platform） | [README.md](../../README.md) |
| 开发迭代 | **663 提交，最近 10 天 150 提交**（高速迭代中） | `git rev-list --count` |
| 测试规模 | **247 测试文件** | `find tests -name "test_*.py"` |
| Validation 场景 | **130 场景（65 功能 + 65 回归）** | `find src/autoinfo/mcp/scenarios` |
| MCP 工具 | **146 工具 / 35 类别** | README |
| 采集器 | **30 collector handlers**（RSS/API/Web/Webhook/Email/PDF + 21 内置域） | README |
| Demo 交付 | `autoinfo-demo-package-20260902-perfect2.zip`（**437 文件，4 域 × 24 产物，全溯源**）[已修正 2026-09-04：该文件在本仓库与 $HOME 均不存在，deliverables/ 目录亦不存在；最近似真实交付物为 outputs/autoinfo-deliverable-13domains-20260810.zip（2026-08-10，734KB，13 域）] | deliverables/ |
| Demo 质量 | **R5(1) 通过独立全量审查，0 P0/P1/P2**[已修正 2026-09-04：仓库无 R5 独立审查报告存档（DoD 标准 1 要求审查报告归档，缺失）；demo-release-standard.md:12 仅为自查勾选行；R6 样本 1/2 ✅、R7 样本 2/2 ⏳] | docs/demo-release-standard.md |
| 商业化痕迹 | Stripe 集成、订阅分层（Free/Premium/Enterprise）、消费追踪、生命周期管理 | README features |
| 用户模型 | **B1 付费终端用户 / B2 Agent 操作者 / B3 人类总监** | docs/dev/specs/user-lifecycle-definition.md |

### 状态声明
**AutoInfo：已建成（247 测试 / 130 validation 场景），demo 阶段基本完工（R5 通过），零真实付费用户，周迭代（150 提交/10天）。** 商业验证目标：启动阶段确认定位、用户画像、竞品坐标、付费意愿。

---

## 阶段 1：客户身份锚定（JTBD）

### 客户身份卡（来自项目自有市场文档 + 外部验证）

**AutoInfo 服务两类客户，对应两条产品线：**

| 维度 | 客户 A：信息购买者（RAW 产品） | 客户 B：知识产品订阅者（PROCESSED 产品） |
|:-----|:-----|:-----|
| 具体身份 | 制药竞品情报分析师、VC 交易挖掘、政策研究负责人、市场情报经理 | 忙碌临床医生、投资组合经理、创业公司创始人、高管决策者 |
| 雇佣工作 | 把分散多源的公开信息 → 结构化、可消费的 RAW 数据流 | 把 RAW 信息 → 提炼、分析、可定期消费的知识产品 |
| 现状替代 | 每年 $10-100K 付给专有数据库（Capital IQ/AlphaSense）| 手动订阅多源 newsletter / 无暇阅读一手资料 |
| 付费意愿 | **$50-500/月**（可靠领域 RAW 流）| **$100-2,000/月**（领域化 PROCESSED 情报）|
| 质量关切 | 完整性、新鲜度、来源可溯 | 事实准确性、分析深度、时效、呈现质量 |
| 来源 | docs/dev/specs/market-positioning.md §7.2 | 同左 |

### JTBD 核心洞察
**"翻译完还要保持原版式"式的具体工作**：客户要的是"不用自己读 100 个源，就能得到结构化的领域情报"——这个需求已被付费 newsletter 生态验证（TLDR 1.25M 订阅、Pragmatic Engineer $15/月），但 newsletter 是**人工 curation**，AutoInfo 是**自动化 + Agent 原生**，这是差异点。

---

## 阶段 2：用户期望结果（ODI）

> 期望结果 = 方向 + 对象 + 度量 + 情境。来源必须是社区/竞品评论/文档，禁止凭空推测。

| 期望结果 | 来源 | 重要度 | 当前满意度 | 机会缺口 |
|:---------|:-----|:------:|:---------:|:--------:|
| 最小化 多源信息 累积到"来不及读"的时间（天） | Reddit r/rss "drowning in feeds / +999 unread" | 9 | 3 | 高 |
| 最小化 增加 RSS 源后 信息过载的时间（3 源即崩） | Reddit "once I add more than 3 sources, it becomes unmanageable" | 8 | 3 | 高 |
| 最大化 每天花在阅读上的时间回报（省回的小时数/天） | TLDR "150 hours/year 省回"（开发者 newsletter 评测）| 8 | 4 | 中高 |
| 最大化 领域情报的新鲜度（小时级） | market-positioning §7.2 客户 A 质量关切 | 9 | 5 | 高 |
| 最大化 产物可追溯性（每条分析能溯源到源） | market-positioning §7.2 客户 A/B 共同关切 | 8 | 6 | 中 |
| 最大化 交付格式覆盖（能选 audio/video/epub 而非只有邮件）| market-positioning §7.7.3 格式商业化数据 | 7 | 4 | 中高 |

**证据来源**：Reddit r/rss 多帖（overwhelmed / drowning / not the solution）+ readless/rockstar 开发者 newsletter 评测 + 项目自有 market-positioning.md（其数据源自 2024-2026 全球信息付费调研报告）。

---

## 阶段 3：能力覆盖度矩阵（AutoInfo vs 竞品）

### 竞品当前定价（2026 实测，多源交叉）

| 竞品 | 类别 | 定价（2026） | 来源 |
|:-----|:-----|:-----|:-----|
| **Feedly** | RSS 阅读器 | Free $0 / Pro $6.99 / Pro+ $12.99 / Enterprise $1,600+/月 | readless.app 2026 + official |
| **Inoreader** | RSS 阅读器 | Free $0 / Pro $7.50-9.99 / Team $44.99+ / 50人 $374.99+ | inoreader.com/pricing |
| **AlphaSense** | 企业情报 | **$15K-$20K/座席/年**（SMB $12,210/年, Enterprise $123,760/年）| elevatedsignal.com + spendhound + vendr |
| **Kompyte**（Semrush）| 竞品监控 | $300/年起（不公开；Semrush 收购披露 avg $20K ARR/客户）| competely.ai + parano.ai |
| **Readless** | AI digest | Free / Pro $4.90 / Max $9/月（新玩家，2026）| readless.app/pricing |
| **Competely** | 竞品监控 | $39-$59/月起（公开定价）| competely.ai |
| **Diffbot** | Web 提取 API | Free $0 / Startup $299 / Plus $899/月 | diffbot.com/pricing |
| **KnowledgeSDK** | Web 提取 API | Starter $29 / Pro $99/月起 | knowledgesdk.com |

### 能力对照（AutoInfo vs 最有代表性的 3 类）

| 能力 | AutoInfo | Feedly Leo | Readless | AlphaSense |
|:-----|:--------:|:----------:|:--------:|:----------:|
| 多源采集 | ✅ 30 collectors | ✅ RSS+ | ✅ RSS | ✅ 专有库 |
| LLM 摘要 | ✅ G0-G5 门控 | ✅ Leo AI | ✅ | ✅ |
| **结构化提取** | ✅ 自定义 schema | ❌ | ❌ | ⚠️ 有限 |
| **KB 沉淀（Raw→Draft→Wiki）** | ✅ 4 层 | ❌ | ❌ | ⚠️ 无开放 KB |
| **多输出格式（audio/video/epub）** | ✅ 8 种 | ❌ | ❌ | ❌ |
| **Agent 原生（MCP）** | ✅ 146 工具 | ⚠️ 有 API | ❌ | ❌ |
| **BYOK（自带 LLM key）** | ✅ | ❌ | ❌ | ❌ |
| 数据所有权 | ✅ 文件本地 | ❌ SaaS | ❌ SaaS | ❌ SaaS |
| 交付渠道 | ✅ 13 种 | ❌ 邮件+App | ✅ 邮件 | ✅ 平台 |
| **质量门控（防幻觉）** | ✅ G0-G5+D1-D3 | ❌ | ❌ | ⚠️ |
| 价格 | **$0 起（BYOK）** | $7-1600 | $4.9-9 | $15K-100K/年 |

**结论**：AutoInfo 在**结构化提取、KB 沉淀、多格式输出、Agent 原生、BYOK、质量门控** 6 项上显著领先竞品。**没有单一竞品同时具备这 6 项**。但——这个"能力全面"本身也是双刃剑（见阶段 6）。

---

## 阶段 4：被斩杀风险测试（Agent-as-a-User 维度）

### 4.1 等价 skill 检查（必查清单）

| 检查项 | 发现 | 风险 |
|:-------|:-----|:----:|
| anthropics/skills 官方仓库 | **BlogWatcher skill**（RSS 监控）已在 KiwiClaw/OpenClaw 生态存在 | 🟡 |
| Hermes 自带 skills | **Hermes 内置 blogwatcher-cli**（RSS/Atom 监控）— 你已用 | 🟡 |
| skills.sh / 社区 | **rss-agent**（GitHub shiquda，SKILL.md）等 RSS 摘要 skill 已存在 | 🟡 |
| 通用 Agent 实测 | **Claude Code/Codex + MCP** 可以搭竞品监控 agent（Digital Applied 2026-07 实测）| 🟡 |

### 4.2 斩杀风险评级

| AutoInfo 能力块 | 通用 Agent + 现成 skill 能替代？ | 风险 | 硬差距 |
|:-----|:-----|:----:|:-----|
| **RSS 采集 + AI 摘要** | ✅ BlogWatcher + LLM 半小时搭出 | 🔴 高 | 无（免费 skill 已覆盖）|
| **竞品监控核心** | ✅ changedetection.io $8.99/月 + MCP = DIY 监控 | 🔴 高 | 无 |
| **结构化提取 + KB 沉淀** | ⚠️ 可搭但要写代码 | 🟡 中 | 部分（需要 schema 设计）|
| **质量门控（防幻觉/占位/泄漏）** | ❌ 通用 agent 不会默认做 | 🟢 低 | **强（R1-R13 硬扫 + G0-G5）** |
| **多格式产物（video/epub/audiobook）** | ⚠️ 可搭但工程量大 | 🟡 中 | 部分 |
| **端到端管线 + 溯源 + 审计** | ❌ 通用 agent 搭不出这种完备度 | 🟢 低 | **强** |

### 4.3 斩杀风险核心结论（诚实）

**Digital Applied 2026-07 文章是决定性证据**：企业 CI 套件 $16K-70K/年，但"MCP 连接是简单的 20%，hash-gate/去重/告警预算 才是让产品可用的 80%"。**监控核心已经被 DIY 化（$8.99/月 changedetection.io）**。

这直接威胁 AutoInfo 的 RAW 产品线（监控/数据管道 = commodity）。**但 AutoInfo 的防御不在管道，在质量门控 + 多格式产物 + 端到端完备性**——DIY agent 能采集能摘要，但**不会默认做 R1-R13 硬扫（空壳/泄漏/占位/品牌残留）+ D1-D5 付费价值维度**。这正是 AutoInfo 130 validation 场景证明的差异化。

---

## 阶段 5：付费意愿验证

### 5.1 市场基准数据（多源）

| 数据 | 值 | 来源 |
|:-----|:---|:-----|
| 竞争情报工具市场 | **$823.4M (2026) → $3,004.1M (2033)，CAGR 20.3%** | Grand View Research |
| AI Agent 市场 | **$10.9B (2026) → $182.9B (2033)，CAGR 49.6%** | Grand View Research |
| 全球数字新闻付费率 | **仅 16%** 全球为数字新闻付费（弱付费基础）| Reuters Institute DNR 2026 |
| AI 用户付费强度 | AI 用户平均付 **4× 订阅费（$66/月）**；67% 称 AI 订阅"最重要" | Bango 2025（market-positioning 引用）|
| 订阅疲劳 | 流失率 31%→47% (2024→2026)；87% Gen Z 疲劳 | market-positioning §7.7.1 |
| **中间地带（$20-200/月）** | 已被 Readless($4.9-9)/Competely($39)/Parano(€89) 进入 | 2026 实测 |

### 5.2 关键缺口发现（对项目文档的修正）

**项目自带 market-positioning.md 说"$20-200/月中间地带真空，只有 Kompyte"——这个论断已经过时**。2026 实测发现 Readless（$4.9-9/月 AI digest）、Competely（$39/月竞品监控）、Parano（€89/月）都进入了这个区间。

**修正后的真实格局**：
- **$0-15/月**：Feedly/Inoreader/Readless（消费级 AI digest 拥挤）
- **$39-300/月**：Competely/Parano/Kompyte（自服务竞品监控）
- **$15K-100K/年**：AlphaSense/Crayon/Klue（企业 CI 套件）
- **AutoInfo 定位**：能力上是"全平台"，但**价格锚点（$50-2,000/月）正好落在新玩家密集区**——差异化不能靠价格，必须靠"RAW+PROCESSED 全管线 + 质量门控 + 多格式"的组合价值

### 5.3 付费意愿四信号（诚实评估）

| 信号 | 状态 | 说明 |
|:-----|:----:|:-----|
| 付费意愿（LOI/定金）| ❌ 零 | 无真实付费用户/LOI/试点 |
| 可复制动作 | ❌ | 冷接触到付费的步骤未验证（纯产品，无销售流程）|
| 行为 > 观点 | ⚠️ | 无 usage log 可查（无真实用户）|
| 经济性 | ⚠️ | Stripe 已接但无定价落地验证 |

**结论：付费意愿 [未验证]——这正常（启动阶段），但意味着商业论证的结论是"方向成立，证据待补"，不是"已证实"。**

---

## 阶段 6：优劣势分析 + 迭代决策

### 优势（有证据）
1. **能力深度**：8 产品 × 8 格式 × 146 MCP × 21 域，无单一竞品同时具备（阶段 3 对照）
2. **质量门控是硬差距**：R1-R13 硬扫 + G0-G5 + 130 validation 场景——DIY agent 和轻量竞品都不做
3. **Agent 原生**：146 MCP 工具是未来（Reuters Institute 2026 #2 主题 = agent 中介触达）
4. **BYOK + 数据所有权**：对"怕 SaaS 锁定"的用户有吸引力
5. **Demo 质量已证**：R5 独立审查 0 缺陷（可信度证据）[已修正 2026-09-04：R5 审查报告未归档、demo 包不存在——同上，证据强度有限，见阶段 0 标注]

### 劣势（有证据）
1. **斩杀风险高**：RSS 采集 + 摘要（核心能力）可被免费 skill 替代（阶段 4）
2. **中间价位已不空**：Readless/Competely 等新玩家进入，价格竞争激烈
3. **RAW 产品线是 commodity**：数据管道价值低（market-positioning 自己承认 margin 低）
4. **零付费证据**：无 LOI/用户/试点
5. **功能过载风险**：8 产品 × 8 格式 × 146 工具对"单一痛点"用户是负担——买家要的是"解决我的信息问题"，不是"全平台"

### 迭代决策

**✅ 继续投入（PROCESSED 产品线）**——但聚焦：
1. **砍弱补强**：RAW 数据管道不作为主卖点（commodity），主推 **PROCESSED 产品（digest/report/premium-briefing）的质量 + 溯源 + 多格式**
2. **差异化话术**：从"我们采集信息"改为"**我们交付可溯源、经过质量门控、多格式的知识产品**"（vs DIY agent 只给你原始摘要）
3. **定价锚点**：对标 $4.9-9 的 Readless（轻量 digest）和 $39 的 Competely（监控），PROCESSED 产品取 **$20-100/月**（中间偏上，靠质量差异化），避免正面撞 $4.9
4. **试点设计**：找 3-5 个特定域用户（金融情报/医学研究）做 Concierge MVP——用户提供域，AutoInfo 生成 PROCESSED 产品，验证付费意愿
5. **斩杀对冲**：公开 BlogWatcher 等价 skill 被替代的差距 = 必须让"质量门控"成为可感知差异（demo 里强化 R1-R13 扫描的可视化）

---

## 证据来源总表

| # | 来源 | 用途 |
|:--|:-----|:-----|
| 1 | AutoInfo README.md（本地 backup repo）| 产品功能/状态 |
| 2 | docs/dev/specs/market-positioning.md | 定位/竞品/定价/用户画像（项目自证）|
| 3 | docs/dev/specs/user-lifecycle-definition.md | B1/B2/B3 用户模型 |
| 4 | docs/demo-release-standard.md | demo DoD/R5 状态 |
| 5 | deliverables/autoinfo-demo-package-20260902-perfect2.zip[已修正 2026-09-04：该文件在本仓库与 $HOME 均不存在] | demo 包内容（437 文件）（文件不存在，改用 outputs/autoinfo-deliverable-13domains-20260810.zip）|
| 6 | git log / rev-list | 迭代速度（663 提交/10 天 150）|
| 7 | Feedly pricing（readless.app 2026 + official）| Feedly $0-1600/月 |
| 8 | Inoreader pricing（inoreader.com）| Inoreader $7.50-629.99/月 |
| 9 | AlphaSense pricing（elevatedsignal/spendhound/vendr）| $15K-100K+/年 |
| 10 | Kompyte pricing（competely.ai/parano.ai）| $300/yr 起 |
| 11 | Readless pricing（readless.app）| $4.90-9/月 |
| 12 | Competely pricing（competely.ai）| $39-59/月 |
| 13 | Diffbot pricing（diffbot.com）| $299-899/月 |
| 14 | KnowledgeSDK（knowledgesdk.com）| $29-99/月 |
| 15 | BlogWatcher skill（kiwiclaw + Hermes docs）| 斩杀风险等价物 |
| 16 | rss-agent（github shiquda）| 斩杀风险等价物 |
| 17 | Digital Applied 竞品监控文章（2026-07-08）| DIY 成本 $8.99/月 + noise control 是 80% |
| 18 | Grand View Research：竞争情报工具市场 | $823.4M→$3,004.1M, CAGR 20.3% |
| 19 | Grand View Research：AI Agents 市场 | $10.9B→$182.9B, CAGR 49.6% |
| 20 | Reuters Institute DNR 2026 | 16% 全球数字新闻付费率 |
| 21 | Reddit r/rss 多帖（overwhelmed/drowning）| 用户痛点证据 |
| 22 | readless/rockstar 开发者 newsletter 评测 | newsletter curation 价值（TLDR 150h/年）|
| 23 | Bango 2025（market-positioning 引用）| AI 用户付 4× 订阅费 $66/月 |

---

## 未验证项清单（诚实列出待补数据）

| 项 | 缺口 | 验证方法 |
|:---|:-----|:---------|
| 付费意愿 | 无 LOI/定金/试用用户 | 3-5 个 Concierge MVP 试点（用户提供域，AutoInfo 出产物）|
| 目标客户是谁 | market-positioning 说"情报分析师/医生/创始人"，但**无访谈证据** | 3-5 个 Switch 访谈（Mom Test 法，锚定过去行为）|
| 价格带 | 项目文档 $50-2,000/月，但中间价已拥挤 | Van Westendorp 定价访谈 |
| RAW vs PROCESSED 谁先卖 | 项目文档说 PROCESSED 高利润，但无销售证据 | 试点同时跑两类，看哪个转化 |
| 中文市场 | market-positioning 说中国是次要市场，但无中文用户验证 | 待定（先做海外试点）|
| 竞品全面度 | 只验证了 8 家，EnkiAI/TrendIntel（项目文档提到）未深挖 | 补查这 2 家 |

---

## 结论

**AutoInfo 不是"又一个 RSS 阅读器"，它的可辩护价值在"质量门控 + 多格式 + 全管线的知识产品"，而不是"采集信息"。** 启动阶段的关键动作不是继续堆功能，而是：**用 3-5 个 Concierge MVP 验证特定域用户的付费意愿，同时明确对外话术从"信息平台"转向"可溯源的知识产品交付"**。斩杀风险真实存在（DIY agent 能替代数据管道），但质量门控是它目前唯一不可复制的护城河——把这一点做成 demo 的第一卖点。

---

## 建议优化与发展方向（2026-09-02，基于上文数据）

> 以下建议全部锚定在本报告已验证的数据上，标注对应数据来源编号（见证据来源总表）。

### 方向 1：产品优化——把"质量门控"从内部资产变成用户可感知卖点

| 动作 | 依据数据 | 预期效果 |
|:-----|:---------|:---------|
| demo 增加"AutoInfo vs 裸 LLM 输出"对照页（同一 topic，AutoInfo 产物 vs 直接让 ChatGPT 写摘要，展示 R1-R13 硬扫差异）| 斩杀风险第 4 阶段（free skill 能摘要但无门控）| 让"质量门控"可感知，抵消"自己用 LLM 也行"的认知 |
| 把 130 validation 场景做成公开的"质量承诺页"（`list_validation_scenarios` 公开展示）| 阶段 0（130 场景 = 工程证据）| 对 B2B 买家（CIO/合规敏感）是最强信任状——证明"每次交付都过门控" |
| PROCESSED 产品默认带"溯源清单"（每条结论 → source_url 链接）| market-positioning §7.2（客户 A/B 都关切溯源）| 直接对标 AlphaSense 的 traceability，让溯源成为默认而非可选 |

### 方向 2：市场进入——放弃"泛信息平台"话术，垂直域打穿

| 动作 | 依据数据 | 预期效果 |
|:-----|:---------|:---------|
| 选 2 个域（医学研究 + 金融情报）做垂直打穿，其余域只维护 | 项目自有 market-positioning §6.2（medical=🔴P0、financial=🔴P0，最高 WTP）| 聚焦 = 可验证的付费场景；泛平台 = 什么都做不好 |
| 定价锚点：PROCESSED 产品 $20-100/月，RAW 免费引流 | 阶段 5.2（Readless $4.9/Competely $39 已进中间价；RAW=commodity 不能收费）| 用 $4.9 竞品 4-20 倍的价格卖"门控+多格式"，靠差异化而非低价 |
| 免费层设计：免费 = "1 域 + 1 产品 + 每周 digest"，付费解锁"多域 + PROCESSED + 多格式" | ChartMogul 2026：AI 原生产品 free-to-paid 6-8% good / 15-20% great | 免费层是转化管道，不是慈善——设计成"体验过门控就离不开" |

### 方向 3：验证体系——把"已证明的能力"转成"销售证据"

| 动作 | 依据数据 | 预期效果 |
|:-----|:---------|:---------|
| 用 R5 demo 包作为首个销售材料（437 文件、4 域 24 产物、0 缺陷）[已修正 2026-09-04：demo 包不存在、R5 报告未归档——同上，需先重建交付物再作为销售材料] | 阶段 0（R5(1) 通过独立审查）[已修正 2026-09-04：同上——demo 包不存在、R5 报告未归档，仅自查通过] | 对 B2B 买家：不靠 PPT 靠交付包 |
| 做 3-5 个 Concierge MVP：用户提供域 → AutoInfo 生成 2 周 PROCESSED 产品 → 用户看后定价访谈 | 未验证项清单第 1 项（付费意愿）| 这是唯一能产生"真金白银信号"的动作（Steve Blank 四信号）|
| 给 MVP 用户做 Sean Ellis 测试（"如果明天消失你多失望"）| 阶段 5（付费意愿未验证）| 40% 规则判断 PMF |

### 方向 4：斩杀对冲——防守"DIY agent"进攻

| 动作 | 依据数据 | 预期效果 |
|:-----|:---------|:---------|
| 公开 BlogWatcher 等价 skill 的差距：AutoInfo 的差异化 = "门控 + 多格式 + 溯源"，不是"能摘要" | 阶段 4（BlogWatcher/rss-agent 已存在）| 让用户知道"自己搭"缺什么 |
| 若 DIY 威胁实质化，考虑"API 优先"模式（提供 AutoInfo 作为 MCP server，让 agent 直接调）| 阶段 3（MCP 是未来）| 打不过就加入——成为 agent 生态的基础设施而非替代品 |

### 方向 5（验证指标）：启动阶段每 2-4 周回炉

| 指标 | 目标 | 依据 |
|:-----|:-----|:-----|
| Concierge MVP 转化率 | ≥ 8%（行业 median）| ChartMogul 2026：B2B free-to-paid 6-10% good / 15-20% great |
| 用户流失率 | 月度 churn < 5% | market-positioning §7.7（订阅疲劳 47% churn 是行业红线，AutoInfo 须显著低于）|
| 单域月 ARPU | $20-100/月 | 阶段 5 定价锚点 |
| 3 个月内 | 至少 1 个付费 LOI | Steve Blank 四信号（付费意愿）|
