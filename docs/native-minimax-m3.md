# Native MiniMax-M3 economy agent

Codex can keep an OpenAI model as the primary agent while spawning a custom `minimax_m3` subagent through MiniMax's OpenAI Responses API. Codex still owns the child lifecycle, tools, status, follow-ups, and result collection. No Claude Code or MiniMax Code process is required.

This guide follows the current [Codex custom-agent schema](https://learn.chatgpt.com/docs/agent-configuration/subagents), the [Codex custom-provider reference](https://learn.chatgpt.com/docs/config-file/config-reference), and MiniMax's official [Codex integration](https://platform.minimaxi.com/docs/token-plan/codex) and [Responses API](https://platform.minimax.io/docs/api-reference/responses-create) documentation.

## 1. Configure the provider

Export the key without writing it into a tracked file:

```bash
export MINIMAX_API_KEY="..."
```

Merge [`examples/codex/minimax-provider.toml`](../examples/codex/minimax-provider.toml) into the user-level `~/.codex/config.toml`. Provider and authentication settings belong at user level; project-local configuration cannot override machine-local provider credentials.

Codex also supports command-backed bearer tokens. This is useful when a desktop app does not inherit the login shell environment:

```toml
[model_providers.minimax]
name = "MiniMax"
base_url = "https://api.minimaxi.com/v1"
wire_api = "responses"

[model_providers.minimax.auth]
command = "/bin/zsh"
args = ["-lc", "source ~/.zshrc >/dev/null 2>&1; printf %s \"$MINIMAX_API_KEY\""]
```

Use either `env_key` or `[model_providers.minimax.auth]`, never both. Do not put a literal bearer token in repository files.

China-region accounts use `https://api.minimaxi.com/v1`; international accounts use `https://api.minimax.io/v1`.

## 2. Install the custom agent

Copy [`examples/codex/minimax-m3.toml`](../examples/codex/minimax-m3.toml) to:

```text
~/.codex/agents/minimax-m3.toml
```

Current Codex releases discover standalone custom-agent files directly. The file's `name = "minimax_m3"` is the source of truth and its required `description` and `developer_instructions` tell the parent when and how to use it. The primary session keeps its own model because the MiniMax provider is pinned only inside this custom-agent layer.

For shared repository policy, a credential-free custom-agent file may live under `.codex/agents/`, but provider and authentication settings must still remain user-level.

## 3. Install the optional model catalog

Copy [`examples/codex/minimax-m3-model-catalog.json`](../examples/codex/minimax-m3-model-catalog.json) to:

```text
~/.codex/model-catalogs/minimax-m3.json
```

`model_catalog_json` is capability metadata, not a second provider configuration. It teaches Codex how to present and drive the model:

- model slug and display description;
- available reasoning choices;
- base instructions;
- shell/tool-call behavior;
- parallel tool-call support;
- text and image input modalities;
- truncation behavior.

It does not store the API key, choose the API endpoint, prove task quality, or remove the need for the custom agent's supervision policy.

MiniMax-M3 treats `none` as thinking off. Any non-`none` reasoning effort enables Adaptive Thinking but does not tune a graded reasoning depth. The catalog therefore exposes only `none` and `high` as a clear off/on choice.

## 4. Restart and route

Restart Codex after changing provider, agent, or catalog files. Ask the parent to use `agent_type = "minimax_m3"` for a bounded Work Order. Prefer no history fork or a small bounded context slice; pass the contract, relevant paths, and validators explicitly.

Use the M3 route for low-risk and selected medium-risk work that has:

- tight allowed paths;
- positive, negative, and boundary cases;
- a deterministic validator;
- no destructive or irreversible side effects.

Always send an M3 delivery to a fresh non-M3 Verifier before bounded root review. Ambiguous semantics, security boundaries, concurrency, migrations, and destructive operations stay with a stronger approved implementer. Count retries, rework, and verifier tokens when measuring realized savings.

## Capability and evidence boundary

MiniMax documents M3 as a coding/agentic model with up to a 1M-token context window, image input, tool use, parallel tool calls, and an OpenAI-compatible Responses API. Its current pricing makes it attractive as an economy Worker, but pricing can change; check the [official pricing page](https://platform.minimax.io/subscribe/token-plan?tab=api-enterprise) instead of hard-coding a permanent cost ratio.

Token Firewall's current M3 evidence is only a two-task directional pilot. It supports supervised experimentation, not a general claim that M3 matches the strongest coding models. The route intentionally spends more verification effort because a cheap first pass only saves money when the accepted result remains correct.
