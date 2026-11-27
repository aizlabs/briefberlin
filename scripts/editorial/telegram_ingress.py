"""Authenticate Telegram webhook updates before passing the original bytes to OpenClaw."""

import hmac
import http.client
import json
import os
import sqlite3
import subprocess
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import manual_drafts, publication_host
from .db import connect

LIMIT = 256_000
HEADER = "X-Telegram-Bot-Api-Secret-Token"


def decision(conn, update, account):
    """Called only after the request's bot-specific TLS webhook secret was checked."""
    message = update.get("message") or {}
    control = (update.get("callback_query") or {}).get("data", "")
    if control.startswith(("bb-publish:", "bb-discard:")) or message.get("text", "").strip().lower() in {
        "publish", "discard"
    }:
        try:
            with publication_host.locked(publication_host.state_dir(conn), "manual"):
                manual_drafts.receive_update(conn, update, account)
        except ValueError:
            # A stale or unbound decision creates no receipt. The forwarded message lets
            # the skill explain how to reply to the active control.
            pass
    elif control.startswith("bb-review:"):
        handler = os.environ.get("BB_REVIEW_INGRESS")
        if not handler:
            raise OSError("configure BB_REVIEW_INGRESS before enabling review controls")
        result = subprocess.run([handler], input=json.dumps(update).encode(), timeout=30,
                                stdout=subprocess.PIPE, check=True)
        answer = result.stdout.decode().strip()
        query_id = update["callback_query"].get("id")
        if not isinstance(query_id, str) or not query_id or not 1 <= len(answer) <= 200:
            raise ValueError("invalid review acknowledgment")
        return {"method": "answerCallbackQuery", "callback_query_id": query_id,
                "text": answer, "show_alert": True}


def relay(raw, url, secret):
    endpoint = urlsplit(url)
    if (endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "::1"}
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError("OpenClaw upstream must be a fixed loopback HTTP webhook")
    with closing(http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=30)) as conn:
        conn.request("POST", endpoint.path or "/", body=raw, headers={HEADER: secret, "Content-Type": "application/json"})
        with conn.getresponse() as response:
            if not 200 <= response.status < 300:
                raise OSError("OpenClaw webhook delivery pending")
            body = response.read(LIMIT + 1)
            if len(body) > LIMIT:
                raise OSError("OpenClaw webhook response too large")
            return body, response.getheader("Content-Type") or "application/json"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.connection.settimeout(35)
        if self.path != "/telegram" or not hmac.compare_digest(
            self.headers.get(HEADER, "").encode(), self.server.secret.encode()
        ):
            self.send_error(403)
            return
        try:
            length = int(self.headers["Content-Length"] or "0")
            if self.headers.get("Transfer-Encoding") or not 0 < length <= LIMIT:
                raise ValueError("invalid update length")
            raw = self.rfile.read(length)
            update = json.loads(raw)
            if len(raw) != length or not isinstance(update, dict) or type(update.get("update_id")) is not int:
                raise ValueError("invalid update")
            with closing(connect()) as conn:
                receipt = decision(conn, update, self.server.account)
            if receipt is None:
                body, content_type = relay(raw, self.server.upstream, self.server.upstream_secret)
            else:
                body, content_type = json.dumps(receipt).encode(), "application/json"
        except (ValueError, TypeError, AttributeError):
            self.send_error(400)
            return
        except (OSError, sqlite3.Error, subprocess.SubprocessError, http.client.HTTPException):
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def main():
    os.umask(0o077)
    secret = os.environ["BB_TELEGRAM_WEBHOOK_SECRET"]
    if len(secret) < 32:
        raise ValueError("configure a high-entropy Telegram webhook secret of 32 or more characters")
    with ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("BB_INGRESS_PORT", 8789))), Handler) as server:
        server.secret = secret
        server.account = os.environ["BB_TELEGRAM_ACCOUNT"]
        server.upstream = os.environ["BB_OPENCLAW_WEBHOOK"]
        server.upstream_secret = os.environ.get("BB_OPENCLAW_WEBHOOK_SECRET", secret)
        server.serve_forever()
