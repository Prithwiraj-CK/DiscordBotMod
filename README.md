# Discord AI support bot

Answers user questions in specific channels from a set of project one-pagers,
and hands off to a human when it doesn't know.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

### 1. Create the bot

1. https://discord.com/developers/applications → **New Application**
2. **Bot** tab → **Reset Token** → copy it into `DISCORD_BOT_TOKEN` in `.env`
3. Same tab → enable **Message Content Intent** (required, the bot reads messages)
4. **OAuth2 → URL Generator** → scopes `bot`, permissions
   `View Channels`, `Send Messages`, `Read Message History`
5. Open the generated URL to invite it to the server

Set the bot's name and avatar on the **General Information** tab.

### 2. Configure

Turn on Developer Mode in Discord (Settings → Advanced), then right-click each
support channel → **Copy Channel ID** and put them in `ALLOWED_CHANNEL_IDS`,
comma-separated. Right-click the staff role → **Copy Role ID** for
`STAFF_ROLE_ID`.

The bot answers **only** in the listed channels. Empty list = answers nowhere.

### 3. Add knowledge

Drop `valhalla.md` and `olympus.md` into `knowledge/`. See `knowledge/README.md`.

### 4. Run

```bash
python bot.py
```

## How it works

```
message in an allowed channel
  → last N messages pulled for context
  → system prompt (rules + one-pagers) + conversation → model
  → answer, or [[ESCALATE]] → pings staff role instead
```

## Notes

- **Model swap.** Every model call goes through `ask_llm()` in `llm.py`. Claude
  version is in a comment at the bottom of that file — swapping is one edit.
- **Escalation is deliberate.** The prompt tells the model to escalate rather
  than guess, so a thin `knowledge/` means lots of handoffs. Fix that by
  writing more knowledge, not by softening the prompt — a confidently wrong
  answer to a real user costs more than a handoff.
- **Cooldown.** One question per user per `USER_COOLDOWN_SECONDS`.
- **Keys.** `.env` only. Don't commit it — add it to `.gitignore`.

## Next

- **SigNoz** — let it answer from live telemetry ("is checkout erroring?").
  Add a `signoz.py` query helper and expose it as a tool call.
- Thread replies for long back-and-forths.
- Log every escalation; the recurring ones tell you what to write down next.
