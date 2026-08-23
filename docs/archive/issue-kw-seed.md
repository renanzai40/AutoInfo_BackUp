## 问题
keyword-management 场景引用的预置关键词不存在（multicenter / time-lapse embryo imaging）。

## 证据
- `grep -rn "multicenter\|time-lapse" src/autoinfo/data/ configs/` → 无结果
- 各 domain 的 _keywords.yaml（knowledge/<domain>/_keywords.yaml）中均无这些关键词
- 相关 validation scenario（keyword-management）因 seed 缺失失败

## 影响
- validation 场景 keyword-management 无法通过（数据层缺 seed）
- 该场景本应验证关键词管理的确定性分组，现因数据缺失无法验证

## 建议
- 若场景引用错误 → 修正 scenario 引用（代码/配置层修复）
- 若确需这些关键词 → 在 seed 数据中补充 multicenter / time-lapse embryo imaging 预置关键词
- 修复必须落代码/配置层，不只是改产物

关联：2026-08-11 validation rerun 发现的 5 个 failed scenario 之一（数据类）
