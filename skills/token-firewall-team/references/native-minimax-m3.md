---
name: native-minimax-m3
description: Configure and supervise a MiniMax-M3 custom agent inside the Codex native subagent lifecycle.
---

# Native MiniMax-M3 route

Keep provider credentials in the user environment and provider definition in user-level `~/.codex/config.toml`. Install a standalone `~/.codex/agents/minimax-m3.toml` with `name = "minimax_m3"`, a bounded-Worker description and developer instructions, `model = "MiniMax-M3"`, `model_provider = "<provider-id>"`, and an optional `model_catalog_json`.

Current Codex requires standalone custom-agent files to define `name`, `description`, and `developer_instructions`. The main session keeps its own model because the provider and model override apply only to the spawned custom-agent layer. Codex owns creation, tools, messaging, status, waits, follow-ups, interruption, and result collection; no Claude Code or MiniMax Code process is required.

`model_catalog_json` describes model capabilities such as the reasoning toggle, base instructions, shell/tool behavior, parallel tool calls, input modalities, and truncation. It is not credential storage, endpoint configuration, routing proof, or quality evidence.

Route only low-risk and selected medium-risk Work Orders with tight paths, positive/negative/boundary cases, and deterministic validators. Avoid a full-history fork. After delivery, reconstruct Git truth, rerun validators, and dispatch a fresh non-M3 Verifier. Keep ambiguous semantics, security, concurrency, migrations, destructive actions, and external side effects with a stronger approved implementer.

Use either `env_key` or command-backed provider authentication, never both. Never commit a literal API key. See the repository's `docs/native-minimax-m3.md` and `examples/codex/` when available for complete credential-free examples.
