"""Spam/noise filter (M1). Early hard filter — runs BEFORE classifier slot.

Module order kept: collector → dedup → spam filter → classifier → alert.
"""

import re


def _compiled(patterns: list[str]):
    return [re.compile(re.escape(p), re.IGNORECASE) for p in patterns if p]


def filter_noise(conn, items: list[dict], noise_patterns: list[str]) -> list[dict]:
    """Archive noise items in DB and return the survivors."""
    if not items:
        return []
    regexes = _compiled(noise_patterns)
    ids_by_url = {
        row["url"]: row["id"]
        for row in conn.execute(
            """SELECT id, url FROM requests
               WHERE status = 'lead' AND score IS NULL"""
        )
    }
    survivors = []
    for item in items:
        if any(rx.search(item["raw_text"]) for rx in regexes):
            request_id = ids_by_url.get(item["url"])
            if request_id:
                conn.execute(
                    """UPDATE requests
                       SET status = 'archived',
                           task_type = 'spam'
                       WHERE id = ?""",
                    (request_id,),
                )
        else:
            survivors.append(item)
    conn.commit()
    return survivors
