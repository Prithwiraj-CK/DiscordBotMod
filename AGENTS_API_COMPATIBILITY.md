# Managed Agents API compatibility report

Date checked: 2026-09-26

## Decision

**Do not implement `AGENT_RUNTIME=agents` yet.** The required compatibility
gate is not fully satisfied. Responses remains the only supported runtime in
this repository.

The decision is deliberately conservative: the requested model is
`gpt-6-luna`, and the project must not silently change it. Official
documentation confirms Luna support for the Responses API and function calling,
but does not explicitly confirm Luna support for the managed Agents API. The
installed Python SDK also does not expose the Agents API namespace.

No OpenAI API request, Discord request, service restart, model change, or
retention-setting change was made for this investigation.

## Local compatibility checks

| Check | Result | Evidence |
| --- | --- | --- |
| Installed Python SDK | **Blocked** | The project virtual environment has `openai==2.48.0`; `OpenAI(api_key="placeholder").beta` has no `agents` member. |
| Current runtime | Supported | `llm.py` uses the Responses API and `OPENAI_MODEL` defaults to `gpt-6-luna`. |
| Current account access | **Unknown** | No authenticated Agents API call or dashboard inspection was performed. An account would need `api.agents.read`, `api.agents.write`, and `api.responses.write` permissions. |
| Required model in managed Agents API | **Not officially established** | The Luna model page lists Responses and Chat Completions endpoints and describes its tools as Responses tools. Agents documentation examples use `gpt-6-astra`; no official source checked explicitly states that `gpt-6-luna` is accepted by managed Agent sessions. |

Because the SDK and model gates are not both positive, no feature flag or
runtime implementation is allowed under the requested rule.

## Capability matrix

| Requirement | Official status | Compatibility conclusion |
| --- | --- | --- |
| Managed Codex harness | Supported | Agents API provides a managed Codex harness, durable sessions, orchestration, recovery, and context compaction. |
| `gpt-6-luna` availability | **Unconfirmed for Agents** | Luna is officially documented for Responses and Chat Completions. Keep Responses until OpenAI explicitly documents Agents API support or an authorized test confirms it without changing the model. |
| Custom function tools | Supported | Agents sessions accept JSON-schema functions. The application receives required actions and submits a result using session/turn/call IDs. Existing Olympus tool schemas are conceptually reusable, but their event-driven handling would require a new adapter. |
| Self-hosted environment | Supported, but unsuitable as-is | Agents API supports `environment.type: self_hosted`; it requires `codex exec-server`, a restricted environment key, outbound WebSocket connectivity, and an executor that runs shell commands and reads/writes files. This is not the project’s present read-only function-tool design. |
| Read-only repository access | Supported through current function tools | The safer fit is `environment.type: none` plus the existing root-confined Olympus functions. A self-hosted executor is not inherently read-only; OpenAI documents it as running commands and reading/writing files. |
| `store=False` equivalent | **Not equivalent** | Responses supports the current stateless `store=False` behavior. Agents API retains durable session state and explicitly does not support Zero Data Retention. A migration would change the data lifecycle. |
| Automatic compaction | Supported | The managed harness provides context compaction. It changes context management from this repository’s explicit per-turn packet construction to hosted durable session behavior. |
| Tracing and token accounting | Partially supported | Agent traces and turn/session usage are available, but usage is best-effort, may arrive after completion, can be `null`, and does not expose cache-write tokens. The current exact local usage ledger would need to remain authoritative for billing estimates or be redesigned. |
| Latency | Likely higher / unmeasured | Agent sessions add session creation or reuse, event streaming/webhook handling, function-action round trips, and possibly executor startup. No authenticated benchmark was run, so there is no measured latency claim. |

## Migration surface if the gates later pass

The work would be a substantial adapter, not a switch of one client method:

1. Upgrade to an OpenAI Python SDK that exposes `client.beta.agents` and pin
   the verified minimum version.
2. Confirm, with an authorized non-production session, that `gpt-6-luna` is
   accepted by the Agents API for this project and retains strict structured
   output/function behavior.
3. Create an event-driven function dispatcher for required actions. It must
   preserve the existing Olympus-only tool allowlist, `ResearchBudget`, opaque
   anchors, selected-evidence gate, account/security handoffs, and privacy-safe
   logging.
4. Use `environment.type: none`; do not attach a self-hosted executor unless a
   separate, OS-enforced read-only sandbox is designed and approved.
5. Add session lifecycle/expiry/deletion policies. This is necessary because
   Agents sessions are durable and do not offer the current `store=False` data
   boundary.
6. Add parity tests for structured decision, tool authorization, budget,
   grounding, safety handoffs, and usage reporting before allowing any runtime
   selection outside tests.

## Official documentation consulted

- [Agents API overview](https://developers.openai.com/api/docs/guides/agents-api/overview): managed harness, durable sessions, compaction, and Agents retention limits.
- [Agents API architecture](https://developers.openai.com/api/docs/guides/agents-api/architecture): `none`, OpenAI-hosted, and self-hosted environment boundaries; application-owned function tools.
- [Agents API functions](https://developers.openai.com/api/docs/guides/agents-api/tools/functions): custom JSON-schema function tools and required-action lifecycle.
- [Self-hosted sandboxes](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted): `codex exec-server`, required credentials, and executor behavior.
- [Agents observability and usage](https://developers.openai.com/api/docs/guides/agents-api/observability): trace contents, late/best-effort usage, and cache-write accounting limitation.
- [GPT-6 Luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna): Luna’s Responses/Chat endpoint and function/tool support.
- [Data controls](https://developers.openai.com/api/docs/guides/your-data): Responses `store=false` behavior and general API retention controls.
