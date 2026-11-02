"""Telegram alerting (M1). Plain alert: source, link, excerpt. No LLM.

Secrets: TG_TOKEN + TG_CHAT_ID from .env only (AGENTS.md). Send is a
notification to our own chat — this is NOT contacting any platform/source.
"""

import html
import json
import os
import urllib.request

API_URL = "https://api.telegram.org/bot{token}/sendMessage"

MAX_EXCERPT = 700


def format_message(item: dict) -> str:
    posted = item.get("posted_at") or "unknown time"
    excerpt = html.escape(item["raw_text"][:MAX_EXCERPT])
    body = (
        f"<b>🆕 Request ({html.escape(item['source'])})</b>\n"
        f"👤 {html.escape(item.get('author') or '')}\n"
        f"🕒 {html.escape(str(posted))}\n\n"
        f"{excerpt}\n\n"
        f"🔗 {html.escape(item['url'])}"
    )
    return body


def send(token: str, chat_id: str, message: str) -> dict:
    payload = json.dumps(
        {"chat_id": chat_id, "text": message, "parse_mode": "HTML",
         "disable_web_page_preview": True}
    ).encode("utf-8")
    request = urllib.request.Request(
        API_URL.format(token=token),
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def alert(conn, items: list[dict]) -> int:
    """Alert for each item; marks sent_at. Returns count sent."""
    token = os.environ.get("TG_TOKEN", "")
    chat_id = os.environ.get("TG_CHAT_ID", "")
    if not token or not chat_id:
        raise RuntimeError("TG_TOKEN / TG_CHAT_ID missing — copy .env.example to .env")
    sent = 0
    for item in items:
        send(token, chat_id, format_message(item))
        sent += 1
    if items:
        ids_by_url = {row["url"]: row["id"] for row in conn.execute(
            "SELECT id, url FROM requests WHERE status = 'lead'")}
        for item in items:
            request_id = ids_by_url.get(item["url"])
            if request_id:
                conn.execute(
                    "UPDATE requests SET sent_at = datetime('now') WHERE id = ?",
                    (request_id,),
                )
        conn.commit()
    return sent
