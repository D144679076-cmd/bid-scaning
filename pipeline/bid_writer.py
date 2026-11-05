"""Bid writer (M3). LLM draft per request using profile row + per-source
templates (docs/PLAN.md §5). Drafts stored into requests.draft_text.

Manual send everywhere — approve button (M2) just marks readiness; the
human copies the draft into the platform (AGENTS.md: never auto-send).
"""

import json
import sqlite3
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

PROMPT_TMPL = """You write the service offer for {name} — an automation /
custom-software freelancer/agency. Write a reply the AUTHOR of the request
would receive as a first response.

LANGUAGE: reply in the language below: {language}. If you are not sure, use {tone}.
TONE: {tone}.

HARD RULES (profile):
{hard_rules}
- ≤ {max_chars} characters total for this draft.
- Mention ONLY facts from your PROFILE facts below — invent nothing.

PROFILE FACTS:
- name: {name}
- portfolio: {portfolio}
- specialties: {specialties}
- past work: {past_work}
- pricing: {pricing}
- service disclosure line to include somewhere: "{name} — I do this kind of build" (adapt wording)
- contact: {contact_hint}

SOURCE-SPECIFIC STYLE ({source_style_strength}):
{source_style}

REQUEST CONTEXT (data extracted automatically):
- platform: {source}
- type: {request_type}
- tools hinted: {tools}
- budget signal: {budget}
- deadline: {deadline}
- buying-intent reason: {reason}
- AUTHOR'S POST (verbatim, may be long — reply to ITS specifics):
'''
{post}
'''

CLIENT NOTE (optional refinement typed by the owner): {client_note}

OUTPUT: STRICT JSON {{"draft": "the full reply text"}} — no markdown fences."""

SOURCE_STYLES = {
    "reddit": ("strong", "- helpful-answer style: 2-line sketch of the solution FIRST,\n"
                "  genuinely answer the question, then ONE line offering to build it,\n"
                "  plus service disclosure; public thread reply, never cold-DM\n"
                "- max_chars 900"),
    "make": ("strong", "- short pitch + portfolio link + matching fixed-price tier lookup\n- max_chars 700"),
    "facebook": ("strong", "- casual 1–2 sentences + light emoji OK + end with a question hook;\n  draft is paste-ready\n"
                "- M9: tool-market posts are often Vietnamese teencode\n"
                "  (e/ae/bác/ib/zalo/tele) — match the author's language and\n"
                "  chat register; contact = the profile.contact_hint\n- max_chars 400"),
    "upwork": ("strong", "- standard proposal: 1 intro line referencing their exact pain,\n"
               "  3-bullet plan, price range, CTA question\n- max_chars 1200"),
    "x": ("strong", "- one value statement + question END; MUST fit 280 characters\n- max_chars 280"),
    "linkedin": ("strong", "- one value statement + short plan; professional but plain\n- max_chars 500"),
}
DEFAULT_STYLE = ("strong", "- one value statement + one question\n- max_chars 700")


def load_profile(conn: sqlite3.Connection, yaml_path: str | None = None) -> dict:
    """Profile from profile.yaml FIRST (config-file driven: edit the file,
    next cycle drafts from it — no reseed needed). DB row = fallback when
    the file is missing, unparseable, or still contains placeholders."""
    path = Path(yaml_path or Path(__file__).resolve().parent.parent
                / "profile.yaml")
    try:
        prof = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        prof = {}
    if prof and "REPLACE-ME" not in json.dumps(prof, ensure_ascii=False):
        return {
            "name": prof.get("name", ""),
            "portfolio": prof.get("portfolio_url", ""),
            "specialties": prof.get("specialties", []),
            "past_work": json.dumps(prof.get("past_work", []),
                                    ensure_ascii=False),
            "pricing": json.dumps(prof.get("pricing_tiers", []),
                                  ensure_ascii=False),
            "tone": prof.get("tone", "casual-professional"),
            "contact_hint": prof.get("contact_hint", ""),
        }
    row = conn.execute(
        """SELECT name, portfolio_url, past_work, pricing_tiers, tone,
                  contact_hint
           FROM profile WHERE id = 1""").fetchone()
    if not row:
        return {}
    return {
        "name": row["name"] or "",
        "portfolio": row["portfolio_url"] or "",
        "specialties": [],  # specialties live in profile.yaml only
        "past_work": row["past_work"] or "[]",
        "pricing": row["pricing_tiers"] or "[]",
        "tone": row["tone"] or "casual-professional",
        "contact_hint": row["contact_hint"] or "DM via platform",
    }


