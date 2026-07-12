# Token Firewall Runtime Pilot 结果

> 本页保留 2026-07-11 的原始两任务方向性 Pilot。后续 12 组 Terra 配对扩展实验已达到冻结样本/覆盖门槛，节省 70.79% 的 Sol Token，并在未观察到交付质量下降的情况下通过非劣效门禁；参见 [扩展实验报告](labs/terra-route-n12-001/report/evaluation-report.md) 与 [方法说明](../docs/evaluation.md)。M3 与 Claude 的结论仍仅限本页的 `n=2` Pilot。

日期：2026-07-11
状态：工程闭环完成；统计证据仍不足以作发布级非劣效声明。

## 实验范围

- 两个冻结任务：low 风险 ASCII 标签规范化、high 风险 HS256 认证边界加固。
- 四条路线：D（Sol 直接实现）、A（M3 实现/验证，必要时 B 组 Terra 返工复核）、C（Terra 实现/验证）、E（Claude Sonnet 实现/验证）；所有可进入终审的候选都由新的 Sol Session 匿名盲审。
- Acceptance Spec 均包含正例、反例和语义边界；隐藏测试只在同一任务全部模型阶段结束后运行。
- 失败、格式错误、超时和返工全部保留；Token 按 Session ID 去重。模型调用前的零 Token 失败也保留在来源链中。

## 单任务结果

| 风险 | 路线 | 任务成功 | Sol Token | 相对 D 节省 | 全模型 accounted Token | 结论 |
|---|---:|---:|---:|---:|---:|---|
| low | D / Sol 直做 | 是 | 271,282 | — | 271,282 | Public、Sol Review、Hidden 均通过 |
| low | A+B / M3 Loop | 是 | 141,741 | 47.75% | 2,623,670 | A 被 Sol 找出 2 个高风险错误；精细化 r2 合同后 B 修复并通过 |
| low | C / Terra | 是 | 70,128 | 74.15% | 346,285 | 一次通过；实现先校验原始 ASCII，再规范化 |
| low | E / Claude Sonnet | 否 | 0 | 不适用 | 782,897 | Worker 产生同类边界错误，Claude Verifier 正确拒绝；未唤醒 Sol |
| high | D / Sol 直做 | 是 | 327,643 | — | 327,643 | Public、Sol Review、Hidden 均通过 |
| high | A / M3 | 是 | 100,908 | 69.20% | 1,304,841 | 明确安全合同下首次实现即通过；快照恢复吸收 CLI 升级故障 |
| high | C / Terra | 是 | 72,184 | 77.97% | 375,286 | 一次通过 |
| high | E / Claude Sonnet | 否 | 0 | 不适用 | 790,011 | 一次被运行时目录权限阻断，一次实现后结构化输出重试耗尽 |

`accounted Token` 使用跨 Runtime 的 gross input + output 口径并包含 cache read；它适合审计上下文负担，不等同于供应商 native billing Token。本项目的优化目标是昂贵的 Sol Token，因此 cheap-model Token 不作为主要成本门槛。

## 路线级 Evaluation Lab

主分析包含同一冻结任务的所有失败尝试。每条路线当前只有 2 个 Pair，低于冻结协议要求的 12 个 Pair，且尚未覆盖 medium 风险和 feature/refactor/integration 类型，所以发布结论均为 `INSUFFICIENT_SAMPLE`。

| 路线 | 成功率（D→实验） | 累计 Sol 节省 | 用量完整 | 当前 Pilot 门禁 |
|---|---:|---:|---:|---:|
| M3 | 100% → 100% | 59.49% | 否 | FAIL（低于 70% 目标；low Control 有一次超时未知用量） |
| Terra | 100% → 100% | 76.24% | 否 | FAIL（仅因 low Control 超时用量不完整） |
| Claude Sonnet | 100% → 0% | 100%（不可解释） | 否 | FAIL（质量/Runtime 可靠性失败） |

模型阶段敏感性分析排除 low Control 的超时 Reviewer 后：Terra 保持 100% 任务成功、76.24% Sol 节省且用量完整，方向性 Pilot 门禁为 PASS；M3 仍因 59.49% 节省低于目标而 FAIL；Claude 仍 FAIL。敏感性分析不能替代主分析。

- [M3 模型阶段敏感性报告](labs/m3-route-model-only-001/report/evaluation-report.md)
- [Terra 模型阶段敏感性报告](labs/terra-route-model-only-001/report/evaluation-report.md)
- [Claude 模型阶段敏感性报告](labs/claude-route-model-only-001/report/evaluation-report.md)
- [Terra 质量—Token 图](labs/terra-route-model-only-001/report/quality-token-pareto.svg)

## 观察与路由结论

1. 当前默认便宜路线应为 Terra Worker + fresh Terra Verifier + Sol Reviewer。它在两个风险层均一次通过，并给出最高的可解释 Sol 节省。
2. M3 适合机械且合同非常明确的任务。high 安全任务因边界写得完整而一次成功；low 合同对单段标签和“先校验再 Unicode 变换”不够明确，M3 Worker 与 M3 Verifier同时漏判，返工后的第二次 Sol Review 把累计节省压到 47.75%。
3. Sol 必须保留最终决策权。low A 的隐藏测试也通过，但 Sol 仍找出两个真实高风险语义错误，说明隐藏测试不能替代语义审查，也暴露了数据集覆盖缺口。
4. Claude Code Adapter 已打通真实 Claude Sonnet、模型身份核验、结构化输出、Token/成本回收和 macOS 写边界；但当前两项任务均未形成可接受候选，不应作为默认路线。
5. 外部 Runtime 必须失败关闭。Mavis 当前配置为 `bypassPermissions` 且新版升级后移除了旧 CLI，因此生产派发默认拒绝；本次仅在一次性 Pilot 仓库显式使用 unsafe override。Claude 仅允许写 Worker workspace、Stage artifact、私有 tmp 和 `~/.claude/session-env`。

## Hardening 证据

- 15 个成功或关键失败 Run（含两次隔离 M3 smoke 和一次安装版 Skill 前向 smoke）已生成逐文件 SHA-256 的 ZIP 快照并全部重新验证。
- MiniMax CLI 在运行中升级消失后，M3 Verifier 从不可变消息/用量快照恢复；只有在原 Review Packet、原 Patch 和当前 `base..HEAD` Patch 的 SHA-256 全部相同时，才允许 Commit-ID 重映射。
- 安装前向 smoke 通过 Claude Code 外壳调用实际 `MiniMax-M3[1M]`，macOS sandbox 仅放行 workspace、Stage artifact、`~/.claude/session-env` 和 `/private/tmp/claude-<uid>`；冻结交付恢复后由 Broker 独立重跑 acceptance tests，最终达到 `REVIEW_READY`。
- 安装目录 `~/.codex/skills/token-firewall-team/` 本身又执行了一次零新增模型回合的 frozen-patch 前向测试，生成 Delivery Manifest 与 Review Packet 并达到 `REVIEW_READY`。
- 故障注入覆盖截断 JSONL、事件 ID 冲突、SQLite 查询索引删除重建、Payload 篡改、Archive 腐坏、Symlink 逃逸和 Codex Timeout Session 恢复。
- `worktree` 使用 `git clone --no-hardlinks --no-checkout`；Worker 无法写 `.git` 时由 Broker 在范围/测试门禁之后提交。

## 证据边界

这些结果支持“架构可运行，Terra 路线值得继续扩样”，不支持“已经证明所有任务质量非劣”。下一次发布级判定必须继续沿用冻结门槛，累积至少 12 个 Pair、补齐 medium 风险与四类任务，并保持失败/返工全量会计。
