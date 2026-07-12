# Inspect AI compatibility layer

Token Firewall's Benchmark Runtime and normalized Evaluation Pairs remain the authoritative source for Git state, hidden tests, retries, Session-level usage, and the release verdict. This optional adapter turns frozen pairs into native Inspect samples for exploratory analysis and re-scoring; it does not rerun or replace the external coding Harness.

Export a Lab's pairs:

```bash
TF="python3 skills/token-firewall-team/scripts/token_firewall.py"
$TF evaluation-export-inspect evidence/labs/<lab>/protocol.json \
  evidence/labs/<lab>/pairs/*.json \
  --out-dir /tmp/token-firewall-inspect
```

Create a structured Inspect Eval Log without another model call:

```bash
pip install 'inspect-ai>=0.3.206'
inspect eval integrations/inspect_ai/token_firewall_eval.py \
  -T dataset=/tmp/token-firewall-inspect/token-firewall-pairs.jsonl \
  --log-dir /tmp/token-firewall-inspect/logs
```

The custom scorer reports task success, quality-score difference, and per-pair Sol savings. Metrics include risk and task-type groups plus standard errors clustered by Task ID. Inspect logs can then be viewed or re-scored:

```bash
inspect view --log-dir /tmp/token-firewall-inspect/logs
inspect score /tmp/token-firewall-inspect/logs/<run>.eval \
  --scorer integrations/inspect_ai/token_firewall_eval.py@frozen_pair_scorer \
  --action overwrite --overwrite
```

Do not use the arithmetic mean of per-pair savings from Inspect as the authoritative Token verdict. Token Firewall computes cumulative, Session-deduplicated Sol savings from immutable Benchmark Records.
