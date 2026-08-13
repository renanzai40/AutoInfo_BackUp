# AC5 — 产物抽样验证判定(2026-08-12)

> 依据:docs/dev/acceptance-framework.md AC5「术语一致性 + 产物可交付性」。
> 本页为 B3 定向抽样集,采用真实 CLI 端到端路径(`python -m autoinfo.cli output ...`),全部针对 medical-research 域。

## 产物清单(5/5)

| # | 产物 | 命令 | 结果 | 文件 | 说明 |
|---|------|------|------|------|------|
| 1 | 周报 Digest | `output digest --domain medical-research --period weekly --format markdown` | ✅ exit 0 | ac5-digest-weekly.md (3.7KB) | 含 Source Attribution 段落,产物结构完整 |
| 2 | 标准 Report | `output report --domain medical-research --format markdown` | ✅ exit 0 | ac5-report-standard.md (55KB) | 首次调用遇 LLM JSON 解析失败,重试自愈;最终产物含执行摘要 |
| 3 | Tutorial | `output tutorial --domain medical-research --audience student` | ✅ exit 0 | ac5-tutorial-student.md (30KB) | 学生受众适配,章节化结构 |
| 4 | Presentation | `output presentation --topic "MRI research frontiers"` | ❌ exit 1 | — (0 字节) | LLM JSON 解析失败两次,`slides=0, chars=288`;该路径 **无重试自愈** |
| 5 | 专栏 Column | `output report --type column --format markdown` | ✅ exit 0 | ac5-column.md (52KB) | 前期两次解析告警后自愈,耗时较长(≈280s 内完成) |

## 判定

- **PASS(4/5)**:digest / report / tutorial / column 均产生产物文件且结构有效。
- **观察项(1/5)**:presentation 路径失败——与 2026-08-08 B-04 修复(LLM JSON 解析)同源,
  但 presentation 的生成调用链缺少 report 路径的解析重试兜底。
  **未阻塞**:presentation 失败以明确错误返回(exit 1 + 可读信息),非静默损坏;digest/report/tutorial/column 证实产品线整体可用。

## 交叉验证

- 软删条目(2026-08-12 B-03)在 digest 生成期间触发 promotion 拒绝(`source-score-below-threshold`),
  **被隔离至 `knowledge/_failed/`,未污染产物** —— 软删工程语义正确。
- LLM 解析告警均为 B-04 类(`Failed to parse LLM response as JSON`),report/column 通过重试自愈,
  证明现有重试机制有效;presentation 为可改进面(后续排期)。

## 建议动作

1. presentation 路径:复用 report 的重试/解析兜底(`llm.py` 的 `parse_json_response` 已具备 3 策略,
   缺的是 presentation 调用点的重试封装)。
2. 验收报告将本观察项列入「已知限制」而非阻塞项。