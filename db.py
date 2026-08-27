"""Thin Turso (libSQL) access layer over the HTTP API, shared by the webapp
and worker.

Talks to Turso via its stateless HTTP "pipeline" endpoint using only the
Python standard library — no database driver to install. SQL uses
libSQL/SQLite syntax; Postgres-style "%s" placeholders are accepted and
translated to libSQL "?" positional placeholders.
"""
import os
import json
import base64
import datetime
import urllib.request

import config


def _base_url():
    url = (config.TURSO_DATABASE_URL or "").strip()
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    elif url.startswith("wss://"):
        url = "https://" + url[len("wss://"):]
    elif url.startswith("ws://"):
        url = "http://" + url[len("ws://"):]
    return url.rstrip("/")


def _encode_arg(v):
    if v is None:
        return {"type": "null", "value": None}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode("ascii")}
    if isinstance(v, datetime.datetime):
        return {"type": "text", "value": v.isoformat(sep=" ")}
    if isinstance(v, datetime.date):
        return {"type": "text", "value": v.isoformat()}
    return {"type": "text", "value": str(v)}


def _decode_cell(cell):
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        try:
            return int(cell.get("value"))
        except (TypeError, ValueError):
            return cell.get("value")
    if t == "float":
        try:
            return float(cell.get("value"))
        except (TypeError, ValueError):
            return cell.get("value")
    if t == "blob":
        try:
            return base64.b64decode(cell.get("base64") or "")
        except Exception:
            return b""
    return cell.get("value")


def _run(sql, params=()):
    base = _base_url()
    if not base:
        raise RuntimeError("TURSO_DATABASE_URL not set")
    sql = sql.replace("%s", "?")
    body = {"requests": [
        {"type": "execute",
         "stmt": {"sql": sql, "args": [_encode_arg(p) for p in (params or ())]}},
        {"type": "close"},
    ]}
    req = urllib.request.Request(
        base + "/v2/pipeline",
        data=json.dumps(body).encode("utf-8"), method="POST")
    if config.TURSO_AUTH_TOKEN:
        req.add_header("Authorization", "Bearer " + config.TURSO_AUTH_TOKEN)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    results = data.get("results") or []
    if not results:
        raise RuntimeError("empty Turso response")
    first = results[0]
    if first.get("type") == "error":
        raise RuntimeError("Turso: " + str((first.get("error") or {}).get("message")))
    return first["response"]["result"]


def _rows(result):
    cols = [c.get("name") for c in result.get("cols", [])]
    return [dict(zip(cols, [_decode_cell(c) for c in row]))
            for row in result.get("rows", [])]


def query(sql, params=()):
    return _rows(_run(sql, params))


def one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=(), returning=False):
    result = _run(sql, params)
    if returning:
        return _rows(result)
    return result.get("affected_row_count", 0)


def scalar(sql, params=()):
    row = one(sql, params)
    if not row:
        return None
    return next(iter(row.values()))
