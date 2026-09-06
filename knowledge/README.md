# knowledge/

One `.md` per project. `valhalla.md` and `olympus.md` go here.

Every file in this folder is concatenated into the system prompt on every
question, so keep each one tight — roughly a page. Prefer the things users
actually ask about over exhaustive internal detail:

- what the project is, in two lines
- the main user-facing flows and what can go wrong in each
- common errors and what they actually mean
- known limitations and "no, that isn't supported"
- what genuinely needs a human (account issues, payments, outages)

Anything not written down here, the bot will escalate rather than guess.
That's the intended behaviour — the fastest way to make it smarter is to add
to these files, not to loosen the prompt.
