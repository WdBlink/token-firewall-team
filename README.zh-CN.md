<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/logo-light.svg">
    <img alt="Token Firewall" src=".github/logo-light.svg" width="520">
  </picture>

  <p><strong>12 任务实验中，昂贵编程模型 Token 减少 70.79%，同时不把质量控制交给便宜模型。</strong></p>
  <p>Codex 按任务为原生 Agent 路由模型，强推理模型只评审由 Git 和测试支撑的紧凑交付。</p>
  <p><a href="README.md">English</a> | <strong>中文</strong></p>
</div>

<div align="center">

[![License: MIT][license-shield]][license-url]
[![Release][release-shield]][release-url]
[![Tests][tests-shield]][tests-url]
[![Agent Skills][skills-shield]][skills-url]
[![Python][python-shield]][python-url]

</div>

<div align="center">
  <a href="#quick-start">快速开始</a> &middot;
  <a href="#why-token-firewall">为什么</a> &middot;
  <a href="#experimental-evidence">实验依据</a> &middot;
  <a href="#how-it-works">工作原理</a> &middot;
  <a href="#current-limits">当前限制</a> &middot;
  <a href="docs/evaluation.md">实验详情</a>
</div>

> **主要实验结果：** 在一项冻结的 12 任务 Terra 实现、Sol 评审研究中，昂贵 Sol Token 从 **3,599,108** 降至 **1,051,353**，减少 **70.79%**；任务成功率为 **91.67%**，Sol 直接实现对照组为 **83.33%**。本研究中**未观察到交付质量下降**。
>
> 这是受路线和数据集约束的结论，不能证明其他仓库、模型版本、编程语言或任务分布也会得到相同结果。

<a id="quick-start"></a>

## 快速开始

### 安装

全局安装 Skill：

```bash
npx skills add WdBlink/token-firewall-team -g
```

### 选择操作

告诉 Codex 你需要的结果：

```text
“使用 token-firewall-team 实现这个 Issue”  —— Codex 原生委派、Git/测试门禁和强模型终审
“将这条路线与 Sol 直接实现进行基准对比” —— 配对质量、用量与 Token 节省证据
“这次 Worker 使用 Claude”               —— 明确选择第三方 CLI Adapter
```

## 使用示例

一次代码改动可以这样调用：

```text
使用 token-firewall-team 完成这个改动。默认使用 Codex 原生 Agent：读密集和边界清晰的常规任务优先 Terra，语义歧义或高风险任务使用 GPT-5.6，并保留 Git/测试门禁与独立终审。除非我明确指定第三方平台，否则不要调用外部 CLI。
```

<a id="why-token-firewall"></a>

## 为什么需要 Token Firewall

如果最强编程模型把大部分时间花在读文件、跑测试和编写常规改动上，它的上下文预算就被执行工作占用，而不是用于高价值判断。Token Firewall 适合能够说清“什么算完成”、希望 Codex 按任务分配原生模型，同时保留强最终评审的团队。

## 你将获得什么

- **降低前沿模型开销。** 读密集与边界清晰的常规任务优先原生 Terra，语义歧义和高风险判断保留给 GPT-5.6。
- **更安全的委派。** 在实现前冻结正例、反例和明确的语义边界。
- **先验证据，再接受交付。** 只有 Git 真值 Patch、批准的测试和全新 Verifier 都通过，交付才进入终审。
- **低噪声观察原生进度。** 复用 Codex 的 Agent 状态与等待机制，不持续转发 Worker 完整终端。
- **用同一套实验同时衡量质量与节省。** 失败尝试、返工、隐藏检查、模型身份和原生用量都保留在配对评估中。
- **外部平台必须显式授权。** Claude、MiniMax、OpenCode 等 CLI Adapter 只有在用户明确指定相应第三方平台时才运行。

<a id="experimental-evidence"></a>

## 实验依据

主要实验将 Sol 直接实现与历史上的外部 Terra 实现、Sol 评审路线放在同一套冻结的 12 任务配对测试中比较。任务覆盖 feature、bug-fix、refactor 和 integration，以及低、中、高风险；只有公开与隐藏检查、有界评审、范围检查和完整用量证据全部通过，任务才算成功。该证据支持“按任务分层路由”的方向，但不会把外部 Runtime 变成运行默认值；当前默认控制面是 Codex 原生 Agent。

<div align="center">
  <img alt="12 组配对任务逐任务交付质量与昂贵 Sol Token 对照" src=".github/assets/terra-n12-task-comparison.svg" width="960">
</div>

