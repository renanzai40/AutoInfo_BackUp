<!-- doc-type: adr -->
# 0007. release-please 版本真值：以 manifest + `_version.py` 为准，tag 仅反映已发布版本

- **Status**: Accepted
- **Date**: 2026-08-15
- **Author**: Hermes Agent (human-reviewed)

## Context

AutoInfo 用 release-please（`release-type: python`）自动发布。2026-08-15 发布流程暴露出一个版本治理缺陷：

- `src/autoinfo/_version.py` 和 `.release-please-manifest.json` 都是 `1.8.1`（运行时真值，MCP/REST 的 `version` 字段读 `_version.py`）。
- 但 git 上存在一个手工打的 `v0.9.0` tag（"pre-V1 baseline" 快照，2026-08-13，无 GitHub Release，指向的 commit 代码已是 1.8.1）。
- release-please 以 **git tag 为版本发现基准**，找到 `v0.9.0` 后把"当前版本"当作 0.9.0，推出下一个版本 **0.10.0** —— 合并会把 manifest 从 1.8.1 **降级**到 0.10.0，与 `_version.py`、CHANGELOG v1.10 全部冲突。

进一步发现（发布后验证）：release-please 的 python 策略对 `pyproject.toml` 的 `dynamic = ["version"]` 会打日志 `dynamic version found … Skipping update`，**不更新 `_version.py`**（其内置 `PythonFileWithVersion` updater 只自动匹配 `<pkg>/__init__.py` 和文件名为 `version.py` 的文件，`_version.py` 不匹配）。结果：即使版本正确，运行时 `_version.py` 也会与已发布版本漂移。

## Decision

1. **版本真值 = manifest + `_version.py`**。git tag 只允许反映"已经过 release-please 发布的版本"，不再作为版本发现的唯一依据。
2. **禁止手工打版本 tag**（尤其不得打低于 manifest 当前版本的 tag）。需要 baseline 快照用普通 commit/分支，不要用 `vX.Y.Z` 命名。
3. **`_version.py` 必须与 manifest 同步**：在 `release-please-config.json` 的 `packages["."].extra-files` 中声明 `src/autoinfo/_version.py`（`type: generic`），版本行加 `# x-release-please-version` 注解，release-please 每次发布自动更新。
4. **`workflow_dispatch` + `release-as` 输入**作为版本修复的逃生舱：tag 错乱时可手动锁目标版本（如 `release-as: 1.9.0`），无需改 git 历史。
5. **修复动作（2026-08-15 执行）**：删除 `v0.9.0` tag（无 release、无引用、commit 可达）；用 `release-as: 1.9.0` 发布 v1.9.0；把 `_version.py` 同步到 1.9.0 并加注解。

## Alternatives considered

- **删除旧 tag 后让 release-please 自动推算**：删 tag 后 release-please 找不到任何 release 标记，会按"首次发布"推 0.1.0（实测 `No version for path .` → 0.1.0）。单独删 tag 不够，必须配合 `release-as` 显式指定目标版本。
- **重打 `v1.8.1` tag**：会再制造一个"从未经 release-please 发布"的假 tag，且 `v0.9.0` 仍残留，tag 历史更混乱；无法根治"手工 tag 误导版本发现"的根因。
- **仅用 `release-as` 而不删 tag**：单次覆盖有效，但不修根因——下次 main push 时 release-please 仍会以 `v0.9.0` 为准重新生成错误发布 PR（实测 0.10.0 重复出现）。删 tag（清根因）+ `release-as`（锁目标）必须组合。
- **重命名 `_version.py` → `version.py`**（触发内置 updater，零配置）：要改 `pyproject.toml` 的 `attr` 引用、`__init__.py` 的 import、可能的测试引用，改动面大于加 `extra-files` + 行注解；且 `type: generic` + 注解是 release-please 官方文档路径。

## Consequences

- 未来 release-please 每次发布会同步更新 `_version.py`（行注解由 generic updater 识别），运行时版本与 manifest 保持锁定。
- tag 错乱时可通过 `workflow_dispatch` + `release-as` 手动修正，无需改 git 历史。
- **注意**：`_version.py` 的 `# x-release-please-version` 注解是功能性标记，**不得删除**（generic updater 只更新带注解的行）。
- **注意**：任何人不得手工创建 `v*` tag；如需快照用普通分支。
- 发布流程观测点：每次 main push 后 Release workflow 若开出发布 PR，其 `_version.py` 变更行必须与 manifest 同步变更；若只有 manifest 变而 `_version.py` 不变，说明 extra-files 配置回退，需按本 ADR 修复。
