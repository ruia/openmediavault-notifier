import json
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from .config import Channel, Config, EmailSettings
from .render import Rendered

HTTP_TIMEOUT = 5
SMTP_TIMEOUT = 15
USER_AGENT = "openmediavault-notifier"
LOCAL_ENVELOPE_USER = "openmediavault-notifier"
DISCORD_COLORS = {"info": 0x2ECC71, "warning": 0xF1C40F, "critical": 0xE74C3C}
NTFY_PRIORITY = {"info": 3, "warning": 4, "critical": 5}
NTFY_TAGS = {"info": "information_source", "warning": "warning", "critical": "rotating_light"}
GOTIFY_PRIORITY = {"info": 4, "warning": 7, "critical": 9}
DISCORD_TITLE_LIMIT = 256
DISCORD_TEXT_LIMIT = 4096
SLACK_TEXT_LIMIT = 3000
TELEGRAM_TEXT_LIMIT = 4096
NTFY_TEXT_LIMIT = 4000

_urlopen = urllib.request.urlopen
_smtp = smtplib.SMTP
_smtp_ssl = smtplib.SMTP_SSL


class DeliveryError(RuntimeError):
    pass


def deliver(channel: Channel, rendered: Rendered, config: Config) -> None:
    sender = _SENDERS.get(channel.type)
    if sender is None:
        raise DeliveryError(f"unknown channel type '{channel.type}'")
    sender(channel, rendered, config)


def _discord(channel: Channel, rendered: Rendered, config: Config) -> None:
    payload = {
        "username": sender_name(channel, config),
        "embeds": [{
            "title": clip(rendered.title, DISCORD_TITLE_LIMIT),
            "description": clip(rendered.text, DISCORD_TEXT_LIMIT),
            "color": DISCORD_COLORS[rendered.severity],
        }],
        "allowed_mentions": {"parse": []},
    }
    post_json(channel.url, payload)


def _slack(channel: Channel, rendered: Rendered, config: Config) -> None:
    title = slack_escape(rendered.title.replace("*", ""))
    text = slack_escape(clip(rendered.text, SLACK_TEXT_LIMIT))
    payload = {
        "username": sender_name(channel, config),
        "text": f"*{title}*\n{text}",
    }
    post_json(channel.url, payload)


def _telegram(channel: Channel, rendered: Rendered, config: Config) -> None:
    payload = {
        "chat_id": channel.chatid,
        "text": clip(f"{rendered.title}\n\n{rendered.text}", TELEGRAM_TEXT_LIMIT),
        "disable_web_page_preview": True,
    }
    post_json(f"https://api.telegram.org/bot{channel.token}/sendMessage", payload)


def _ntfy(channel: Channel, rendered: Rendered, config: Config) -> None:
    payload = {
        "topic": channel.topic,
        "title": rendered.title,
        "message": clip(rendered.text, NTFY_TEXT_LIMIT),
        "priority": NTFY_PRIORITY[rendered.severity],
        "tags": [NTFY_TAGS[rendered.severity]],
    }
    headers = {"Authorization": f"Bearer {channel.token}"} if channel.token else {}
    post_json(f"{channel.url}/", payload, headers)


def _gotify(channel: Channel, rendered: Rendered, config: Config) -> None:
    payload = {
        "title": rendered.title,
        "message": rendered.text,
        "priority": GOTIFY_PRIORITY[rendered.severity],
    }
    post_json(f"{channel.url}/message", payload, {"X-Gotify-Key": channel.token})


def _email(channel: Channel, rendered: Rendered, config: Config) -> None:
    settings = config.email
    if not settings.enable:
        raise DeliveryError("email notifications are disabled in openmediavault")
    recipients = channel.recipients or settings.default_recipients
    if not recipients:
        raise DeliveryError("no recipients configured")
    if not settings.sender:
        raise DeliveryError("no sender address configured in openmediavault")
    message = EmailMessage()
    message["From"] = formataddr((sender_name(channel, config), settings.sender))
    message["To"] = ", ".join(recipients)
    message["Subject"] = rendered.title
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=config.fqdn)
    message["X-OMV-Notifier"] = "1"
    message.set_content(rendered.text)
    message.add_alternative(rendered.html, subtype="html")
    message.get_payload()[0]["X-OMV-Notifier"] = "1"
    envelope_sender = (
        f"{LOCAL_ENVELOPE_USER}@{config.fqdn}" if settings.is_local_server else settings.sender
    )
    try:
        with _smtp_connect(settings) as smtp:
            if settings.authenable:
                smtp.login(settings.username, settings.password)
            smtp.send_message(message, from_addr=envelope_sender, to_addrs=list(recipients))
    except (smtplib.SMTPException, OSError) as exc:
        raise DeliveryError(
            f"SMTP delivery via {settings.server}:{settings.port} failed: {exc}"
        ) from exc


def _smtp_connect(settings: EmailSettings):
    context = ssl.create_default_context()
    use_ssl = settings.tls == "ssl" or (settings.tls == "auto" and settings.port == 465)
    if use_ssl:
        return _smtp_ssl(settings.server, settings.port, timeout=SMTP_TIMEOUT, context=context)
    smtp = _smtp(settings.server, settings.port, timeout=SMTP_TIMEOUT)
    if settings.tls in ("starttls", "auto"):
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
    return smtp


def post_json(url: str, payload: dict, headers=None) -> bytes:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            **(headers or {}),
        },
        method="POST",
    )
    host = urllib.parse.urlsplit(url).hostname or url
    try:
        with _urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(200).decode("utf-8", errors="replace").strip()
        raise DeliveryError(f"HTTP {exc.code} from {host}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise DeliveryError(f"cannot reach {host}: {exc.reason}") from exc
    except (OSError, TimeoutError) as exc:
        raise DeliveryError(f"request to {host} failed: {exc}") from exc


def sender_name(channel: Channel, config: Config) -> str:
    return channel.sendername or config.hostname


def slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 1] + "…"


_SENDERS = {
    "discord": _discord,
    "slack": _slack,
    "telegram": _telegram,
    "ntfy": _ntfy,
    "gotify": _gotify,
    "email": _email,
}