| 被评估路线 | 任务成功率 | 平均质量分 | 昂贵 Sol Token |
|---|---:|---:|---:|
| Sol 直接实现 | 83.33%（10/12） | 94.58 | 3,599,108 |
| Terra 实现、Sol 评审 | 91.67%（11/12） | 96.67 | **1,051,353（−70.79%）** |

该路线通过了预先冻结的 5 个百分点配对非劣效门槛：配对 95% 区间为 **[0, 25]** 个百分点，高于冻结的 −5 个百分点边界。因此，这项研究支持一个有边界的结论：**昂贵模型 Token 减少 70.79%，且本研究中未观察到交付质量下降。** 表中更高的点估计只是如实报告的观察值，不用于声称该架构能够提高质量。

这一结果不能保证评审质量或节省效果会在被评估的 Terra 实现、Sol 评审路线及冻结任务集之外成立。其他路线仍只是方向性研究，不能用来支持这一结论。

→ [阅读方法、披露、局限与复现说明](docs/evaluation.md) · [了解评估框架与 Inspect AI 的角色](docs/evaluation-framework.md) · [查看冻结 Lab](evidence/labs/terra-route-n12-001/report/evaluation-report.md)

<a id="when-it-fits"></a>

## 适用场景

当编程任务有清晰的验收证据、实现上下文较大，并且你希望最强模型负责最终判断而不是消耗整个任务的实现预算时，适合使用 Token Firewall。

不要用它弥补含糊的需求，也不要在未经批准时自动执行不可逆的生产操作，更不能把一项研究外推为普遍的质量保证。关键迁移、破坏性工作和无法消除的高歧义任务，应交给获准使用的最强实现模型，并设置明确的人工边界。

<a id="compatibility"></a>

## 兼容性

| 能力 | 所需环境 | 是否必需 |
|---|---|---:|
| 安装并调用 Skill | 支持 [Agent Skills](https://agentskills.io) 的 Codex | 是 |
| 原生 Agent 路由 | Codex 原生子 Agent 与可用模型配置/宿主自动路由 | 默认 |
| 第三方路线 | 用户明确指定并安装相应 Claude、MiniMax 或 OpenCode CLI | 可选 |
| 协议验证与 Evaluation Lab | Python 3.10+ | 是 |

路线预检、Runtime 命令和运行边界见 [Runtime Runbook](skills/token-firewall-team/references/runbook.md) 与[架构概览](docs/architecture.md)。

<a id="how-it-works"></a>

## 工作原理

```text
明确的验收合同
    → Codex 原生角色/模型路由
    → Git 范围检查 + 确定性测试 + 全新 Verifier
    → 交给最强终审模型的紧凑匿名证据包
```

Worker 始终只负责提出候选方案；Git、批准的验证命令、全新 Verifier 和最终评审者共同决定是否接受交付。

<a id="current-limits"></a>

## 当前限制

- 主要结果仍来自一个冻结的合成 Python 任务集和一组 Terra/Sol 配置；仍需真实仓库和跨语言复现。
- 当前 native-first 运行策略仍需要自己的真实仓库和分模型复现，不能把 12 任务外部 Terra 结果直接当作证明。
- Claude Code、MiniMax Code 与 OpenCode 是显式选择的可选通道，具有各自的模型身份和隔离要求，永远不会成为自动 fallback。

## 一起塑造路线图

下一步证据重点包括真实仓库实验、12+ 任务的 M3 路线复现、受认可的外部 Benchmark，以及模型版本漂移追踪。**Star 或 Watch 本仓库即可跟进每一份新路线报告**，也欢迎通过 [CONTRIBUTING.md](CONTRIBUTING.md) 帮助确定优先级或参与贡献。

## 开源协议

[MIT](LICENSE) © 2026 WdBlink。

---

Forged with [Skill Forge](https://github.com/motiful/skill-forge) · Crafted with [Readme Craft](https://github.com/motiful/readme-craft)

[license-shield]: https://img.shields.io/github/license/WdBlink/token-firewall-team.svg?style=flat-square
[license-url]: LICENSE
[release-shield]: https://img.shields.io/github/v/release/WdBlink/token-firewall-team?style=flat-square
[release-url]: https://github.com/WdBlink/token-firewall-team/releases
[tests-shield]: https://img.shields.io/github/actions/workflow/status/WdBlink/token-firewall-team/tests.yml?branch=main&style=flat-square&label=tests
[tests-url]: https://github.com/WdBlink/token-firewall-team/actions/workflows/tests.yml
[skills-shield]: https://img.shields.io/badge/Agent%20Skills-compatible-7F56D9?style=flat-square
[skills-url]: https://agentskills.io
[python-shield]: https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white
[python-url]: https://www.python.org/
