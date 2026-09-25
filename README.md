# Discord AI support bot

Drafts answers to user questions from a set of project one-pagers, posts them
to the configured shadow-output channel for staff review, and hands off to a human when
it doesn't know.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

### 1. Create the account

This bot signs in as a **normal Discord user account**, not a bot application.
That is what lets it appear as a person in the member list, with no BOT tag.

> **Read this first.** Automating a user account ("self-botting") is against
> Discord's Terms of Service. The usual penalty is termination of that account,
> and it can take the server access with it. Use a dedicated throwaway account,
> never your own, and keep `ALLOWED_CHANNEL_IDS` tight.

1. Make a new Discord account and get it into the server the normal way
2. Log into that account in a browser
3. DevTools (F12) → **Application** → **Local Storage** → `discord.com`
4. Copy the `token` value into `DISCORD_USER_TOKEN` in `.env`

The token is rotated whenever that account changes its password, so a sudden
run of 401s usually means someone logged it out or reset it.

### 2. Configure

Turn on Developer Mode in Discord (Settings → Advanced), then right-click each
support channel → **Copy Channel ID** and put them in `ALLOWED_CHANNEL_IDS`,
comma-separated. Right-click the staff role → **Copy Role ID** for
`STAFF_ROLE_ID`.

The bot reads **only** in the listed channels, plus directly tagged/replied-to
messages in the configured server. Empty list = answers nowhere outside that
direct-tag exception.
The account must already be able to see and post in each one; there are no
permissions to grant, it just needs to be a member.

`SHADOW_MODE=true` is the safe default. Every proposal is posted only in the
configured shadow-output channel; it is never sent as a reply in the source
channel. Set `SHADOW_MODE=false` only for a deliberate
live test after migrating to an official Discord bot account.
Outgoing URLs are wrapped in Discord's no-preview format (`<https://...>`),
so links remain clickable without creating automatic embeds.

### Short-term conversation memory

When `CONVERSATION_MEMORY_ENABLED=true` and `REDIS_URL` is set, Salena keeps a
scrubbed, bounded conversation record in Redis for four hours by default. The
record is scoped to `guild_id`, `channel_id`, `thread_id`, and `user_id`, so a
user's unrelated tickets cannot share context. Older turns are compacted into
an extractive summary and the record expires automatically. Redis is only
conversation context: approved facts and repository evidence remain the
authority for factual answers.

Redis is optional. If the package, server, or connection is unavailable, the
bot logs one warning and falls back to the existing recent Discord context.
The memory path does not widen the Discord read allowlist or the output-channel
guard. For local use, start Redis and set
`REDIS_URL=redis://127.0.0.1:6379/0` in `.env`.

### Discord transport

Salena uses REST polling every 15 seconds by default (`DISCORD_TRANSPORT=rest`)
instead of discum's unstable user-account WebSocket. It reads only the existing
allowed channels and preserves the output-channel guard; the trade-off is up to
one poll interval of reply delay. This removes the recurring WebSocket callback
`error 15`, reconnect loops, and watchdog restarts from normal operation.

`DISCORD_TRANSPORT=gateway` remains as a compatibility escape hatch. In that
mode the gateway watchdog and five-minute REST backup sweep are enabled, but
the legacy transport remains unreliable.

### Production transport

The current listener still authenticates with a Discord user token through the
unmaintained `discum` library. REST polling avoids its failing WebSocket, but
the durable production fix remains an official Discord application and bot
token with a maintained gateway client. Do not put a bot token in source
control; keep it only in the ignored `.env` file.

### 3. Add knowledge

The repository retains both `valhalla.md` and `olympus.md` in `knowledge/`.
Live support is currently Olympus-only: Valhalla knowledge is dormant and an
explicit Valhalla question receives a fixed team handoff. See
`knowledge/README.md`.

### 4. Run

```bash
python bot.py
```

For automatic restart while this Mac is logged in, install the local
shadow-mode `launchd` service:

```bash
chmod +x ops/run-shadow.sh
mkdir -p .runtime
cp ops/com.discordbotmod.shadow.plist "$HOME/Library/LaunchAgents/"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.discordbotmod.shadow.plist"
```

The service restarts after a gateway failure and writes logs to `.runtime/`.
It cannot run while the Mac is powered off or asleep, and it always forces
`SHADOW_MODE=true`.

### 5. Monitor model usage

Salena uses `gpt-6-luna` through the Responses API with configurable reasoning
(`OPENAI_REASONING_EFFORT=medium` by default). Set
`DAILY_USAGE_WEBHOOK_URL` in the ignored `.env` to receive one report every
24 hours with estimated API cost, calls, input/cache-write/output/reasoning
tokens, and model counts. With `USAGE_REPORT_LIVE_UPDATES=true` (the default),
that same report message is edited after each completed support response with
the latest rolling totals; it does not post a new message per question. The
local `.runtime/openai_usage.jsonl` ledger stores only those counts and cost
metadata—never Discord text, prompts, or replies.

