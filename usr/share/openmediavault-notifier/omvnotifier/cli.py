import argparse
import json
import logging
import logging.handlers
import os
import re
import sys

from . import channels, enrich, message, render
from . import config as config_module

LOG = logging.getLogger("omv-notifier")
SYSLOG_SOCKET = "/dev/log"
_OWN_MESSAGE = re.compile(r"\A--={15}\d+==\n(?:[^\n]+\n)*?X-OMV-Notifier: 1\n")


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(to_stderr=args.command != "dispatch")
    try:
        return args.func(args)
    except Exception:  # noqa: BLE001 - last line of defence, must never break mail delivery
        LOG.exception("unhandled error in %s", args.command)
        return 0 if args.command == "dispatch" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omv-notifier",
        description="Forward openmediavault notifications to chat services and email.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dispatch = subparsers.add_parser("dispatch", help="Notification sink entry point.")
    dispatch.add_argument("message_file")
    dispatch.add_argument("sender", nargs="?", default="")
    dispatch.add_argument("recipient", nargs="*")
    dispatch.set_defaults(func=cmd_dispatch)

    test = subparsers.add_parser("test", help="Send a test notification to a channel.")
    test.add_argument("uuid")
    test.set_defaults(func=cmd_test)

    events = subparsers.add_parser("events", help="Print the known event classes as JSON.")
    events.set_defaults(func=cmd_events)
    return parser


def setup_logging(to_stderr: bool) -> None:
    LOG.setLevel(logging.INFO)
    LOG.handlers.clear()
    if os.path.exists(SYSLOG_SOCKET):
        handler = logging.handlers.SysLogHandler(
            address=SYSLOG_SOCKET, facility=logging.handlers.SysLogHandler.LOG_DAEMON
        )
        handler.ident = "omv-notifier: "
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOG.addHandler(handler)
    if to_stderr or not LOG.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        LOG.addHandler(handler)


def cmd_dispatch(args) -> int:
    try:
        config = config_module.load()
    except config_module.ConfigError as exc:
        LOG.error("%s", exc)
        return 0
    if not config.enable:
        return 0
    subject = os.environ.get("OMV_NOTIFICATION_SUBJECT", "")
    date = os.environ.get("OMV_NOTIFICATION_DATE", "")
    try:
        with open(args.message_file, encoding="utf-8", errors="replace") as handle:
            body = handle.read()
    except OSError as exc:
        LOG.error("cannot read message file %s: %s", args.message_file, exc)
        return 0
    if _OWN_MESSAGE.match(body):
        LOG.info("ignoring message sent by omv-notifier itself (%s)", subject)
        return 0
    recipients = tuple(
        part.strip() for item in args.recipient for part in item.split(",") if part.strip()
    )
    notification = message.classify(
        subject, body, hostname=config.hostname, sender=args.sender,
        recipients=recipients, date=date,
    )
    targets = [
        channel for channel in config.channels
        if channel.accepts(notification.event, notification.recovery)
    ]
    if not targets:
        LOG.info("no channel accepts event '%s' (%s)", notification.event, notification.subject)
        return 0
    notification = enriched(notification, config)
    rendered = render.render(notification, config)
    for channel in targets:
        try:
            channels.deliver(channel, rendered, config)
        except channels.DeliveryError as exc:
            LOG.error("channel '%s' (%s): %s", channel.name, channel.type, exc)
        except Exception:  # noqa: BLE001 - one broken channel must not keep the alert from the others
            LOG.exception("channel '%s' (%s): unexpected error", channel.name, channel.type)
        else:
            LOG.info("delivered '%s' event to channel '%s'", notification.event, channel.name)
    return 0


def cmd_test(args) -> int:
    try:
        config = config_module.load()
    except config_module.ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    channel = config.channel(args.uuid)
    if channel is None:
        print(f"channel '{args.uuid}' not found in the deployed configuration", file=sys.stderr)
        return 1
    rendered = render.render(message.test_notification(config.fqdn), config)
    try:
        channels.deliver(channel, rendered, config)
    except channels.DeliveryError as exc:
        print(f"channel '{channel.name}' ({channel.type}): {exc}", file=sys.stderr)
        return 1
    print(f"Test notification sent to '{channel.name}' ({channel.type}).")
    return 0


def cmd_events(args) -> int:
    print(json.dumps([{"value": key, "text": title} for key, title in message.EVENT_CLASSES]))
    return 0


def enriched(notification, config):
    if notification.event not in enrich.ENRICHED_EVENTS:
        return notification
    try:
        devices = enrich.list_block_devices()
    except enrich.EnrichError as exc:
        LOG.warning("block device lookup failed, sending without disk details: %s", exc)
        devices = []
    return enrich.enrich(notification, config, devices)
