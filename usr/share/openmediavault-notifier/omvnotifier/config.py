import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = "/etc/openmediavault-notifier/config.json"
CONFIG_PATH_ENV = "OMV_NOTIFIER_CONFIG"
CHANNEL_TYPES = ("discord", "slack", "telegram", "ntfy", "gotify", "email")
LOCAL_SMTP_HOSTS = ("127.0.0.1", "localhost", "::1")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class EmailSettings:
    enable: bool
    server: str
    port: int
    tls: str
    sender: str
    authenable: bool
    username: str
    password: str
    primaryemail: str
    secondaryemail: str

    @property
    def is_local_server(self) -> bool:
        return self.server.strip().lower() in LOCAL_SMTP_HOSTS

    @property
    def default_recipients(self) -> tuple:
        return tuple(address for address in (self.primaryemail, self.secondaryemail) if address)


@dataclass(frozen=True)
class Channel:
    uuid: str
    enable: bool
    name: str
    type: str
    url: str
    token: str
    chatid: str
    topic: str
    recipients: tuple
    sendername: str
    events: frozenset
    skiprecovery: bool

    def accepts(self, event: str, recovery: bool) -> bool:
        if not self.enable:
            return False
        if self.skiprecovery and recovery:
            return False
        return not self.events or event in self.events


@dataclass(frozen=True)
class Mountpoint:
    uuid: str
    fsname: str
    dir: str
    fstype: str
    tags: tuple


@dataclass(frozen=True)
class SharedFolder:
    name: str
    mntentref: str
    reldirpath: str


@dataclass(frozen=True)
class Config:
    enable: bool
    replaceemail: bool
    uiurl: str
    hostname: str
    domainname: str
    email: EmailSettings
    channels: tuple
    mountpoints: tuple
    sharedfolders: tuple

    @property
    def fqdn(self) -> str:
        return f"{self.hostname}.{self.domainname}" if self.domainname else self.hostname

    def channel(self, uuid: str):
        for channel in self.channels:
            if channel.uuid == uuid:
                return channel
        return None


def config_path() -> Path:
    return Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH))


def load(path=None) -> Config:
    path = Path(path) if path else config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(
            f"configuration file {path} does not exist, apply the configuration first"
        ) from None
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read configuration file {path}: {exc}") from exc
    return parse(raw)


def parse(raw) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be an object")
    email = _dict(raw, "email")
    return Config(
        enable=_bool(raw, "enable"),
        replaceemail=_bool(raw, "replaceemail"),
        uiurl=_str(raw, "uiurl"),
        hostname=_str(raw, "hostname"),
        domainname=_str(raw, "domainname"),
        email=EmailSettings(
            enable=_bool(email, "enable"),
            server=_str(email, "server"),
            port=_int(email, "port"),
            tls=_str(email, "tls"),
            sender=_str(email, "sender"),
            authenable=_bool(email, "authenable"),
            username=_str(email, "username"),
            password=_str(email, "password"),
            primaryemail=_str(email, "primaryemail"),
            secondaryemail=_str(email, "secondaryemail"),
        ),
        channels=tuple(_channel(item) for item in _list(raw, "channels")),
        mountpoints=tuple(_mountpoint(item) for item in _list(raw, "mountpoints")),
        sharedfolders=tuple(_sharedfolder(item) for item in _list(raw, "sharedfolders")),
    )


def _channel(item) -> Channel:
    channel_type = _str(item, "type")
    if channel_type not in CHANNEL_TYPES:
        raise ConfigError(f"channel '{item.get('name', '?')}' has unknown type '{channel_type}'")
    return Channel(
        uuid=_str(item, "uuid"),
        enable=_bool(item, "enable"),
        name=_str(item, "name"),
        type=channel_type,
        url=_str(item, "url").strip().rstrip("/"),
        token=_str(item, "token").strip(),
        chatid=_str(item, "chatid").strip(),
        topic=_str(item, "topic").strip(),
        recipients=_csv(_str(item, "recipients")),
        sendername=_str(item, "sendername").strip(),
        events=frozenset(_csv(_str(item, "events"))),
        skiprecovery=_bool(item, "skiprecovery"),
    )


def _mountpoint(item) -> Mountpoint:
    return Mountpoint(
        uuid=_str(item, "uuid"),
        fsname=_str(item, "fsname"),
        dir=_str(item, "dir"),
        fstype=_str(item, "fstype"),
        tags=_csv(_str(item, "tags")),
    )


def _sharedfolder(item) -> SharedFolder:
    return SharedFolder(
        name=_str(item, "name"),
        mntentref=_str(item, "mntentref"),
        reldirpath=_str(item, "reldirpath"),
    )


def _csv(value: str) -> tuple:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _get(obj, key):
    if not isinstance(obj, dict) or key not in obj:
        raise ConfigError(f"missing configuration key '{key}'")
    return obj[key]


def _dict(obj, key) -> dict:
    value = _get(obj, key)
    if not isinstance(value, dict):
        raise ConfigError(f"configuration key '{key}' must be an object")
    return value


def _list(obj, key) -> list:
    value = _get(obj, key)
    if not isinstance(value, list):
        raise ConfigError(f"configuration key '{key}' must be a list")
    return value


def _str(obj, key) -> str:
    value = _get(obj, key)
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ConfigError(f"configuration key '{key}' must be a string")
    return str(value)


def _int(obj, key) -> int:
    value = _get(obj, key)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"configuration key '{key}' must be an integer") from None


def _bool(obj, key) -> bool:
    value = _get(obj, key)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off", ""):
            return False
    raise ConfigError(f"configuration key '{key}' must be a boolean")
