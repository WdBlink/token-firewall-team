# Jev semantic evaluation

Run after deterministic validation and fresh verification, before final review. Jev supplies three 0–3 scores (requirements, semantic boundary, evidence grounding) and a feedback category. These are review inputs, not PASS/FAIL authority. Existing Git, validator, independent verifier, Sol and HUMAN_REBET requirements remain in force. Routing shadow is separate.

## First use

Use `TYPESAFE_API_KEY` from the runtime environment. When absent, the CLI prompts with hidden input on an interactive terminal, using the key only for that invocation. In Codex/noninteractive mode, it returns `TYPESAFE_API_KEY_REQUIRED`; tell the user: “请配置 TypeSafe API Key 到运行环境的 TYPESAFE_API_KEY，或在本地终端运行 eval-typesafe 后按隐藏提示输入。” Do not echo keys or put them in chat, command arguments, artifacts, or the repository. Users may manage persistent secrets through their own secret manager. An existing environment key avoids the prompt.

## Input and command

Prepare a redacted JSON packet with nonempty `task`, `acceptance_spec`, `delivery`, `evidence`, and `risk` (`low`, `medium`, `high`, `critical`). Evidence must contain actual validator observations and bounded patch/context slices sufficient to judge acceptance cases. Only these five fields are sent, with a 64 KB limit. Remove credentials, unrelated private data, Worker/model/cost identity, and hidden tests. Review nested content too. This packet is sent to TypeSafe's hosted API.

```bash
python3 "$SKILL_ROOT/scripts/token_firewall.py" eval-typesafe packet.json --out jev-eval-attempt-1.json
```

Use a new output path per attempt. The record preserves exact request, request hash, rubric version, full response (including returned model and usage), latency and status. Do not publish private packets automatically. Exit 0 means `SCORED`, not accepted. Exit 1 means service/response failure (`ESCALATE`); exit 2 means invalid local input or missing key. Use normal independent review on failure and explicitly record the unavailable score. Never silently retry.

The reviewer inspects low scores and gaps, then makes the normal evidence-backed decision. Jev confidence is not probability of correctness. No threshold currently bypasses a reviewer. Scores are not substituted for hidden-test outcomes or the Evaluation Lab's mechanical non-inferiority endpoint. No new savings or quality claim is implied.
