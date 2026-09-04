import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from omvnotifier import channels, cli, enrich
from omvnotifier import config as config_module

from helpers import LSBLK_DEVICES, MONIT_FS_BODY, MONIT_FS_SUBJECT, raw_channel, write_config


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_path = Path(self.tmp.name) / "config.json"
        self.message_path = Path(self.tmp.name) / "message.txt"
        self.env = mock.patch.dict(os.environ, {
            config_module.CONFIG_PATH_ENV: str(self.config_path),
            "OMV_NOTIFICATION_SUBJECT": MONIT_FS_SUBJECT,
            "OMV_NOTIFICATION_DATE": "Fri, 04 Sep 2026 10:31:09 +0100",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.deliver = mock.Mock()
        patcher = mock.patch.object(channels, "deliver", self.deliver)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(enrich, "list_block_devices", mock.Mock(return_value=LSBLK_DEVICES))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(cli, "SYSLOG_SOCKET", os.path.join(self.tmp.name, "no-syslog"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def dispatch(self, body=MONIT_FS_BODY):
        self.message_path.write_text(body, encoding="utf-8")
        return self.run_cli("dispatch", str(self.message_path), "sender@example.org", "admin@example.org")


class DispatchTest(CliTestCase):
    def test_delivers_to_matching_channels_with_enrichment(self):
        write_config(self.config_path)
        code, _, err = self.dispatch()
        self.assertEqual(code, 0)
        self.deliver.assert_called_once()
        channel, rendered, config = self.deliver.call_args.args
        self.assertEqual(channel.name, "Discord")
        self.assertIn("Disk Media back under the space threshold", rendered.title)
        self.assertIn("Shared folders: movies, tv", rendered.text)
        self.assertIn("delivered 'monit-filesystem' event to channel 'Discord'", err)

    def test_delivery_error_does_not_stop_other_channels(self):
        write_config(self.config_path, channels=[
            raw_channel(uuid="1", name="A", type="discord", url="https://d/x"),
            raw_channel(uuid="2", name="B", type="discord", url="https://d/y"),
        ])
        self.deliver.side_effect = [channels.DeliveryError("boom"), None]
        code, _, err = self.dispatch()
        self.assertEqual(code, 0)
        self.assertEqual(self.deliver.call_count, 2)
        self.assertIn("channel 'A' (discord): boom", err)

    def test_no_matching_channel(self):
        write_config(self.config_path, channels=[raw_channel(events="smart")])
        code, _, err = self.dispatch()
        self.assertEqual(code, 0)
        self.deliver.assert_not_called()
        self.assertIn("no channel accepts event 'monit-filesystem'", err)

    def test_disabled_plugin(self):
        write_config(self.config_path, enable=False)
        self.assertEqual(self.dispatch()[0], 0)
        self.deliver.assert_not_called()

    def test_missing_config_exits_zero(self):
        code, _, err = self.dispatch()
        self.assertEqual(code, 0)
        self.assertIn("does not exist", err)
        self.deliver.assert_not_called()

    def test_missing_message_file_exits_zero(self):
        write_config(self.config_path)
        code, _, err = self.run_cli("dispatch", str(self.message_path))
        self.assertEqual(code, 0)
        self.assertIn("cannot read message file", err)

    def test_unexpected_exception_exits_zero(self):
        write_config(self.config_path)
        self.deliver.side_effect = RuntimeError("unexpected")
        code, _, err = self.dispatch()
        self.assertEqual(code, 0)
        self.assertIn("unhandled error in dispatch", err)

    def test_lsblk_failure_still_delivers(self):
        write_config(self.config_path)
        enrich.list_block_devices.side_effect = enrich.EnrichError("no lsblk")
        code, _, err = self.dispatch()
        self.assertEqual(code, 0)
        self.deliver.assert_called_once()
        self.assertIn("block device lookup failed", err)


class TestCommandTest(CliTestCase):
    def test_sends_test_notification(self):
        write_config(self.config_path)
        code, out, _ = self.run_cli("test", "22222222-2222-4222-8222-222222222222")
        self.assertEqual(code, 0)
        self.assertIn("Test notification sent to 'Phone' (ntfy)", out)
        channel, rendered, _ = self.deliver.call_args.args
        self.assertEqual(channel.type, "ntfy")
        self.assertEqual(rendered.title, "storagecenter: Test notification")

    def test_unknown_channel(self):
        write_config(self.config_path)
        code, _, err = self.run_cli("test", "nope")
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

    def test_delivery_failure_is_reported(self):
        write_config(self.config_path)
        self.deliver.side_effect = channels.DeliveryError("HTTP 404 from ntfy.sh: not found")
        code, _, err = self.run_cli("test", "22222222-2222-4222-8222-222222222222")
        self.assertEqual(code, 1)
        self.assertIn("channel 'Phone' (ntfy): HTTP 404", err)

    def test_missing_config(self):
        code, _, err = self.run_cli("test", "x")
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)


class EventsCommandTest(CliTestCase):
    def test_prints_json(self):
        code, out, _ = self.run_cli("events")
        self.assertEqual(code, 0)
        classes = json.loads(out)
        self.assertEqual(classes[0], {"value": "monit-filesystem", "text": "Monitoring: file systems"})


if __name__ == "__main__":
    unittest.main()
