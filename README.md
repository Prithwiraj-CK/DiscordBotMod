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

### Gateway recovery

The Discord listener has a watchdog because the legacy `discum` client can
loop on a WebSocket after that socket has closed. A healthy idle gateway still
receives heartbeat acknowledgements, so if there is no gateway traffic for
`GATEWAY_STALE_SECONDS` (180 seconds by default), the process exits and its
launchd supervisor starts a new process with a new WebSocket. A closed socket
or any recorded transport error without later gateway traffic is restarted
after 30 seconds. `GATEWAY_RESTART_GRACE_SECONDS` (20 seconds by default) is
the maximum time allowed for the clean shutdown before the supervisor restart
is forced. The five-minute REST sweep remains a separate backup for messages
that arrived during a reconnect.

### 3. Add knowledge

Drop `valhalla.md` and `olympus.md` into `knowledge/`. See `knowledge/README.md`.

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

### 5. Validate the knowledge corpus

The approved source-of-truth index and anonymized regression cases can be
checked offline before changing live replies:

```bash
python evaluate.py
python evaluate.py --list
python evaluate.py --answers answers.json
python evaluate.py --run-openai
python evaluate.py --run-openai --post-to-test
python index_discord_history.py --scan
python index_discord_history.py
```

`knowledge/approved_facts.json` contains the 52 facts that may be used as answers,
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

If `CODEBASE_VALHALLA_PATH` and `CODEBASE_OLYMPUS_PATH` are configured and
`CODEBASE_SEARCH_ENABLED=true`, product and workflow questions also investigate
those two repositories locally. This is a separate opt-in because the selected
excerpts are sent to OpenAI as model context. Research is read-only: semantic
query expansion, keyword search, filename/symbol/route/command/heading search,
one-hop local-reference following, complete bounded function/section reads,
and multiple evidence-review rounds are used. It excludes dependencies,
generated files, logs/dumps/backups, binary assets, and secret-shaped files,
and redacts sensitive-looking values. The model has no shell or filesystem-write
tool. Code excerpts can explain exact implementation behavior, but approved
facts remain authoritative for fees, security, account-specific support,
privacy, and product promises. It is disabled by default.

## How it works

```
message in an allowed channel
  → gateway event (discum), dispatched to a worker thread
  → last N messages pulled for context
  → tagged images transcribed once as untrusted context
  → structured classifier chooses product, intent, risk and action
  → semantic query expansion plus keyword/filename/symbol/route/command search
  → follow local references and read complete bounded functions or documentation sections
  → retrieve matching approved facts, Markdown notes, historical excerpts, and safe code excerpts
  → compare frontend, backend, routes, and docs during iterative evidence review
  → structured drafter maps each factual claim to evidence and validates its action
  → shadow proposal in the configured output channel, or autonomous handoff proposal
```

A 5 minute sweep runs alongside as a safety net for anything the gateway
missed. The gateway is the primary path, so on a healthy bot the sweep finds
nothing almost every time.

## Notes

- **It answers itself if you let it.** On a user account our own replies come
  back through the gateway as ordinary messages (`author.bot` is false for us),
  so the self-id check in `_should_answer` is the only thing preventing an
  endless conversation with ourselves. Do not remove it.
- **Threads, not async.** discum is synchronous, so answers are produced on a
  small `ThreadPoolExecutor`. The gateway callback must return immediately:
  blocking it stalls the heartbeat and drops the connection.
- **Model swap.** Every model call goes through `ask_llm()` in `llm.py`. Claude
  version is in a comment at the bottom of that file — swapping is one edit.
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
