"""Minimal WhatsApp Cloud API sender used by the worker to push async results."""
import json
import urllib.request
import urllib.error

import config

MAX_WA_LEN = 4096


def send_text(to, body):
    return _send(to, {"type": "text", "text": {"body": (body or "")[:MAX_WA_LEN]}})


def send_long(to, body):
    ok = True
    for chunk in _chunks(body or "", MAX_WA_LEN):
        ok = _send(to, {"type": "text", "text": {"body": chunk}}) and ok
    return ok


def _send(to, message):
    if not config.WHATSAPP_TOKEN or not config.PHONE_NUMBER_ID:
        print("WhatsApp credentials missing; cannot notify", to)
        return False
    url = (f"https://graph.facebook.com/{config.GRAPH_API_VERSION}/"
           f"{config.PHONE_NUMBER_ID}/messages")
    payload = {"messaging_product": "whatsapp", "to": to}
    payload.update(message)
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     method="POST")
        req.add_header("Authorization", f"Bearer {config.WHATSAPP_TOKEN}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return True
    except urllib.error.HTTPError as e:
        print("WhatsApp send error:", e.code, e.read().decode("utf-8", "ignore")[:300])
    except urllib.error.URLError as e:
        print("WhatsApp network error:", repr(e))
    return False


def _chunks(text, size):
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > size:
            if cur:
                out.append(cur)
            while len(line) > size:
                out.append(line[:size]); line = line[size:]
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out
