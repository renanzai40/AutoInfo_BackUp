# Demo 包质量残余风险登记表

> 目的:把"每次跑都能发现新问题"的焦虑变成可枚举、可检测、可裁决的**已知残余**。
> 原则:内容生成产品不存在"零问题"状态;生产级 = 残余可列举 + 每类有检测层 + 检测有界。
> 用法:每轮 review/单次生产暴露**新类**时,先登记到此表(现象 → 类 → 层 → 严重度),再决定是否修复。

## A. 语义残余类(LLM 随机性,无法确定性根除,靠检测+裁决)

| 类 | 典型表现 | 检测层 | 严重度 | 状态 |
|---|---|---|---|---|
| 叙事↔来源漂移 | 源信号被改名/抽象成新词("low VIX/inflation/AI spending" → "market breadth") | H1 gate(已知形态)+ L1 battery + 外部 review | P1(若混入) | 有约束+检测;新形态靠 battery/review |
| 推断措辞无 hedge | editorial 句断言市场方向/动机("the smart money is betting") | L1 battery(#191 只约束 feature_story,未盖 editorial 开场)+ 审查程序 | P2/P3 | **已登记(R6/R7 连续双样本再现);审查程序已入 skill demo-package-deliverable-review(2026-09-03);prompt 层约束已补(#210: EDITORIAL_OPENING_HEDGE_CONSTRAINT 覆盖 Editor's Note / Executive Summary / column Deep Dive 开场)** |
| 实体事实误差 | 与来源不符的数字/事实(非汇率类) | 无确定性 gate;L1 battery 部分;外部 review | P1(若混入) | 靠独立 review 兜底 |
| 主题归类/结构组织 | funding 表漏放头条条目(VAST)→ Additional Topics | 无(L0/L1 均不判组织) | P3 | 非缺陷,润色建议 |
| 金额换算轻微漂移 | 新中文金额形态(数百万/几千万/千万级)未注入,LLM 自算 | G6 抓量级错(隐含汇率越界);抓不住轻微漂移 | P2 | 已覆盖数字+中文数字形态;新形态靠 G6 部分兜底 |

## B. 确定性层(已防死或必抓,列出以证明覆盖)

| 类 | 机制 | 类型 |
|---|---|---|
| 词级截断 | `_truncate_ellipsis` + H2 | 防 + 抓 |
| 列表粘连 | 模板 trim_blocks 修复 + H3 | 防 + 抓 |
| 占位/空壳/日志泄漏 | F1-F4 / C2 / C3 | 抓 |
| USD 汇率(数字+中文数字) | `_annotate_rmb_usd` + `_RMB_TEXTUAL_RE` + G6 | 防 + 抓 |
| 404 URL 伪造 | prompt 逐字约束 + `_sanitize_report_urls` | 防(结构上不进产物) |
| 假条目/引用完整性/长文 grounding | C1 / C5 / C6 | 抓 |

## C. 工具层残余(影响检测能力,非内容缺陷)

| 类 | 表现 | 影响 |
|---|---|---|
| battery LLM 格式失败 | ~13/40 条目 ESCALATE "no parseable verdict block" | L1 覆盖不全;fail-loud 正确(绝不静默 PASS) |
| gate 良性误报 | H1 常见词(month/backing)、H2 源标签(npr-news)、包根 C3 | 每次需人工裁决;是保守设计不是 bug |
| presentation LLM 合成失败 | 连续空 slides → KB-derived 兜底(确定性输出) | 产物有效但非 LLM 合成;#220 已知 |

## D. 系统变化触发的新表面(这是"新问题"的真实来源,不是"问题无穷")

| 变化 | 后果 | 对策 |
|---|---|---|
| 新功能 | 新代码面有覆盖缺口(#203 引入 $0.14M) | 新功能自带 QC 测试 + gate 断言 |
| 换模型 | 失败模式分布整体变化,规则需重推 | 换模型后重跑单次生产样本 |
| 修复引入回归 | 重生成可能带新问题(#207 的 404) | 修复必有测试 + 重生成后全 QC |

---

**判断"新问题"的口径**:先查登记表——
- 已在表中 = 已知类的再现,按对应检测层处理(通常可裁决或低成本修),**不算新发现**
- 不在表中 = 真新类,先登记再修(登记本身就把未知未知变成已知已知)
