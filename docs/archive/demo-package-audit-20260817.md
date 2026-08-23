# Demo Package 产物审查报告(2026-08-17,交付前 assistant 初审)

## 审查范围
24 个产物(3 域 × 8 种),247 条 raw。方法:自动化扫描(结构/长度/来源/幻觉信号)+ 代表性产物深读 + 数据链路核对。

## 总体结论

**通过初审,可提交终审。** 三个域产物内容质量达标(有实质分析、断言可溯源、无严重幻觉),交付包结构完整。审查中发现并修复 4 类问题(见下)。

## 质量评分(1-5)

| 域 | digest | report | tutorial | presentation | premium-briefing | magazine-digest | column | enterprise-briefing |
|----|--------|--------|----------|--------------|-------------------|-----------------|--------|---------------------|
| medical-research | 4 | 4 | 4 | 4 | 4 | 4 | 3 | 4 |
| ai-commercial | 4 | 4 | 4 | 4 | 4 | 4 | 3 | 4 |
| financial-intelligence | 4 | 4 | 4 | 4 | 4 | 4 | 3 | 4 |

(评分标准:4=良好,内容实质+可溯源;3=合格,篇幅较短但无缺陷;column 因篇幅最短评 3,非缺陷)

## 修复的问题(审查中发现,已处理)

### 1. 幻觉年份:"July 2023"(9 处)
- 现象:financial 6 个产物中,中国 7 月经济数据被 LLM 写成 "July 2023"(实际 2026)
- 处理:全部修正为 "July 2026"(sed 替换 9 处)
- 根因:LLM 生成摘要时日期上下文漂移——见 issue 候选 B/D

### 2. 促销噪声条目混入(1 条)
- 现象:financial report 曾含 "Amazon Bluetooth headphones" 促销条目(TheStreet deals 分类)
- 处理:从 KB entries 删除 + 重新生成产物,已无残留
- 根因:deals 分类条目被关键词命中留下(见 issue 候选 B)

### 3. 诊断日志污染产物文件(10/24 文件)
- 现象:LiteLLM warning / "Failed to parse" / "LLM returned None content" 等错误行混入产物 md 文件头部
- 处理:sed 清理全部 24 文件,0 残留
- 根因:CLI stdout 与 LLM 日志未隔离(见 issue 候选 A)

### 4. 空 summary 条目(14 行 → 4 行)
- 现象:report 表格 14 行 summary 为空(提纯失败条目 + SEC 元数据)
- 处理:10 条有 content 的补生成 summary(9 条成功,1 条手工写),2 条无 content 的从 KB 删除
- 剩余 4 条为 SEC 8-K/10-Q 元数据(本身无正文,产物显示"metadata"行,可接受)
- 根因:产物生成不过滤空 summary(见 issue 候选 B)

## 溯源验证

| 产物 | URL 数 | 可溯源率 |
|------|--------|---------|
| medical digest | 25 | 25/25 (100%) |
| medical report | 176 | 159/176 (90%) |
| ai digest | 22 | 22/22 (100%) |
| ai report | 120 | 98/120 (82%) |
| financial digest | 42 | 40/42 (95%) |
| financial report | 117 | 88/117 (75%) |

(不可溯源部分多为 report 里对多条目归纳的 Executive Summary 段,内容正确但未逐句带 URL;关键断言均带 Source 链接)

## 遗留观察(不影响交付)

1. **presentation/tutorial 无内嵌 URL**(0 来源链接)——但内容有实质分析(数据点正确),格式上可不带链接
2. **SEC 元数据 4 条**在 report 表格里 summary 显示为行内 metadata 文本(非空,可读)
3. **column 篇幅最短**(2.3-4.3KB)——付费专栏应有更深度内容,建议后续补长文模板
4. 部分 report 的 Executive Summary 无逐句 URL(report 是归纳性文体,可接受)

## 终审建议重点
1. 抽查 2-3 个产物全文(建议 financial report + medical digest + ai-commercial report)
2. 确认 SEC 元数据行的观感可接受
3. 是否接受 presentation/tutorial 无链接(内容实质 OK)
4. 如需 column 更深度,可后续增强模板
