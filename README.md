# Discord AI support bot

Answers user questions in specific channels from a set of project one-pagers,
and hands off to a human when it doesn't know.

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

The bot answers **only** in the listed channels. Empty list = answers nowhere.
The account must already be able to see and post in each one; there are no
permissions to grant, it just needs to be a member.

### 3. Add knowledge

Drop `valhalla.md` and `olympus.md` into `knowledge/`. See `knowledge/README.md`.

### 4. Run

```bash
python bot.py
```

## How it works

```
message in an allowed channel
  → gateway event (discum), dispatched to a worker thread
  → last N messages pulled for context
  → system prompt (rules + one-pagers) + conversation → model
  → answer, or [[ESCALATE]] → pings staff role instead
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
- **Cooldown.** One question per user per `USER_COOLDOWN_SECONDS`. Messages
  dropped by the cooldown are marked handled, so the sweep doesn't answer them
  five minutes later and undo it.
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

## Next

- **SigNoz** — let it answer from live telemetry ("is checkout erroring?").
  Add a `signoz.py` query helper and expose it as a tool call.
- Thread replies for long back-and-forths.
- Log every escalation; the recurring ones tell you what to write down next.
