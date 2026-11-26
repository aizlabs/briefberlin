"""Host-only editorial scheduling and review commands. All successful responses are JSON."""

import argparse
import json
import sys

from . import dispatch, review


def add_commands(commands: argparse._SubParsersAction):
    for name in ("dispatch-tick", "dispatch-status", "publish-pause", "publish-resume",
                 "review-pending", "review-resend", "review-action"):
        commands.add_parser(name)
    mode = commands.add_parser("dispatch-mode")
    mode.add_argument("mode", choices=("observe", "live"))
    ack = commands.add_parser("review-delivered")
    ack.add_argument("--request", required=True)
    ack.add_argument("--receipt", required=True)


def execute(conn, args):
    name = args.command
    if name == "dispatch-tick":
        return dispatch.tick(conn)
    if name == "dispatch-status":
        return dispatch.status(conn)
    if name == "dispatch-mode":
        if args.mode == "live":
            if not dispatch.Policy.load().editor_allowlist:
                raise ValueError("configure the authorized editor route before going live")
            review.callback_key()
        return dispatch.configure(conn, mode=args.mode)
    if name in {"publish-pause", "publish-resume"}:
        return dispatch.configure(conn, paused=name == "publish-pause")
    if name in {"review-pending", "review-resend"}:
        result = review.pending(conn)
        if name == "review-pending" and result.get("delivery_count"):
            result["deliver"] = False
        return result
    if name == "review-delivered":
        return review.delivered(conn, request_id=args.request, receipt=args.receipt)
    if name == "review-action":
        raw = sys.stdin.read(12001)
        if len(raw) > 12000:
            raise ValueError("callback exceeds 12000 characters")
        return review.signed_action(conn, json.loads(raw))
    raise ValueError("unknown dispatch command")
