"""Error-state TG alert for n8n error workflow (M1)."""

import sys

import config as Config
from alerts import telegram


def main() -> int:
    Config.load_env()
    message = f"⚠️ <b>bid-scan run FAILED</b>\n<pre>{sys.argv[1] if len(sys.argv) > 1 else 'unknown'}</pre>"
    token = __import__("os").environ.get("TG_TOKEN", "")
    chat_id = __import__("os").environ.get("TG_CHAT_ID", "")
    if token and chat_id:
        telegram.send(token, chat_id, message)
    print("error alert sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
