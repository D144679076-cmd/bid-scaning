"""Statistics helpers for /stats, /digest and the CLI (M9 2026-11-06).

Pure read-only SQLite aggregates over `requests`. No LLM, no sends.

"Type" axis: task_type rolled up into web-build vs tool-build
(web/app dev = web-build; automation | script/bot | scraper | integration/SaaS
| other software = tool-build). "Topic" axis: request purpose label
(`topic` column, classifier prompt M9; old rows stay blank → unlisted)
plus the `tools` JSON array as a secondary device/platform ranking.

All helpers take `days` (0 = no time window, i.e. all time).
"""

WEB_BUILD = "web/app dev"

WEB_GROUP = "web-build"
TOOL_GROUP = "tool-build"


def _window(days: int) -> str:
    if not days or days <= 0:
        return ""
    return f" AND created_at >= datetime('now', '-{int(days)} days')"


def _group_of(task_type: str | None) -> str:
    return WEB_GROUP if (task_type or "").strip() == WEB_BUILD else TOOL_GROUP


def totals(conn, days: int = 0) -> dict:
    """Whole-status picture for the window: status counts + lead totals."""
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM requests WHERE 1=1" + _window(days)
        + " GROUP BY status").fetchall()
    by_status = {r[0]: r[1] for r in rows}
    return {
        "by_status": by_status,
        "total": sum(by_status.values()),
        "leads": sum(v for k, v in by_status.items()
                     if k in ("lead", "drafted", "approved", "sent",
                              "replied", "won")),
        "low": by_status.get("low", 0),
        "unpaid": by_status.get("unpaid", 0),
    }


def by_group(conn, days: int = 0) -> dict:
    """web-build vs tool-build counts (skipped 'not a request' posts)."""
    rows = conn.execute(
        "SELECT task_type, COUNT(*) FROM requests"
        " WHERE task_type IS NOT NULL AND task_type != 'not a request'"
        + _window(days) + " GROUP BY task_type").fetchall()
    groups: dict[str, int] = {WEB_GROUP: 0, TOOL_GROUP: 0}
    for r in rows:
        groups[_group_of(r[0])] += r[1]
    return groups


def purposes(conn, days: int = 0, limit: int = 10) -> list[tuple[str, str, int]]:
    """Top `topic` purpose labels as (topic, task_type, count).

    Ties: higher avg intent score first (uses AVG over same rows that are
    grouped — computed directly here so only one query runs).
    """
    rows = conn.execute(
        "SELECT topic, task_type, COUNT(*) n, AVG(score) s"
        " FROM requests WHERE topic IS NOT NULL AND topic != ''"
        + _window(days) + " GROUP BY topic ORDER BY n DESC, s DESC, topic"
        " LIMIT ?", (limit,)).fetchall()
    return [(r["topic"], r["task_type"], r["n"]) for r in rows]


def by_source(conn, days: int = 0) -> list[tuple[str, int, float]]:
    """(source, count, avg intent score) per source, count desc."""
    rows = conn.execute(
        "SELECT source, COUNT(*) n, AVG(score) s FROM requests WHERE 1=1"
        + _window(days) + " GROUP BY source ORDER BY n DESC, source").fetchall()
    return [(r["source"], r["n"], r["s"] or 0.0) for r in rows]


def top_tools(conn, days: int = 0, limit: int = 8) -> list[tuple[str, int]]:
    """Rank values inside the `tools` JSON array (SQLite JSON1)."""
    try:
        rows = conn.execute(
            "SELECT value t, COUNT(*) n FROM requests,"
            " json_each(requests.tools) WHERE value IS NOT NULL"
            " AND TRIM(value) != ''" + _window(days)
            + " GROUP BY t ORDER BY n DESC, t LIMIT ?", (limit,)).fetchall()
        return [(r["t"], r["n"]) for r in rows]
    except Exception:
        return []


def build_report(conn, days: int = 7, section: str | None = None) -> str:
    """/stats message; `section` = 'source'|'type'|'topic' → one full axis."""
    t = totals(conn, days)

    def ratio(cnt: int) -> str:
        return f"{100 * cnt / t['total']:.0f}%" if t['total'] else "--"

    lines = [f"📈 bid-scan stats{'' if days == 0 else f' — last {days}d'}"
             f" · total {t['total']}"
             f" · leads {t['leads']} · low {t['low']} · unpaid {t['unpaid']}"]
    if section == "source":
        lines.append("── by source (count · avg score)")
        for s, n, s_avg in by_source(conn, days):
            lines.append(f"{s}: {n} · {s_avg:.1f}" if n else f"{s}: 0")
    elif section == "type":
        lines.append("── web-build vs tool-build")
        for g, n in by_group(conn, days).items():
            lines.append(f"{g}: {n} ({ratio(n)})")
    elif section == "topic":
        lines.append("── main purposes (topic share · n · build group)")
        for topic, task, n in purposes(conn, days):
            lines.append(f"{topic}: {n} [{_group_of(task)}]")
    else:
        groups = by_group(conn, days)
        tg, wg = groups[TOOL_GROUP], groups[WEB_GROUP]
        total_g = tg + wg
        if total_g:
            lines.append(f"── builds asked: tool-build {tg} ({100*tg//total_g}%)"
                         f" · web-build {wg} ({100*wg//total_g}%)")
        lines.append("── by source (count · avg score)")
        for s, n, s_avg in by_source(conn, days)[:6]:
            lines.append(f"{s}: {n} · {s_avg:.1f}" if n else f"{s}: 0")
        lines.append("── main purposes")
        for topic, task, n in purposes(conn, days, limit=5):
            lines.append(f"{topic}: {n} [{_group_of(task)}]")
        tools = top_tools(conn, days)
        if tools:
            lines.append("── top tools/platforms")
            lines.append(" · ".join(f"{name} {n}" for name, n in tools))
    return "\n".join(lines)


def main() -> int:
    """CLI: python -m alerts.stats [days|source|type|topic] [section]"""
    import sys
    import os
    days, section = 7, None
    if len(sys.argv) > 1 and sys.argv[1] in ("source", "type", "topic"):
        section = sys.argv[1]
        if len(sys.argv) > 2:
            try:
                days = max(0, int(sys.argv[2]))
            except ValueError:
                print(__doc__, file=sys.stderr)
                return 2
    elif len(sys.argv) > 1:
        try:
            days = max(0, int(sys.argv[1]))
        except ValueError:
            print("usage: python -m alerts.stats [days] | [source|type|topic] [days]",
                  file=sys.stderr)
            return 2
    from db import connect
    conn = connect(os.environ.get("BIDSCAN_DB", "data/bidscan.db"))
    try:
        print(build_report(conn, days=days, section=section))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
