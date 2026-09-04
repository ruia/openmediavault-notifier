import json
import os
import subprocess
from dataclasses import replace

from .config import Config, Mountpoint
from .message import Notification

LSBLK_COMMAND = (
    "lsblk", "--json", "--list",
    "--output", "PATH,PKNAME,UUID,LABEL,FSTYPE,SIZE,MODEL,SERIAL,MOUNTPOINTS",
)
ENRICHED_EVENTS = frozenset({"monit-filesystem", "smart"})
ROOT_MOUNTPOINT = Mountpoint(uuid="", fsname="", dir="/", fstype="", tags=())


class EnrichError(RuntimeError):
    pass


def list_block_devices(run=subprocess.run) -> list:
    try:
        completed = run(LSBLK_COMMAND, capture_output=True, text=True, check=True, timeout=10)
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise EnrichError(f"lsblk failed: {exc}") from exc
    except ValueError as exc:
        raise EnrichError(f"lsblk returned invalid JSON: {exc}") from exc
    devices = payload.get("blockdevices") if isinstance(payload, dict) else None
    if not isinstance(devices, list):
        raise EnrichError("lsblk output has no 'blockdevices' list")
    return [device for device in devices if isinstance(device, dict)]


def monit_check_id(mount_dir: str) -> str:
    return mount_dir.replace("/", "_").replace(" ", "_").replace(":", "_")


def mountpoint_for_service(config: Config, service: str):
    if service == "rootfs":
        return ROOT_MOUNTPOINT
    for prefix in ("filesystem", "mountpoint"):
        if service.startswith(prefix):
            check_id = service[len(prefix):]
            for mountpoint in config.mountpoints:
                if monit_check_id(mountpoint.dir) == check_id:
                    return mountpoint
    return None


def mountpoint_for_dir(config: Config, mount_dir: str):
    for mountpoint in config.mountpoints:
        if mountpoint.dir == mount_dir:
            return mountpoint
    return None


def device_for_mount(devices: list, mount_dir: str):
    for device in devices:
        if mount_dir in _mountpoints(device):
            return device
    return None


def device_by_path(devices: list, path: str):
    for device in devices:
        if device.get("path") == path:
            return device
    return None


def device_by_name(devices: list, name):
    if not name:
        return None
    return device_by_path(devices, f"/dev/{name}")


def children_of(devices: list, path: str) -> list:
    name = os.path.basename(path)
    return [device for device in devices if device.get("pkname") == name]


def shares_on(config: Config, mountpoint: Mountpoint) -> tuple:
    if not mountpoint.uuid:
        return ()
    return tuple(sorted(
        folder.name for folder in config.sharedfolders if folder.mntentref == mountpoint.uuid
    ))


def describe_filesystem(config: Config, devices: list, mountpoint: Mountpoint) -> dict:
    device = device_for_mount(devices, mountpoint.dir) or {}
    parent = device_by_name(devices, device.get("pkname")) or {}
    return _non_empty({
        "mount_dir": mountpoint.dir,
        "label": _text(device.get("label")),
        "device": _text(device.get("path")),
        "uuid": _text(device.get("uuid")),
        "size": _text(device.get("size")),
        "model": _text(parent.get("model") or device.get("model")),
        "serial": _text(parent.get("serial") or device.get("serial")),
        "tags": ", ".join(mountpoint.tags),
        "shares": ", ".join(shares_on(config, mountpoint)),
    })


def describe_disk(config: Config, devices: list, path: str) -> dict:
    device = device_by_path(devices, path) or {}
    filesystems = []
    for child in children_of(devices, path):
        for mount_dir in _mountpoints(child):
            mountpoint = mountpoint_for_dir(config, mount_dir)
            name = _text(child.get("label")) or _text(child.get("path"))
            shares = ", ".join(shares_on(config, mountpoint)) if mountpoint else ""
            filesystems.append(f"{name} ({mount_dir})" + (f" [{shares}]" if shares else ""))
    return _non_empty({
        "device": path,
        "model": _text(device.get("model")),
        "serial": _text(device.get("serial")),
        "size": _text(device.get("size")),
        "filesystems": "; ".join(filesystems),
    })


def enrich(notification: Notification, config: Config, devices: list) -> Notification:
    extra = {}
    if notification.event == "monit-filesystem":
        mountpoint = mountpoint_for_service(config, notification.fields.get("service", ""))
        if mountpoint:
            extra = describe_filesystem(config, devices, mountpoint)
    elif notification.event == "smart":
        path = notification.fields.get("device")
        if path:
            extra = describe_disk(config, devices, path)
    if not extra:
        return notification
    return replace(notification, fields={**notification.fields, **extra})


def _mountpoints(device: dict) -> list:
    values = device.get("mountpoints")
    if not isinstance(values, list):
        values = [device.get("mountpoint")]
    return [value for value in values if value]


def _text(value) -> str:
    return str(value).strip() if value else ""


def _non_empty(fields: dict) -> dict:
    return {key: value for key, value in fields.items() if value}
