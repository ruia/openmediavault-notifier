import re
from dataclasses import dataclass, field
from email.policy import default as _email_policy

EVENT_CLASSES = (
    ("monit-filesystem", "Monitoring: file systems"),
    ("monit-resource", "Monitoring: CPU, memory, load"),
    ("monit-process", "Monitoring: services"),
    ("smart", "S.M.A.R.T."),
    ("mdadm", "RAID"),
    ("updates", "Package updates"),
    ("cron", "Scheduled tasks"),
    ("auth", "Authentication"),
    ("system", "System"),
    ("unknown", "Other"),
)
EVENT_TITLES = dict(EVENT_CLASSES)
SEVERITIES = ("info", "warning", "critical")


@dataclass(frozen=True)
class Notification:
    subject: str
    body: str
    sender: str = ""
    recipients: tuple = ()
    date: str = ""
    event: str = "unknown"
    severity: str = "info"
    recovery: bool = False
    fields: dict = field(default_factory=dict)


_MONIT_SUBJECT = re.compile(r"^Monitoring (?P<action>\S+) -- (?P<event>.+) (?P<service>\S+)$")
_MONIT_FIELD = re.compile(r"^(Host|Date|Service|Event|Description):[ \t]*(.*)$", re.MULTILINE)
_MONIT_ACTION = re.compile(r"^This triggered the monitoring system to:[ \t]*(.*)$", re.MULTILINE)
_MONIT_RECOVERY = re.compile(r"succeeded|recover|^exists$|accessible|passed", re.IGNORECASE)
_SMART_SUBJECT = re.compile(
    r"^SMART (?:error|warning|notice) \((?P<type>[^)]+)\) detected on host:\s*(?P<host>\S+)",
    re.IGNORECASE,
)
_SMART_DEVICE = re.compile(r"^Device:\s*(?P<device>/dev/[^\s,]+)", re.MULTILINE)
_SMART_INFO = re.compile(r"^Device info:\s*\n(?P<info>.+)$", re.MULTILINE)
_MDADM_SUBJECT = re.compile(r"^(?P<event>[A-Za-z]+) event on (?P<device>/dev/[^:\s]+):(?P<host>\S+)$")
_UPDATES_SUBJECT = re.compile(r"^(?:(?P<count>\d+) package update\(s\) available|No package updates available)$")
_CRON_SUBJECT = re.compile(r"^Cron(?:\s*-\s*(?P<name>.+)|\s*<.*)?$")
_AUTH_SUBJECT = re.compile(
    r"locked users|log ?in|sudo|unauthori[sz]ed|two.factor|\b2fa\b|authentication|one.time password",
    re.IGNORECASE,
)
_SYSTEM_SUBJECTS = (
    (re.compile(r"errors were detected", re.IGNORECASE), "critical"),
    (re.compile(r"certificate expires", re.IGNORECASE), "warning"),
    (re.compile(r"reboot required", re.IGNORECASE), "warning"),
    (re.compile(r"\bUPS\b"), "warning"),
    (re.compile(r"pending configuration", re.IGNORECASE), "info"),
    (re.compile(r"scrub report", re.IGNORECASE), "info"),
    (re.compile(r"test message from", re.IGNORECASE), "info"),
)
_SMART_WARNING_TYPES = {"temperature", "temperaturechanged"}
_SMART_INFO_TYPES = {"emailtest"}
_MDADM_CRITICAL = {"fail", "failspare", "degradedarray", "sparesmissing", "devicedisappeared"}
_MDADM_INFO = {"rebuildfinished", "newarray", "movespare", "spareactive", "testmessage", "rebuildstarted"}
_MDADM_RECOVERY = {"rebuildfinished", "spareactive"}


