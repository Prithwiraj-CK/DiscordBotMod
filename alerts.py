"""Out-of-band alerts for when the bot itself is in trouble.

A log line on a box nobody is watching is not an alert. This posts to a Discord
webhook instead, because that is where the team already is.

Entirely optional: with ALERT_WEBHOOK_URL unset every call is a no-op and the
bot behaves exactly as it did before.

The URL is a secret - anyone holding it can post into that channel as the bot.
It lives in .env, never in this file.
"""

import logging
import os
import threading
import time

import requests

log = logging.getLogger("support-bot.alerts")

# The same alert repeating is one problem, not a hundred. A model outage would
# otherwise fire once per question and bury the channel it is trying to warn.
_MIN_SECONDS_BETWEEN_SAME_ALERT = 300.0
_MAX_TRACKED_KEYS = 200

_last_sent = {}
_lock = threading.Lock()


def _throttled(key):
    now = time.monotonic()
    with _lock:
        previous = _last_sent.get(key)

        # Explicitly "never sent" rather than a 0.0 default. monotonic() starts
        # near zero, so "now - 0.0 < window" is true for the whole first window
        # of the process, which would swallow every alert during the first five
        # minutes: precisely when a crash-looping bot needs to tell someone.
        if previous is not None and now - previous < _MIN_SECONDS_BETWEEN_SAME_ALERT:
            return True

        if len(_last_sent) >= _MAX_TRACKED_KEYS:
            for k in [k for k, sent in _last_sent.items()
                      if now - sent > _MIN_SECONDS_BETWEEN_SAME_ALERT]:
                del _last_sent[k]

        _last_sent[key] = now
        return False


def alert(text, key=None):
    """Post an operational alert, if a webhook is configured.

    key groups alerts for throttling. Pass a stable one ("llm-unavailable")
    so that the same recurring failure collapses into a single message.

    Safe to call from any thread.
    """
    url = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return

    if _throttled(key or text[:80]):
        return

    mention = os.getenv("ALERT_MENTION", "").strip()
    prefix = "{} ".format(mention) if mention else ""
    content = "{}:warning: **support bot**\n{}".format(prefix, text[:1500])

    try:
        response = requests.post(url, json={"content": content}, timeout=10)
        if response.status_code >= 400:
            log.warning(
                "Alert webhook returned %s - check ALERT_WEBHOOK_URL",
                response.status_code,
            )
    except requests.exceptions.RequestException:
        # Whatever happens, a failing alert must not take down the thing it is
        # reporting on. Log it and move on.
        log.exception("Could not send alert")
