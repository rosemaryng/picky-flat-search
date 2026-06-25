"""Tiny HTTP helper (stdlib only, so the core has zero hard dependencies)."""
import json
import urllib.parse
import urllib.request

from .config import HTTP_UA


def get(url: str, headers: dict | None = None, timeout: int = 30) -> str:
    h = {"User-Agent": HTTP_UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def get_json(url: str, headers: dict | None = None, timeout: int = 30):
    return json.loads(get(url, headers, timeout))


def post_form(url: str, data: dict, headers: dict | None = None, auth: tuple | None = None,
              timeout: int = 30):
    h = {"User-Agent": HTTP_UA, "Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        h.update(headers)
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=h)
    if auth:
        import base64
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 30):
    h = {"User-Agent": HTTP_UA, "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def quote(s: str) -> str:
    return urllib.parse.quote(s)
