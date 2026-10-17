"""One-off Telegram delivery check: send ONE message with the service's own Telegram client and settings.

    python -m sw_agents.telegram_check /home/linux1/sw/agents2.env

Reads the same env file as the sw-agents2 unit (KEY=VALUE lines; the process environment wins),
sends "SentinelWard test: delivery check" to the IT chat (SW_TELEGRAM_IT_CHAT), or to the charge
nurse's chat if no IT chat is set, and prints "ok" or "failed: <reason>". It never prints the token,
chat IDs or any other setting value. Exit code 0 = delivered (Telegram returned a message_id).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .clock import RealClock
from .config import ConfigError, Settings
from .telegram import Telegram

TEXT = "SentinelWard test: delivery check"


def read_env_file(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]  # systemd EnvironmentFile quoting
        env[key.strip()] = value
    return env


def main(argv: list[str] | None = None, http=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        env = read_env_file(argv[0]) if argv else {}
    except OSError as exc:
        print(f"failed: env file unreadable ({type(exc).__name__})")
        return 2
    env.update(os.environ)
    try:
        s = Settings.from_env(env)
    except ConfigError as exc:
        print(f"failed: bad setting ({exc})")  # ConfigError messages never contain values
        return 2
    if not s.telegram_token:
        print("failed: SW_TELEGRAM_BOT_TOKEN is not set (telegram off)")
        return 1
    if s.telegram_it_chat is not None:
        chat, who = s.telegram_it_chat, "IT chat"
    elif s.charge_nurse in s.telegram_chats:
        chat, who = s.telegram_chats[s.charge_nurse], f"{s.charge_nurse} chat"
    else:
        print("failed: no IT chat and no chat for the charge nurse")
        return 1
    tg = Telegram(s.telegram_token, RealClock(), http=http)
    try:
        ok = tg.send_test(chat, TEXT)
    finally:
        tg.close()
    print(f"ok: delivered to the {who} (sent={tg.sent}, failed={tg.failed})" if ok
          else f"failed: Telegram did not accept the message for the {who} (see the log line above)")
    return 0 if ok else 1


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    raise SystemExit(main())
