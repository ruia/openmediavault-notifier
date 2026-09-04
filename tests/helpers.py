import json

from omvnotifier import config as config_module

MONIT_FS_SUBJECT = (
    "[storagecenter.home.arpa] Monitoring alert -- Resource limit succeeded "
    "filesystem_srv_dev-disk-by-uuid-01fd2738-e207-4442-b826-a6ac1025953a"
)
MONIT_FS_BODY = """The system monitoring needs your attention.

Host:        storagecenter
Date:        Fri, 04 Sep 2026 10:31:09
Service:     filesystem_srv_dev-disk-by-uuid-01fd2738-e207-4442-b826-a6ac1025953a
Event:       Resource limit succeeded
Description: space usage test succeeded [current space usage = 92.4%]

This triggered the monitoring system to: alert

—
You have received this notification because you have enabled the system monitoring on this host.
"""

MOUNT_DIR = "/srv/dev-disk-by-uuid-01fd2738-e207-4442-b826-a6ac1025953a"

LSBLK_DEVICES = [
    {"path": "/dev/sda", "pkname": None, "uuid": None, "label": None, "fstype": None,
     "size": "3.6T", "model": "WDC WD40EFRX-68N32N0", "serial": "WD-WCC7K1234567",
     "mountpoints": [None]},
    {"path": "/dev/sda1", "pkname": "sda", "uuid": "01fd2738-e207-4442-b826-a6ac1025953a",
     "label": "Media", "fstype": "ext4", "size": "3.6T", "model": None, "serial": None,
     "mountpoints": [MOUNT_DIR]},
    {"path": "/dev/nvme0n1", "pkname": None, "uuid": None, "label": None, "fstype": None,
     "size": "465G", "model": "Samsung SSD 980", "serial": "S123", "mountpoints": [None]},
    {"path": "/dev/nvme0n1p2", "pkname": "nvme0n1", "uuid": "aaaa", "label": None,
     "fstype": "ext4", "size": "460G", "model": None, "serial": None, "mountpoints": ["/"]},
]


def raw_config(**overrides):
    raw = {
        "version": 1,
        "enable": True,
        "replaceemail": False,
        "uiurl": "https://nas.local/",
        "hostname": "storagecenter",
        "domainname": "home.arpa",
        "email": {
            "enable": True,
            "server": "smtp.gmail.com",
            "port": 587,
            "tls": "starttls",
            "sender": "smtp.storagecenter@gmail.com",
            "authenable": True,
            "username": "smtp.storagecenter@gmail.com",
            "password": "app-password",
            "primaryemail": "admin@example.org",
            "secondaryemail": "",
        },
        "channels": [
            raw_channel(uuid="11111111-1111-4111-8111-111111111111", name="Discord", type="discord",
                        url="https://discord.com/api/webhooks/1/abc"),
            raw_channel(uuid="22222222-2222-4222-8222-222222222222", name="Phone", type="ntfy",
                        url="https://ntfy.sh", topic="nas", events="smart,mdadm"),
        ],
        "mountpoints": [
            {"uuid": "mp-1", "fsname": "/dev/disk/by-uuid/01fd2738-e207-4442-b826-a6ac1025953a",
             "dir": MOUNT_DIR, "fstype": "ext4", "tags": "media,backup"},
        ],
        "sharedfolders": [
            {"name": "movies", "mntentref": "mp-1", "reldirpath": "movies/"},
            {"name": "tv", "mntentref": "mp-1", "reldirpath": "tv/"},
            {"name": "other", "mntentref": "mp-2", "reldirpath": "other/"},
        ],
    }
    raw.update(overrides)
    return raw


def raw_channel(**overrides):
    channel = {
        "uuid": "00000000-0000-4000-8000-000000000000",
        "enable": True,
        "name": "channel",
        "type": "discord",
        "url": "",
        "token": "",
        "chatid": "",
        "topic": "",
        "recipients": "",
        "sendername": "",
        "events": "",
        "skiprecovery": False,
    }
    channel.update(overrides)
    return channel


def make_config(**overrides):
    return config_module.parse(raw_config(**overrides))


def make_channel(**overrides):
    return config_module.parse(raw_config(channels=[raw_channel(**overrides)])).channels[0]


def write_config(path, **overrides):
    path.write_text(json.dumps(raw_config(**overrides)), encoding="utf-8")