def classify(subject, body, *, hostname="", sender="", recipients=(), date="") -> Notification:
    clean_subject = decode_subject(subject).strip()
    body = body or ""
    for matcher in _MATCHERS:
        result = matcher(clean_subject, body, hostname)
        if result:
            event, severity, recovery, fields = result
            break
    else:
        event, severity, recovery, fields = "unknown", "info", False, {}
    return Notification(
        subject=clean_subject,
        body=body,
        sender=sender,
        recipients=tuple(recipients),
        date=date,
        event=event,
        severity=severity,
        recovery=recovery,
        fields=fields,
    )


def decode_subject(subject) -> str:
    first_line = (subject or "").split("\n", 1)[0]
    decoded = str(_email_policy.header_factory("subject", first_line))
    return " ".join(decoded.split())


def test_notification(fqdn: str) -> Notification:
    return Notification(
        subject="Test notification",
        body=f"This is a test notification sent by openmediavault-notifier on {fqdn}.",
        event="system",
        severity="info",
        fields={"host": fqdn},
    )


def _classify_monit(subject, body, hostname):
    match = _MONIT_SUBJECT.match(subject)
    if not match:
        return None
    fields = {key.lower(): value.strip() for key, value in _MONIT_FIELD.findall(body)}
    action = _MONIT_ACTION.search(body)
    fields["action"] = action.group(1).strip() if action else match.group("action")
    fields.setdefault("service", match.group("service"))
    fields.setdefault("event", match.group("event"))
    service = fields["service"]
    event_name = fields["event"]
    recovery = bool(_MONIT_RECOVERY.search(event_name))
    if service == "rootfs" or service.startswith(("filesystem", "mountpoint")):
        event, severity = "monit-filesystem", "info" if recovery else "warning"
    elif event_name.startswith("Resource limit") or (hostname and service == hostname):
        event, severity = "monit-resource", "info" if recovery else "warning"
    else:
        event, severity = "monit-process", "info" if recovery else "critical"
    fields.pop("date", None)
    return event, severity, recovery, _non_empty(fields)


def _classify_smart(subject, body, hostname):
    match = _SMART_SUBJECT.match(subject)
    if not match:
        return None
    fields = {"type": match.group("type"), "host": match.group("host")}
    device = _SMART_DEVICE.search(body)
    if device:
        fields["device"] = device.group("device")
    info = _SMART_INFO.search(body)
    if info:
        fields["deviceinfo"] = info.group("info").strip()
    failure_type = fields["type"].lower()
    if failure_type in _SMART_INFO_TYPES:
        severity = "info"
    elif failure_type in _SMART_WARNING_TYPES:
        severity = "warning"
    else:
        severity = "critical"
    return "smart", severity, False, fields


def _classify_mdadm(subject, body, hostname):
    match = _MDADM_SUBJECT.match(subject)
    if not match:
        return None
    event_name = match.group("event")
    key = event_name.lower()
    if key in _MDADM_CRITICAL:
        severity = "critical"
    elif key in _MDADM_INFO:
        severity = "info"
    else:
        severity = "warning"
    fields = {"event": event_name, "device": match.group("device"), "host": match.group("host")}
    return "mdadm", severity, key in _MDADM_RECOVERY, fields


def _classify_updates(subject, body, hostname):
    match = _UPDATES_SUBJECT.match(subject)
    if not match:
        return None
    fields = {"count": match.group("count") or "0"}
    return "updates", "info", False, fields


def _classify_cron(subject, body, hostname):
    match = _CRON_SUBJECT.match(subject)
    if not match:
        return None
    name = (match.group("name") or "").strip()
    return "cron", "info", False, _non_empty({"name": name})


def _classify_auth(subject, body, hostname):
    if not _AUTH_SUBJECT.search(subject):
        return None
    return "auth", "warning", False, {}


def _classify_system(subject, body, hostname):
    for pattern, severity in _SYSTEM_SUBJECTS:
        if pattern.search(subject):
            return "system", severity, False, {}
    return None


def _non_empty(fields: dict) -> dict:
    return {key: value for key, value in fields.items() if value}


_MATCHERS = (
    _classify_monit,
    _classify_smart,
    _classify_mdadm,
    _classify_updates,
    _classify_cron,
    _classify_auth,
    _classify_system,
)
