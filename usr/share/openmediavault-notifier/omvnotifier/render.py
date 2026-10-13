import html
import re
from dataclasses import dataclass

from .config import Config
from .message import Notification

MAX_BODY_LINES = 40
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)%")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z])(?=[A-Z])")
_FACT_LABELS = (
    ("label", "Disk"),
    ("device", "Device"),
    ("model", "Model"),
    ("serial", "Serial"),
    ("size", "Size"),
    ("mount_dir", "Mount point"),
    ("shares", "Shared folders"),
    ("tags", "Tags"),
    ("filesystems", "File systems"),
    ("deviceinfo", "Device info"),
    ("service", "Check"),
    ("event", "Event"),
    ("description", "Details"),
    ("action", "Action"),
    ("type", "Type"),
    ("name", "Task"),
    ("count", "Updates"),
    ("host", "Host"),
)


@dataclass(frozen=True)
class Rendered:
    title: str
    text: str
    html: str
    severity: str


def render(notification: Notification, config: Config) -> Rendered:
    headline = _HEADLINES.get(notification.event, _subject_headline)(notification)
    facts = _facts(notification)
    return Rendered(
        title=f"{config.hostname}: {headline}",
        text=_text(headline, facts, notification),
        html=_html(headline, facts, notification, config),
        severity=notification.severity,
    )


def body_excerpt(body: str, max_lines: int = MAX_BODY_LINES) -> str:
    lines = body.strip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    omitted = len(lines) - max_lines
    return "\n".join(lines[:max_lines]) + f"\n[... {omitted} more lines]"


def includes_body(notification: Notification) -> bool:
    return bool(notification.body.strip()) and not notification.event.startswith("monit")


def _filesystem_headline(notification: Notification) -> str:
    fields = notification.fields
    tags = fields.get("tags", "")
    name = (
        fields.get("label")
        or (tags.split(",")[0].strip() if tags else "")
        or fields.get("mount_dir")
        or fields.get("service", "file system")
    )
    event = fields.get("event", "")
    if fields.get("service", "").startswith("mountpoint") or event in ("Does not exist", "Exists"):
        return f"Mount point {name} is available again" if notification.recovery \
            else f"Mount point {name} is missing"
    if event.startswith("Filesystem flags"):
        return f"File system {name}: mount flags changed"
    if not event.startswith("Resource limit"):
        return f"File system {name}: {event.lower() or 'event'}"
    usage =_PERCENT.search(fields.get("description", ""))
    usage_text = f" ({usage.group(1)}% used)" if usage else ""
    if notification.recovery:
        return f"Disk {name} back under the space threshold{usage_text}"
    return f"Disk {name} is running out of space{usage_text}"


def _resource_headline(notification: Notification) -> str:
    description = notification.fields.get("description", "").lower()
    if "cpu" in description:
        kind = "CPU"
    elif "mem" in description:
        kind = "Memory"
    elif "loadavg" in description or "load average" in description:
        kind = "Load average"
    else:
        kind = "Resource"
    return f"{kind} back to normal" if notification.recovery else f"{kind} usage is high"


def _process_headline(notification: Notification) -> str:
    service = notification.fields.get("service", "unknown")
    event = notification.fields.get("event", notification.subject).lower()
    return f"Service {service}: {event}"


def _smart_headline(notification: Notification) -> str:
    fields = notification.fields
    failure_type = fields.get("type", "warning")
    if fields.get("model") and fields.get("device"):
        return f"SMART {failure_type} on {fields['model']} ({fields['device']})"
    return f"SMART {failure_type} on {fields.get('device', 'disk')}"


def _mdadm_headline(notification: Notification) -> str:
    fields = notification.fields
    event = _CAMEL_BOUNDARY.sub(" ", fields.get("event", "event")).lower()
    return f"RAID {fields.get('device', 'array')}: {event}"


def _cron_headline(notification: Notification) -> str:
    name = notification.fields.get("name")
    return f"Scheduled task '{name}' finished" if name else "Scheduled task finished"


def _subject_headline(notification: Notification) -> str:
    return notification.subject or "Notification"


_HEADLINES = {
    "monit-filesystem": _filesystem_headline,
    "monit-resource": _resource_headline,
    "monit-process": _process_headline,
    "smart": _smart_headline,
    "mdadm": _mdadm_headline,
    "cron": _cron_headline,
}


def _facts(notification: Notification) -> list:
    return [
        (label, notification.fields[key])
        for key, label in _FACT_LABELS
        if notification.fields.get(key)
    ]


def _text(headline: str, facts: list, notification: Notification) -> str:
    lines = [headline, f"Severity: {notification.severity}"]
    lines.extend(f"{label}: {value}" for label, value in facts)
    if includes_body(notification):
        lines.extend(["", body_excerpt(notification.body)])
    return "\n".join(lines)


def _html(headline: str, facts: list, notification: Notification, config: Config) -> str:
    rows = "".join(
        f"<tr><th align=\"left\" style=\"padding:2px 12px 2px 0\">{html.escape(label)}</th>"
        f"<td>{html.escape(value)}</td></tr>"
        for label, value in [("Severity", notification.severity), *facts]
    )
    parts = [
        f"<h2>{html.escape(headline)}</h2>",
        f"<table>{rows}</table>",
    ]
    if includes_body(notification):
        parts.append(f"<pre>{html.escape(body_excerpt(notification.body))}</pre>")
    if config.uiurl:
        parts.append(f"<p><a href=\"{html.escape(config.uiurl, quote=True)}\">Open openmediavault</a></p>")
    parts.append(
        f"<p style=\"color:#888\">Sent by openmediavault-notifier on {html.escape(config.fqdn)}</p>"
    )
    return "\n".join(parts)