def build_prompt(cfg, prof: dict, item: dict) -> str:
    style_key = item["source"] if item["source"] in SOURCE_STYLES else "reddit"
    _k, style = SOURCE_STYLES.get(style_key, DEFAULT_STYLE)
    source = item["source"]
    max_chars = {
        "reddit": 900, "make": 700, "facebook": 400, "upwork": 1200,
        "x": 280, "linkedin": 500,
    }.get(source, 700)
    try:
        hard_rules = (yaml.safe_load(
            (Path(__file__).resolve().parent.parent / "profile.yaml")
            .read_text(encoding="utf-8")) or {}).get("hard_rules", [])
    except (OSError, yaml.YAMLError):
        hard_rules = ["keep it honest and short"]
    return PROMPT_TMPL.format(
        name=prof.get("name") or "a service provider",
        language=item.get("language") or item.get("lang") or "the author's",
        tone=prof.get("tone", ""),
        hard_rules="\n".join(f"- {r}" for r in hard_rules),
        specialties="\n".join(f"- {s}" for s in prof.get("specialties", []))
        or "none listed",
        past_work=prof.get("past_work", "[]"),
        pricing=prof.get("pricing", "[]"),
        portfolio=prof.get("portfolio", ""),
        contact_hint=prof.get("contact_hint", "DM via platform"),
        source_style_strength=SOURCE_STYLES.get(source, DEFAULT_STYLE)[0],
        source_style=style,
        source=source,
        request_type=item.get("request_type") or "other software",
        tools=", ".join(item.get("tools", []) or []) or "none named",
        budget=item.get("budget") or "not stated",
        deadline=item.get("deadline") or "not stated",
        reason=item.get("reason") or "",
        post=item.get("raw_text", "")[:4000],
        max_chars=max_chars,
        client_note=item.get("client_note") or "none",
    )


def write_bid(cfg, client, prof: dict, item: dict) -> str:
    """LLM → draft text; raises RuntimeError on empty draft."""
    from llm import client as _c  # avoid circular import in tests
    if client is None:
        client = _c.chat
    messages = [
        {"role": "system", "content": "You write honest, short, service partner replies. Strict JSON only."},
        {"role": "user", "content": build_prompt(cfg, prof, item)},
    ]
    out = client(cfg, messages)
    draft = (out.get("draft") or "").strip()
    if not draft:
        raise RuntimeError("draft empty")
    # Character safety-net per template rule
    cap = {"facebook": 500, "x": 280}.get(item["source"], 4000)
    if len(draft) > cap:
        draft = draft[:cap].rstrip() + "…"
    return draft


def persist_draft(conn, item: dict, draft: str) -> None:
    conn.execute(
        """UPDATE requests SET draft_text = ?, status = 'drafted'
           WHERE id = ?""",
        (draft, item["db_id"]))
    conn.commit()

# NOTE (flow, per docs/phase-m3.md):
# - ✏️ Edit from TG stores 'edited' status + note; pipeline re-drafts using
#   that note (client_note), then status → 'approved' draft-ready.
# - ✅ Approve → status 'approved' → M4/M5's follow-up tracker + digest cover
#   the rest. Sending stays 100 % manual-copy everywhere (AGENTS.md).
