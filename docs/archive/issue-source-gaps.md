## 问题
2026-08-11 final matrix（produced=338 / gap=0 / not-applicable=390）中，产物层 gap=0 已达标，但**采集层仍有两个缺口**：
- source_gaps = 9：某些 domain 缺特定 source platform 的原始数据
- kb_tier_gaps = 2：KB 数据层级缺口

## 现状
- 这两个缺口只出现在 matrix 报告（validation-deliveries/2026-08-11/final-matrix-report-100pct.md）中
- **没有独立的追踪 issue**，容易在后续验收中被遗忘

## 建议
- 列出具体是哪些 domain × source 缺数据（跑 coverage_matrix 的 gap 明细，落代码/配置层修复采集）
- 评估是否影响 end-user 付费交付（哪些 domain 的付费用户会缺这些 source）

关联：2026-08-11 validation rerun 收尾时发现
