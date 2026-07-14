<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/logo-light.svg">
    <img alt="Token Firewall" src=".github/logo-light.svg" width="520">
  </picture>

  <p><strong>70.79% fewer expensive coding-model tokens in a 12-task study—without giving up quality control.</strong></p>
  <p>Cheaper models implement. Your strongest model reviews a compact, Git-and-test-backed delivery.</p>
  <p><strong>English</strong> | <a href="README.zh-CN.md">中文</a></p>
</div>

<div align="center">

[![License: MIT][license-shield]][license-url]
[![Release][release-shield]][release-url]
[![Tests][tests-shield]][tests-url]
[![Agent Skills][skills-shield]][skills-url]
[![Python][python-shield]][python-url]

</div>

<div align="center">
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#why-token-firewall">Why</a> &middot;
  <a href="#experimental-evidence">Evidence</a> &middot;
  <a href="#how-it-works">How It Works</a> &middot;
  <a href="#current-limits">Limits</a> &middot;
  <a href="docs/evaluation.md">Study Details</a>
</div>

> **Primary-study result:** In a frozen 12-task Terra-worker/Sol-reviewer study, expensive Sol tokens fell **70.79%**—from **3,599,108** to **1,051,353**—while task success was **91.67%** versus **83.33%** for Sol-direct. There was **no observed delivery-quality loss** in this study.
>
> This is a route- and dataset-specific finding. It does not prove the same result for other repositories, model releases, languages, or task distributions.

## Quick Start

### Install

Install the Skill globally:

```bash
npx skills add WdBlink/token-firewall-team -g
```

### Choose an operation

Ask Codex for the outcome you need:

```text
"Use token-firewall-team to implement this issue" — bounded delegation, Git/test gates, and strong final review
"Benchmark this route against Sol-direct"       — paired quality, usage, and Token-savings evidence
"Show the external Worker status"               — state changes, heartbeat, Session, usage, and delivery summary
```

## Usage

Example invocation for a coding change:

```text
Use token-firewall-team for this change. Route implementation to an approved cheaper Worker, keep the strongest approved model for final review, and show only state changes and low-frequency heartbeats.
```

## Why Token Firewall

If your expensive coding model spends most of a task reading files, running tests, and drafting routine changes, its context budget is doing execution work rather than high-value judgment. Token Firewall is for teams that can state what “done” means and want a cheaper implementation path with a strong final review.

## What You Get

- **Lower frontier-model spend.** Move routine implementation to approved cheaper coding agents and keep expensive-model context for judgment.
- **Safer delegation.** Freeze positive cases, negative cases, and a semantic boundary before implementation begins.
- **Evidence before acceptance.** Require a Git-truth patch, approved tests, and a fresh verifier before delivery reaches final review.
- **Low-noise external progress.** See state changes and periodic heartbeats without streaming full Worker terminals into the main task.
- **Quality and savings in one lab.** Preserve failed attempts, rework, hidden checks, model identity, and native usage for paired evaluation.
- **Fail closed.** Stop when repository state, model identity, isolation, usage evidence, or delivery records cannot be verified.

## Experimental Evidence

The primary study compares Sol-direct against the Terra-worker/Sol-reviewer route on the same frozen 12-task paired suite. Tasks span feature, bug-fix, refactor, and integration work across low, medium, and high risk; success required public and hidden checks, bounded review, scope checks, and complete usage evidence.

<div align="center">
  <img alt="Per-task delivery quality and expensive Sol Token comparison across 12 paired tasks" src=".github/assets/terra-n12-task-comparison.svg" width="960">
</div>

| Evaluated route | Task success | Mean quality | Expensive Sol tokens |
|---|---:|---:|---:|
| Sol implements directly | 83.33% (10/12) | 94.58 | 3,599,108 |
| Terra implements, Sol reviews | 91.67% (11/12) | 96.67 | **1,051,353 (−70.79%)** |

The route passed the pre-specified five-point paired non-inferiority gate: its paired 95% interval was **[0, 25]** percentage points, above the frozen −5-point margin. The study therefore supports a bounded conclusion: **70.79% fewer expensive-model tokens with no observed delivery-quality loss in this study.** The higher point estimates are reported as observations, not as evidence that the architecture improves quality.

It does not guarantee quality or savings outside the evaluated Terra-worker/Sol-reviewer route and frozen suite. Other routes are still directional studies, not evidence for this conclusion.

→ [Read the methodology, disclosures, limitations, and reproduction notes](docs/evaluation.md) · [See the evaluation framework and Inspect AI role](docs/evaluation-framework.md) · [Inspect the frozen Lab](evidence/labs/terra-route-n12-001/report/evaluation-report.md)

## When It Fits

Use Token Firewall when a coding task has clear acceptance evidence, implementation context is substantial, and you want the strongest available model to make the final judgment rather than spend the full task budget on implementation.

Do not use it to compensate for vague requirements, automate irreversible production actions without approval, or generalize one study into a universal quality claim. Keep critical migrations, destructive work, and irreducibly ambiguous tasks with the strongest approved implementer and explicit human boundaries.

## Compatibility

| Capability | What you need | Required? |
|---|---|---:|
| Install and invoke the Skill | Codex with [Agent Skills](https://agentskills.io) support | Yes |
| Terra/Sol route | Codex CLI with the selected models available | Optional route |
| MiniMax M3 route | MiniMax Code, or Claude Code with verified effective M3 identity | Optional route |
| Protocol validation and Evaluation Lab | Python 3.10+ | Yes |

For route preflights, Runtime commands, and operational boundaries, see the [Runtime runbook](skills/token-firewall-team/references/runbook.md) and [architecture overview](docs/architecture.md).

## How It Works

```text
Explicit acceptance contract
        → approved cheaper Worker
        → Git scope checks + deterministic tests + fresh verifier
        → compact blind packet for the strongest final reviewer
```

The Worker always proposes; Git, approved validators, the fresh verifier, and the final reviewer decide what is accepted.

## Current Limits

- The primary result comes from one frozen synthetic Python suite and one Terra/Sol configuration; real-repository and cross-language replication is still needed.
- M3 and Claude routes currently have only two-task directional evidence and do not inherit the 12-task Terra conclusion.
- Claude Code and MiniMax Code are optional transports with route-specific identity and isolation requirements; unsupported or unverifiable environments fail closed.

## Help Shape the Roadmap

The next evidence priorities are real-repository studies, 12+ task M3 route replications, recognized external benchmarks, and model-version drift tracking. **Star or watch the repository to follow each new route report**, or help prioritize and contribute that work through [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 WdBlink.

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
