# Token Firewall Evaluation · token-firewall-terra-route-002

发布结论：**PASS**
当前 Pilot 门禁：**PASS**

- 配对任务：12（最低要求 12）
- Control 成功率：83.3%
- Experiment 成功率：91.7%
- 成功率差：8.33 pp
- 95% 配对 Bootstrap CI：[0.00, 25.00] pp
- 非劣效：True（margin 5 pp）
- 累计 Sol Token：3,599,108 → 1,051,353
- Sol 节省：70.79%（目标 70%）
- 用量完整：True

## 图表

- [quality-token-pareto.svg](quality-token-pareto.svg)
- [paired-quality.svg](paired-quality.svg)
- [risk-strata.svg](risk-strata.svg)
- [token-waterfall.svg](token-waterfall.svg)

## Task 明细

| Task | Risk | Type | Control | Experiment | Sol Token C→E |
|---|---|---|---:|---:|---:|
| T-PILOT-HIGH | high | bugfix | 100.0 | 100.0 | 327,643→72,184 |
| T-PILOT-LOW | low | bugfix | 100.0 | 100.0 | 271,282→70,128 |
| T-EVAL-03 | low | feature | 100.0 | 100.0 | 338,926→96,987 |
| T-EVAL-04 | medium | feature | 100.0 | 100.0 | 305,390→70,917 |
| T-EVAL-05 | low | refactor | 100.0 | 100.0 | 289,067→97,649 |
| T-EVAL-06 | medium | refactor | 80.0 | 100.0 | 373,854→122,528 |
| T-EVAL-07 | medium | integration | 100.0 | 100.0 | 274,857→70,583 |
| T-EVAL-09 | high | bugfix | 100.0 | 100.0 | 257,543→74,475 |
| T-EVAL-10 | medium | feature | 100.0 | 100.0 | 286,537→70,298 |
| T-EVAL-11 | medium | refactor | 55.0 | 60.0 | 344,444→135,253 |
| T-EVAL-12 | medium | integration | 100.0 | 100.0 | 257,061→73,765 |
| T-EVAL-13 | low | feature | 100.0 | 100.0 | 272,504→96,586 |
