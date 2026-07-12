# Token Firewall Evaluation · token-firewall-m3-route-002

发布结论：**INSUFFICIENT_SAMPLE**
当前 Pilot 门禁：**FAIL**

- 配对任务：2（最低要求 12）
- Control 成功率：100.0%
- Experiment 成功率：100.0%
- 成功率差：0.00 pp
- 95% 配对 Bootstrap CI：[0.00, 0.00] pp
- 非劣效：True（margin 5 pp）
- 累计 Sol Token：598,925 → 242,649
- Sol 节省：59.49%（目标 70%）
- 用量完整：True

## 图表

- [quality-token-pareto.svg](quality-token-pareto.svg)
- [paired-quality.svg](paired-quality.svg)
- [risk-strata.svg](risk-strata.svg)
- [token-waterfall.svg](token-waterfall.svg)

## Task 明细

| Task | Risk | Type | Control | Experiment | Sol Token C→E |
|---|---|---|---:|---:|---:|
| T-PILOT-LOW | low | bugfix | 100.0 | 100.0 | 271,282→141,741 |
| T-PILOT-HIGH | high | bugfix | 100.0 | 100.0 | 327,643→100,908 |
