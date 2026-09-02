# AutoInfo Validation 治理规范

> 2026-08-15 定稿。跨项目通用规范见全局 skill `validation-framework-execution` → `references/validation-run-governance.md`；本文是 AutoInfo 落地版（路径、命令、责任人）。

## 1. 循环契约（Loop Contract）

### 1.1 每次循环开始前（输入，必读）

| # | 输入 | 位置 | 用途 |
|---|------|------|------|
| 1 | validation-scenario-contract.md | `docs/dev/validation-scenario-contract.md` | 场景编写 + agent-tester 执行标准 |
| 2 | **坑清单（LOOP-LOG）** | **`docs/dev/validation-loop-log.md`** | 迭代前逐条核对，避免重踩 |
| 3 | 上次 run 记录 | `validation-runs/latest` + `scenarios.json` | 基线对比 |
| 4 | coverage baseline | `validation-runs/coverage/`（如有）| 判定基准 |
| 5 | 交付历史 | `04-Output/artifacts/deliverables/AutoInfo/` | 对比交付演进 |

### 1.2 每次循环结束后（输出，必形成）

| # | 输出 | 位置 | 说明 |
|---|------|------|------|
| 1 | run 记录 | `validation-runs/<ts>/`（gitignore）| 引擎自动（scenarios.json + artifacts）|
| 2 | **坑清单更新** | `docs/dev/validation-loop-log.md`（当天追加）| 新坑当天记；循环前必读 |
| 3 | issue + PR | GitHub | 代码层 bug：issue → 修复 → PR（带回归场景或 N/A）|
| 4 | validation 报告 | 汇报给 director | 结果分布 + failed 定性 + 修复验证 + 基线对比 + 遗留 |
| 5 | 交付包（正式交付）| `04-Output/artifacts/deliverables/AutoInfo/` | zip + manifest |

## 2. 失败定性协议

任何 failed 场景在报"回归"前**必须单独复现定性**：

| 类别 | 判定 | 处理 |
|------|------|------|
| LLM 时段波动 | 单独复跑 passed；log 大量 `Failed to parse` | 无需修；稳定时段重跑 |
| 场景断言漂移 | 代码行为变了、场景断言过时（#242 先例）| **改场景**，不改产品 |
| 代码 bug | 单独复跑仍 failed + 可定位 file:line | issue + 修复 PR |
| 数据/状态漂移 | 测试数据残留、gate 配置污染 | 清理/重建，记录 provenance |
| 环境 | 网络/key/端点不可达 | 记录 unconfigured/env-noise |

**并发失败**：并发下 failed、单独 passed = 并发放大器（降并发）；单独也 failed = 真问题。

## 3. LLM 稳定性门禁

- 全量跑前短探测：`llm-gated` 单场景 <60s passed 即稳定（坑 #14）
- 波动时段结果**不参与回归判定**
- output-gen 场景并发 ≤2（semaphore 2，readonly 4）

## 4. 归档映射

| 层 | 去处 |
|----|------|
| 代码/场景/文档 | repo 内（版本化）|
| run 记录 | `validation-runs/`（gitignore）|
| 坑清单 | `docs/dev/validation-loop-log.md`（版本化）|
| 交付包 | `04-Output/artifacts/deliverables/AutoInfo/` |
| 中间件/log/临时脚本 | `99-Tools/validation-scratch/AutoInfo/`（**不是 /tmp**）|

## 5. 报告模板

```markdown
## Validation 报告 — AutoInfo @ <commit sha>
### 结果分布
| Run | 时间 | passed | failed | unconfigured | 总场景 |
### Failed 明细（含定性）
| 场景 | 单独复跑 | 定性 | 修复/issue |
### 修复验证（本循环）
| 修复 | 验证证据 | 状态 |
### 基线对比（vs 上次）
| 变化 | 说明 |
### 遗留问题
```

## 6. 交付物审查协议

验收 = **打开产物审查**（digest 条目相关性、summary 非空、无 EMPTY/VAGUE、真实文件），不是 matrix 数字。
详见全局 skill `references/enduser-content-review.md`。

### 6.1 质量门禁脚本（issue #188）

对一批产物 md 文件做全维度机器门禁检查，作为交付物审查的第一道自动关卡：

```bash
# 对单个产物目录做全维度检查；exit 0 = 干净，exit 1 = 有缺陷，exit 2 = 用法/IO 错误
python3 scripts/quality_gate.py outputs/<domain>
python3 scripts/quality_gate.py outputs/<domain> --cjk-exempt-domains english-learning   # 双语豁免
python3 scripts/quality_gate.py outputs/<domain> --forbidden-words "horse,cervical cancer"  # 域禁用词 (F4)
python3 scripts/quality_gate.py outputs/<domain> --domain-blocklist "medical-research:NICE,cervical cancer"
python3 scripts/quality_gate.py outputs/<domain> --json   # 机器可读摘要
```

覆盖的规则（规则 id 与 issue #188 一致）：

| 层 | 规则 | 检查 |
|----|------|------|
| 格式 | F1 | 空壳（<500B）|
| 格式 | F2 | 占位符（TODO/PLACEHOLDER/TBD/待补/占位/`{{`）|
| 格式 | F3 | 双引用（同一 source 连续重复；一题多源合法不误报）|
| 格式 | F4 | 禁用词（域相关，可配置 `--forbidden-words` / `--domain-blocklist`）|
| 内容 | C1 | 合成伪条目（占位模板标题「金融市场情报 N」/「AI 商业周报 N」/ weekly: 等）|
| 内容 | C2 | 日志泄漏（LiteLLM / Give Feedback / litellm._turn_on_debug / ANSI / 栈 trace）|
| 内容 | C3 | CJK 残留（非双语产物含中文，阈值可配；`*-learning` 双语域豁免）|
| 内容 | C4 | 截断（80-250 字符行无结尾标点；区分完整句/元数据/页脚）|
| 内容 | C5 | 来源完整性（References 与正文引用可对齐；仅 report/*-briefing 要求 References 段）|
| 跨产物 | X1 | 实体一致性（简单版：同实体 copular 身份描述跨产物冲突标记；复杂 LLM 判定版后续）|

说明：C3 的默认双语豁免域为 `*-learning`（与 output 层 `_CJK_EXEMPT_DOMAINS` 一致）。
issue #188 原始描述建议 ai-commercial 也豁免，但 #181/#186 已落地设计将 ai-commercial
的 CJK 视为缺陷（36kr 泄漏进英文产物），故门禁以代码库现状为准，可用
`--cjk-exempt-domains` 覆盖。

人工审查在机器门禁通过后进行（机器保证无已知缺陷类别，人保证相关性/价值判断）。