### 5.1 Bound one support turn

Each support turn has an independent research budget: 50,000 cumulative input
tokens, 24,000 tokens in one request context, 12,000 tool-output tokens, 10
tool calls, 6 reads, 8 selected evidence items, and 75 seconds by default.
The `RESEARCH_MAX_*` settings in `.env.example` configure those limits. Luna's
exact local tokenizer is not available, so Salena uses `o200k_base` when
available and otherwise reserves one token per three UTF-8 bytes—a deliberately
conservative fallback. If a limit is reached, she hands off with incomplete
evidence rather than guessing. Per-turn logs contain only token/count totals,
the stop reason, and evidence IDs; they never include Discord text, source
text, secrets, or answer text.

### 6. Validate the knowledge corpus

The approved source-of-truth index and anonymized regression cases can be
checked offline before changing live replies:

```bash
python evaluate.py
python evaluate.py --list
python evaluate.py --answers answers.json
python evaluate.py --run-openai
python evaluate.py --olympus-only --run-openai
python evaluate.py --run-openai --post-to-test
python index_discord_history.py --scan
python index_discord_history.py
```

`knowledge/approved_facts.json` contains the 53 facts that may be used as answers,
their provenance, risk, and handling guidance. The Markdown one-pagers are
supplemental notes. Product-owner clarifications, runtime behavior, and the
official product documentation take precedence over older notes or examples.
The evaluator checks schema, duplicate IDs, evidence references, and obvious
secret-shaped content; it does not call Discord or OpenAI. The current
regression set contains 97 cases. Routing and posting are autonomous; staff
approval is not required before the bot makes a shadow proposal. The OpenAI
replay measures action, evidence, forbidden claims, and semantic support; the
optional test-channel flag posts each case result only to #bot-test.

The optional history index reads the configured support channels/categories,
scrubs wallet-like values, emails and Discord IDs, and stores the result only
under `.runtime/` (which is ignored by git). Each question retrieves a few
matching excerpts, with staff replies ranked first. Historical text is
secondary context and cannot override approved facts. Tagged messages with
Discord image attachments receive a one-time vision transcription/summary;
image text is untrusted context and cannot override approved facts.

If `CODEBASE_OLYMPUS_PATH` is configured and `CODEBASE_SEARCH_ENABLED=true`,
Olympus product and workflow questions also investigate that repository
locally. This is a separate opt-in because the selected excerpts are sent to
OpenAI as model context. Research is read-only and adaptive: Luna first plans
the factual parts of the question, then can reformulate a weak search, follow
references/callers/tests, and inspect complete bounded functions or
documentation sections until its coverage ledger is complete. It stops early
once every planned part has citable support, or safely hands off on an
incomplete/conflicting ledger, repeated/no-progress work, or a budget limit.
It excludes dependencies,
generated files, logs/dumps/backups, binary assets, and secret-shaped files,
and redacts sensitive-looking values. The model has no shell or filesystem-write
tool. Code excerpts can explain exact implementation behavior; when enabled,
approved facts remain authoritative for fees, security, account-specific
support, privacy, and product promises. Repository search is disabled by
default. `CODEBASE_VALHALLA_PATH` and `REPOSITORY_SEARCH_BOTH` are retained
only for the dormant Valhalla implementation and have no effect in the active
Olympus-only support path.

`SUPPORTED_PRODUCTS=olympus` is the authoritative live product scope. It keeps
shared terms such as “ratio”, “wallet”, and “copy trading” inside Olympus
unless the user explicitly names Valhalla; that explicit case is handed off
before any model, fact retrieval, or repository call. Re-enable Valhalla only
through this single configuration after its own release evaluation.
`APPROVED_FACTS_ENABLED=true` keeps curated FAQ facts
available as authoritative evidence for fees, product promises, onboarding,
and security. Set it to `false` only for a repository-only shadow
evaluation. It does **not** disable account-specific, secret, security, or
money-risk escalation rules. Repository-only mode is useful for testing
implementation questions, but it should not be considered a replacement for
verified public-policy facts such as fees or product promises.

### Olympus repository investigation tools

`olympus_repository_tools.py` provides the live Olympus-only, read-only tool
session used by Luna's adaptive research loop. Search calls issue opaque per-session
anchor IDs; section, caller, reference, and test reads dereference only those
issued IDs, never model-supplied filesystem paths. Every response carries
size/token metadata and emits a privacy-safe trace without question or source
text. Search anchors are non-citable; only a bounded completed read can become
repository evidence.

