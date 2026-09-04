import unittest

from omvnotifier import config as config_module

from helpers import make_config, raw_channel, raw_config


class ParseTest(unittest.TestCase):
    def test_parses_complete_configuration(self):
        config = make_config()
        self.assertTrue(config.enable)
        self.assertEqual(config.fqdn, "storagecenter.home.arpa")
        self.assertEqual(config.email.port, 587)
        self.assertEqual(len(config.channels), 2)
        self.assertEqual(config.channels[1].events, frozenset({"smart", "mdadm"}))
        self.assertEqual(config.mountpoints[0].tags, ("media", "backup"))
        self.assertEqual(config.channels[0].sendername, "")
        self.assertEqual(config.channel("22222222-2222-4222-8222-222222222222").name, "Phone")
        self.assertIsNone(config.channel("missing"))

    def test_accepts_string_booleans_from_salt(self):
        raw = raw_config(enable="1", replaceemail="0")
        raw["email"]["enable"] = "1"
        raw["channels"][0]["skiprecovery"] = "1"
        config = config_module.parse(raw)
        self.assertTrue(config.enable)
        self.assertFalse(config.replaceemail)
        self.assertTrue(config.channels[0].skiprecovery)

    def test_missing_key_is_reported_by_name(self):
        raw = raw_config()
        del raw["hostname"]
        with self.assertRaisesRegex(config_module.ConfigError, "hostname"):
            config_module.parse(raw)

    def test_unknown_channel_type_is_rejected(self):
        raw = raw_config(channels=[raw_channel(type="pager", name="Pager")])
        with self.assertRaisesRegex(config_module.ConfigError, "Pager.*pager"):
            config_module.parse(raw)

    def test_invalid_boolean_is_rejected(self):
        with self.assertRaisesRegex(config_module.ConfigError, "enable"):
            config_module.parse(raw_config(enable="maybe"))

    def test_fqdn_without_domain(self):
        config = make_config(domainname="")
        self.assertEqual(config.fqdn, "storagecenter")

    def test_url_trailing_slash_is_stripped(self):
        config = make_config(channels=[raw_channel(url="https://gotify.example.com/")])
        self.assertEqual(config.channels[0].url, "https://gotify.example.com")


class LoadTest(unittest.TestCase):
    def test_missing_file_raises_config_error(self):
        with self.assertRaisesRegex(config_module.ConfigError, "does not exist"):
            config_module.load("/nonexistent/omv-notifier.json")


class ChannelAcceptsTest(unittest.TestCase):
    def test_empty_events_accept_everything(self):
        channel = make_config().channels[0]
        self.assertTrue(channel.accepts("cron", False))
        self.assertTrue(channel.accepts("smart", True))

    def test_event_filter(self):
        channel = make_config().channels[1]
        self.assertTrue(channel.accepts("smart", False))
        self.assertFalse(channel.accepts("cron", False))

    def test_disabled_channel_rejects(self):
        config = make_config(channels=[raw_channel(enable=False)])
        self.assertFalse(config.channels[0].accepts("smart", False))

    def test_skip_recovery(self):
        config = make_config(channels=[raw_channel(skiprecovery=True)])
        self.assertFalse(config.channels[0].accepts("monit-filesystem", True))
        self.assertTrue(config.channels[0].accepts("monit-filesystem", False))


class EmailSettingsTest(unittest.TestCase):
    def test_local_server_detection(self):
        raw = raw_config()
        raw["email"]["server"] = "localhost"
        self.assertTrue(config_module.parse(raw).email.is_local_server)
        self.assertFalse(make_config().email.is_local_server)

    def test_default_recipients_skip_empty(self):
        self.assertEqual(make_config().email.default_recipients, ("admin@example.org",))


if __name__ == "__main__":
    unittest.main()
