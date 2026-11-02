"""Telegram alerting (M1). Plain alert: source, link, excerpt. No LLM.

Secrets: TG_TOKEN + TG_CHAT_ID from .env only (AGENTS.md). Send is a
notification to our own chat — this is NOT contacting any platform/source.
"""

import html
import json
import os
import urllib.request

API_URL = "https://api.telegram.org/bot{token}/{method}"

MAX_EXCERPT = 700

# Buttons (M2): callbacks update requests.status via alerts/callbacks.py
CALLBACKS = {
    "approve": "✅ Approve",
    "reject": "❌ Reject",
    "open": "🔗 Open source",
}


def format_message(item: dict) -> str:
    posted = item.get("posted_at") or "unknown time"
    excerpt = html.escape(item["raw_text"][:MAX_EXCERPT])
    score = item.get("score")
    head = f"<b>🆕 Request ({html.escape(item['source'])})</b>\n"
    if score is not None:
        request_type = html.escape(item.get("request_type") or "")
        reason = html.escape(str(item.get("reason") or ""))
        head += (f"⭐ Score: {score}/10 · {request_type}\n"
                 f"🧠 {reason}\n")
    head += f"👤 {html.escape(item.get('author') or '')}\n"
    if item.get("budget"):
        head += f"💰 {html.escape(str(item['budget']))}\n"
    if item.get("deadline"):
        head += f"⏳ {html.escape(str(item['deadline']))}\n"
    head += f"🕒 {html.escape(str(posted))}\n\n"
    return head + f"{excerpt}\n\n🔗 {html.escape(item['url'])}"


def keyboard(item: dict):
    """Inline keyboard payload for a scored/request; only for real leads."""
    request_id = item.get("db_id")
    rows = [[
        {"text": "✅ Approve", "callback_data": f"approve:{request_id}"},
        {"text": "❌ Reject", "callback_data": f"reject:{request_id}"},
        {"text": "🔗 Open", "url": item["url"]},
    ]]
    if item.get("score") is not None and item["score"] < 6:
        return None  # digested items: no buttons
    return rows


def call_api(token: str, method: str, payload: dict) -> dict:
    request = urllib.request.Request(
        API_URL.format(token=token, method=method),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send(token: str, chat_id: str, message: str, *, disable_preview=True) -> dict:
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    if disable_preview:
        payload["disable_web_page_preview"] = True
    return call_api(token, "sendMessage", payload)


def send_with_buttons(token: str, chat_id: str, item: dict) -> dict:
    payload = {"chat_id": chat_id, "text": format_message(item),
               "parse_mode": "HTML", "disable_web_page_preview": True}
    kb = keyboard(item)
    if kb:
        payload["reply_markup"] = {"inline_keyboard": kb}
    return call_api(token, "sendMessage", payload)


def alert(conn, items: list[dict], min_interval_seconds: int = 8,
          max_per_run: int = 15) -> int:
    """Alert for each item; marks sent_at. Paced to avoid Telegram flooding.

    Rate limit: one message per min_interval_seconds, at most max_per_run
    per cycle. Unsent items stay status=lead and go out in the next run —
    no data lost, chat stays readable.
    """
    token = os.environ.get("TG_TOKEN", "")
    chat_id = os.environ.get("TG_CHAT_ID", "")
    if not token or not chat_id:
        raise RuntimeError("TG_TOKEN / TG_CHAT_ID missing — copy .env.example to .env")
    import time
    sent = 0
    for item in items[:max_per_run]:
        if sent:
            time.sleep(min_interval_seconds)
        try:
            telegram_send = send_with_buttons(token, chat_id, item)
        except Exception as exc:  # network hiccup: leave unsent, retry next run
            print(f"[warn] tg send failed for {item['url']}: {exc}", flush=True)
            continue
        sent += 1
    if items[:max_per_run]:
        ids_by_url = {row["url"]: row["id"] for row in conn.execute(
            "SELECT id, url FROM requests WHERE status = 'lead'")}
        for item in items[:max_per_run]:
            request_id = ids_by_url.get(item["url"])
            if request_id:
                conn.execute(
                    "UPDATE requests SET sent_at = datetime('now') WHERE id = ?",
                    (request_id,),
                )
        conn.commit()
    return sent