The layer rejects path traversal, escaping symlinks, `.env`, secret/credential
files, dependencies, generated output, logs, dumps, and oversized or binary
files. It exposes a fixed repository revision check using read-only Git
commands. `run_allowlisted_test` recognises only hard-coded command IDs, but
currently returns `test_execution_unavailable`: this runtime has no OS-level
sandbox that can safely execute untrusted repository test code without allowing
writes or network access. It intentionally does not fall back to a local shell.
The tools are registered only for the Olympus support path; they cannot search
or read Valhalla.

## How it works

```
message in an allowed channel
  → Discord REST poll, dispatched to a worker thread
  → scoped Redis memory plus recent Discord messages
  → retain at least the current user's five previous messages
  → tagged images transcribed once as untrusted context
  → Olympus-only product scope and deterministic Valhalla handoff
  → understand question and plan private factual subquestions
  → adaptive Olympus-only discovery with compact opaque anchors
  → inspect citable sections; optionally follow references, callers, and tests
  → per-turn token, tool, evidence, and wall-clock budget
  → retrieve approved facts and current code as evidence; Markdown and old staff replies remain background only
  → verify a coverage ledger for every planned subquestion
  → Luna drafts from a fresh compact selected-evidence packet, or clarifies/hands off safely
  → shadow proposal in the configured output channel, or autonomous handoff proposal
```

The REST poller is the live transport because the old user-account gateway was
intermittent. It also performs bounded catch-up so a process restart does not
silently lose a freshly tagged question.

## Notes

- **It answers itself if you let it.** On a user account our own replies appear
  in REST history as ordinary messages (`author.bot` is false for us),
  so the self-id check in `_should_answer` is the only thing preventing an
  endless conversation with ourselves. Do not remove it.
- **Threads, not async.** Answers are produced on a small
  `ThreadPoolExecutor`, while the REST poller continues checking channels.
- **Model calls.** Every model call goes through `llm.py`, which uses the
  Responses API so the configured reasoning model can plan and validate support
  research. Model responses are requested with `store=False`.
- **Escalation is deliberate.** The prompt tells the model to escalate rather
  than guess, so a thin `knowledge/` means lots of handoffs. Fix that by
  writing more knowledge, not by softening the prompt — a confidently wrong
  answer to a real user costs more than a handoff.
- **No per-user rate limit.** Every qualifying message gets an answer, however
  fast they arrive. `WORKER_THREADS` is the only thing bounding concurrency.
- **Keys.** `.env` only. Don't commit it — add it to `.gitignore`.

## When things go wrong

The design rule: a real user's question must not vanish. A slow answer is
recoverable, a wrong answer gets escalated, but a silently dropped question is
invisible to everyone including us.

- **Transient model failures retry.** Timeouts, rate limits and 5xx get
  `LLM_MAX_ATTEMPTS` tries with backoff. A bad key or malformed request fails
  immediately, since retrying only makes the user wait longer for the same
  error.
- **A failed answer goes back in the queue.** A message is reserved before the
  model call so the live path and the sweep can't both answer it, and released
  again on failure so the next sweep retries. After `ANSWER_ATTEMPTS` it's
  written off and alerted, rather than retried forever.
- **The sweep can't die.** Each pass is wrapped, so one unreadable channel or
  one bad message costs that pass and nothing more; the loop keeps going and
  alerts. A dead sweep looks exactly like a healthy bot from the outside.
- **Alerts.** Set `ALERT_WEBHOOK_URL` to get told when the model is
  unreachable, the bot can't reply in a channel, the sweep crashed, or the
  gateway stopped. Repeats of the same alert collapse for five minutes.
  Unset, it's a no-op.
- **Rate limits are honoured.** A 429 waits the `Retry-After` Discord asks for
  rather than hammering. Ignoring them is how a user account gets flagged.
- **Exit codes.** 1 = bad config, 2 = the token was rejected, 3 = the gateway
  stopped. All non-zero, so a supervisor restarts rather than reading a dead
  bot as a clean shutdown.
- **Bad config degrades, it doesn't crash.** A non-numeric setting logs a
  warning and uses the default; one malformed channel id is dropped and the
  rest keep working. Missing token or key still exits at startup with a
  message saying which.
- **Knowledge is hot.** Editing a file in `knowledge/` takes effect on the next
  question, no restart.
- **The current runtime is still a test harness.** It authenticates as a normal
  Discord user account, which Discord prohibits automating. Keep it in a
  private test channel until it is migrated to an official Discord bot account
  and the structured routing/evaluation gate is in place.

## Next

- **SigNoz** — let it answer from live telemetry ("is checkout erroring?").
  Add a `signoz.py` query helper and expose it as a tool call.
- Thread replies for long back-and-forths.
- Log every escalation; the recurring ones tell you what to write down next.
