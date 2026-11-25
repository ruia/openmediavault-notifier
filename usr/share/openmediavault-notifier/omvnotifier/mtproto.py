import base64
import binascii
import ipaddress
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .config import Channel

RUNTIME_PYTHON = "/opt/openmediavault-notifier-mtproxy/bin/python3"
# The helper reads the request as JSON on stdin and exits 0 once Telegram confirmed
# the message. On failure the last line it writes to stderr is the reason.
HELPER = Path(__file__).with_name("mtproxy_helper.py")
TIMEOUT = 30
PROXY_LINKS = (("https", "t.me", "/proxy"), ("tg", "proxy", ""))


class MTProtoError(RuntimeError):
    pass


def check(mtproxy: str, apiid: str, apihash: str, chatid: str) -> dict:
    proxy = parse_proxy(mtproxy)
    if not re.fullmatch(r"[0-9]{1,10}", apiid) or not 0 < int(apiid) < 2**31:
        raise MTProtoError("the API ID must be the number shown at my.telegram.org")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", apihash):
        raise MTProtoError("the API hash must be the 32 character value shown at my.telegram.org")
    if not (re.fullmatch(r"@[A-Za-z0-9_]{1,32}", chatid) or _is_numeric_chat_id(chatid)):
        raise MTProtoError("the chat ID must be a numeric chat ID or an @username")
    return {"api_id": int(apiid), "api_hash": apihash, "chat_id": chatid, "proxy": proxy}


def deliver(channel: Channel, text: str) -> None:
    request = check(channel.mtproxy, channel.apiid, channel.apihash, channel.chatid)
    request.update(bot_token=channel.token, text=text)
    try:
        result = subprocess.run(
            [RUNTIME_PYTHON, "-I", str(HELPER)], input=json.dumps(request), text=True,
            capture_output=True, timeout=TIMEOUT, check=False,
        )
    except FileNotFoundError:
        raise MTProtoError(
            f"the MTProxy runtime {RUNTIME_PYTHON} is not installed, see the plugin README"
        ) from None
    except subprocess.TimeoutExpired:
        raise MTProtoError(f"MTProxy delivery did not finish within {TIMEOUT} seconds") from None
    if result.returncode != 0:
        reason = _last_line(result.stderr)
        for secret in filter(None, (channel.token, channel.apihash, request["proxy"]["secret"])):
            reason = reason.replace(secret, "***")
        raise MTProtoError(f"MTProxy helper failed with exit status {result.returncode}: {reason}")


def parse_proxy(link: str) -> dict:
    try:
        if len(link) > 1024:
            raise ValueError
        url = urlsplit(link)
        if (url.scheme, url.netloc, url.path) not in PROXY_LINKS or url.fragment:
            raise ValueError
        fields = parse_qs(url.query, strict_parsing=True, max_num_fields=3)
        if fields.keys() != {"server", "port", "secret"}:
            raise ValueError
        server, = fields["server"]
        port, = fields["port"]
        secret, = fields["secret"]
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", server):
            server = str(ipaddress.IPv6Address(server.removeprefix("[").removesuffix("]")))
        if not re.fullmatch(r"[0-9]{1,5}", port) or not 0 < int(port) <= 65535:
            raise ValueError
        raw = _decode_secret(secret)
        if not (len(raw) == 16
                or len(raw) == 17 and raw[0] == 0xDD
                or 18 <= len(raw) <= 270 and raw[0] == 0xEE):
            raise ValueError
    except (ValueError, binascii.Error):
        raise MTProtoError("the MTProxy link is not a valid Telegram proxy link") from None
    return {"server": server, "port": int(port), "secret": raw.hex()}


def _decode_secret(secret: str) -> bytes:
    if re.fullmatch(r"[0-9a-fA-F]+", secret) and len(secret) % 2 == 0:
        return bytes.fromhex(secret)
    if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", secret) or len(secret) > 512:
        raise ValueError
    return base64.b64decode(secret + "=" * (-len(secret) % 4), altchars=b"-_", validate=True)


def _is_numeric_chat_id(chatid: str) -> bool:
    return re.fullmatch(r"-?[0-9]{1,16}", chatid) is not None and 0 < abs(int(chatid)) < 2**53


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "no reason given"
