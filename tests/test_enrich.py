import json
import subprocess
import unittest
from unittest import mock

from omvnotifier import enrich
from omvnotifier.message import Notification, classify

from helpers import LSBLK_DEVICES, MONIT_FS_BODY, MONIT_FS_SUBJECT, MOUNT_DIR, make_config


class ListBlockDevicesTest(unittest.TestCase):
    def test_parses_lsblk_json(self):
        completed = subprocess.CompletedProcess(enrich.LSBLK_COMMAND, 0, stdout=json.dumps({"blockdevices": LSBLK_DEVICES}))
        devices = enrich.list_block_devices(run=mock.Mock(return_value=completed))
        self.assertEqual(len(devices), 4)

    def test_lsblk_failure_raises_enrich_error(self):
        run = mock.Mock(side_effect=subprocess.CalledProcessError(1, "lsblk"))
        with self.assertRaisesRegex(enrich.EnrichError, "lsblk failed"):
            enrich.list_block_devices(run=run)

    def test_invalid_json_raises_enrich_error(self):
        completed = subprocess.CompletedProcess(enrich.LSBLK_COMMAND, 0, stdout="not json")
        with self.assertRaisesRegex(enrich.EnrichError, "invalid JSON"):
            enrich.list_block_devices(run=mock.Mock(return_value=completed))


class LookupTest(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_check_id_matches_monit_template(self):
        self.assertEqual(enrich.monit_check_id("/srv/dev disk:1"), "_srv_dev_disk_1")

    def test_mountpoint_for_service(self):
        service = "filesystem" + enrich.monit_check_id(MOUNT_DIR)
        self.assertEqual(enrich.mountpoint_for_service(self.config, service).dir, MOUNT_DIR)
        service = "mountpoint" + enrich.monit_check_id(MOUNT_DIR)
        self.assertEqual(enrich.mountpoint_for_service(self.config, service).dir, MOUNT_DIR)
        self.assertEqual(enrich.mountpoint_for_service(self.config, "rootfs").dir, "/")
        self.assertIsNone(enrich.mountpoint_for_service(self.config, "filesystem_srv_unknown"))
        self.assertIsNone(enrich.mountpoint_for_service(self.config, "nginx"))

    def test_describe_filesystem(self):
        details = enrich.describe_filesystem(self.config, LSBLK_DEVICES, self.config.mountpoints[0])
        self.assertEqual(details["label"], "Media")
        self.assertEqual(details["device"], "/dev/sda1")
        self.assertEqual(details["model"], "WDC WD40EFRX-68N32N0")
        self.assertEqual(details["serial"], "WD-WCC7K1234567")
        self.assertEqual(details["shares"], "movies, tv")
        self.assertEqual(details["tags"], "media, backup")
        self.assertEqual(details["mount_dir"], MOUNT_DIR)

    def test_describe_root_filesystem_without_devices(self):
        details = enrich.describe_filesystem(self.config, [], enrich.ROOT_MOUNTPOINT)
        self.assertEqual(details, {"mount_dir": "/"})

    def test_describe_disk(self):
        details = enrich.describe_disk(self.config, LSBLK_DEVICES, "/dev/sda")
        self.assertEqual(details["model"], "WDC WD40EFRX-68N32N0")
        self.assertEqual(details["filesystems"], f"Media ({MOUNT_DIR}) [movies, tv]")

    def test_describe_disk_unknown_device(self):
        self.assertEqual(enrich.describe_disk(self.config, LSBLK_DEVICES, "/dev/sdz"), {"device": "/dev/sdz"})


class EnrichTest(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_filesystem_notification_gains_disk_details(self):
        notification = classify(MONIT_FS_SUBJECT, MONIT_FS_BODY, hostname="storagecenter")
        enriched = enrich.enrich(notification, self.config, LSBLK_DEVICES)
        self.assertEqual(enriched.fields["label"], "Media")
        self.assertEqual(enriched.fields["shares"], "movies, tv")
        self.assertEqual(enriched.fields["event"], "Resource limit succeeded")

    def test_smart_notification_gains_disk_details(self):
        notification = Notification(subject="s", body="", event="smart", fields={"device": "/dev/sda", "type": "Health"})
        enriched = enrich.enrich(notification, self.config, LSBLK_DEVICES)
        self.assertEqual(enriched.fields["serial"], "WD-WCC7K1234567")
        self.assertIn("Media", enriched.fields["filesystems"])

    def test_other_events_are_untouched(self):
        notification = Notification(subject="Cron", body="", event="cron")
        self.assertIs(enrich.enrich(notification, self.config, LSBLK_DEVICES), notification)

    def test_unknown_service_is_untouched(self):
        notification = Notification(subject="s", body="", event="monit-filesystem", fields={"service": "filesystem_nope"})
        self.assertIs(enrich.enrich(notification, self.config, LSBLK_DEVICES), notification)


if __name__ == "__main__":
    unittest.main()
