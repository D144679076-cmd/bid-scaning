"""OpenAI-compatible chat client. Profile-based: BOTH Ollama backends
supported (client choice 2026-11-02):

- local: http://localhost:11434/v1  — free, private, no key needed
- cloud: https://ollama.com/v1      — same API shape, billed Ollama cloud,
                                       requires LLM_API_KEY in .env

Switch = one line in config.yaml (`llm.active: local|cloud`). Cloud works
with any OpenAI-compatible endpoint too (OpenRouter etc.) by swapping
base_url/model. No new dependencies (urllib).
"""

import json
import os
import re
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 60
DEFAULT_RETRIES = 2


def resolve_profile(cfg: dict, name: str | None = None) -> dict:
    llm = cfg["llm"]
    profiles = llm.get("profiles", {})
    active = name or llm.get("active", "local")
    if profiles and active in profiles:
        prof = dict(profiles[active])
    else:  # legacy flat keys
        prof = dict(llm)
    prof.setdefault("base_url", profiles.get("local", {}).get("base_url",
                     "http://localhost:11434/v1"))
    prof.setdefault("model", "qwen3:1.7b")
    key_name = prof.get("api_key_env") or ""
    key = os.environ.get(key_name, "") if key_name else ""
    if not prof["base_url"].startswith("http://localhost") and not key and key_name:
        raise RuntimeError(f"backend '{active}' needs {key_name} in .env (cloud)")
    prof["_api_key"] = key
    prof["_name"] = active
    return prof


def _chain(cfg: dict) -> list[str]:
    """Client rule 2026-11-02: CLOUD FIRST, local as automatic fallback.
    Chain from config; falls back to [cloud, local] when unset."""
    llm = cfg["llm"]
    order = llm.get("failover_order") or ["cloud", "local"]
    return [p for p in order if llm.get("profiles", {}).get(p)] or ["local"]


def chat(cfg: dict, messages: list[dict], *, response_json: bool = True) -> dict:
    """Try each backend in failover_order; config llm.active pins a single one
    when failover disabled. First successful backend wins."""
    if cfg["llm"].get("failover_enabled", True):
        chain = _chain(cfg)
    else:
        chain = [cfg["llm"].get("active", "local")]
    errors = []
    for name in chain:
        try:
            prof = resolve_profile(cfg, name)
        except RuntimeError as exc:  # cloud without .env key etc.
            errors.append(f"{name}: {exc}")
            continue
        try:
            result = _chat_one(cfg, prof, messages, response_json=response_json)
            print(f"[llm] backend used: {name}", flush=True)
            return result
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("LLM failover exhausted: " + " | ".join(errors))


def _chat_one(cfg: dict, prof: dict, messages: list[dict], *,
              response_json: bool = True) -> dict:
    url = prof["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": prof["model"],
        "messages": messages,
        "temperature": float(prof.get("temperature", cfg["llm"].get("temperature", 0.2))),
        "stream": False,
    }
    if response_json:
        payload["response_format"] = {"type": "json_object"}
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if prof["_api_key"]:
        headers["Authorization"] = f"Bearer {prof['_api_key']}"
    steps = int(prof.get("retry", DEFAULT_RETRIES))
    last_err = None
    for _ in range(max(1, steps)):
        try:
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(
                    request, timeout=int(prof.get("request_timeout", DEFAULT_TIMEOUT))) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            return _parse_json(content)
        except _PermanentJson as exc:
            raise RuntimeError(f"LLM returned non-JSON: {exc}") from exc
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError, OSError) as exc:
            last_err = exc
            continue
    raise RuntimeError(f"LLM unreachable after {steps} tries: {last_err}")


class _PermanentJson(Exception):
    pass


def _parse_json(content: str) -> dict:
    text = content.strip()
    # cloud models (gemma4 etc.) wrap JSON in markdown fences — tolerate
    fence = re.match(r"```[a-zA-Z]*\n?(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        pass
    m = re.search(r"\{.*\}", text, re.S)  # first balanced-ish object
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise _PermanentJson(exc) from exc
    raise _PermanentJson(json.JSONDecodeError("no JSON object in reply", text, 0))

