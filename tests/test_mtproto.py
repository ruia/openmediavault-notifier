import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omvnotifier import channels, mtproto
from omvnotifier.render import Rendered

from helpers import make_channel, make_config

SECRET = "dd" + "b" * 32
LINK = f"https://t.me/proxy?server=proxy.example&port=443&secret={SECRET}"
TOKEN = "123456:bot-token-value"
API_HASH = "a" * 32
FAKE_TLS = "ee" + "c" * 32 + b"example.com".hex()


def mtproxy_channel(**overrides):
    settings = dict(type="telegram", token=TOKEN, chatid="42", transport="mtproxy",
                    mtproxy=LINK, apiid="123456", apihash=API_HASH)
    settings.update(overrides)
    return make_channel(**settings)


def rendered():
    return Rendered(title="nas: Test notification", text="Severity: info", html="", severity="info")


class ParseProxyTest(unittest.TestCase):
    def test_accepted_links(self):
        cases = {
            f"https://t.me/proxy?server=proxy.example&port=443&secret={'a' * 32}":
                {"server": "proxy.example", "port": 443, "secret": "a" * 32},
            LINK: {"server": "proxy.example", "port": 443, "secret": SECRET},
            f"tg://proxy?server=10.0.0.1&port=8443&secret={FAKE_TLS.upper()}":
                {"server": "10.0.0.1", "port": 8443, "secret": FAKE_TLS},
            "tg://proxy?server=proxy.example&port=443&secret="
            + base64.urlsafe_b64encode(bytes.fromhex(FAKE_TLS)).decode().rstrip("="):
                {"server": "proxy.example", "port": 443, "secret": FAKE_TLS},
            f"https://t.me/proxy?server=[2001:db8::1]&port=443&secret={SECRET}":
                {"server": "2001:db8::1", "port": 443, "secret": SECRET},
        }
        for link, expected in cases.items():
            with self.subTest(link=link):
                self.assertEqual(mtproto.parse_proxy(link), expected)

    def test_rejected_links_never_repeat_the_secret(self):
        secret = "f" * 32
        cases = [
            "",
            f"https://example.com/proxy?server=p&port=443&secret={secret}",
            f"http://t.me/proxy?server=p&port=443&secret={secret}",
            "https://t.me/proxy?server=p&port=443",
            f"https://t.me/proxy?server=p&port=443&secret={secret}&extra=1",
            f"https://t.me/proxy?server=p&port=443&secret={secret}#fragment",
            f"https://t.me/proxy?server=p&port=0&secret={secret}",
            f"https://t.me/proxy?server=p&port=70000&secret={secret}",
            f"https://t.me/proxy?server=bad_host!&port=443&secret={secret}",
            f"https://t.me/proxy?server=p&port=443&secret={'f' * 30}",
            f"https://t.me/proxy?server=p&port=443&secret=dd{'f' * 34}",
            f"https://t.me/proxy?server=p&port=443&secret=ee{'f' * 32}",
        ]
        for link in cases:
            with self.subTest(link=link):
                with self.assertRaises(mtproto.MTProtoError) as raised:
                    mtproto.parse_proxy(link)
                self.assertEqual(str(raised.exception), "the MTProxy link is not a valid Telegram proxy link")
                self.assertNotIn(secret, str(raised.exception))


class CheckTest(unittest.TestCase):
    def test_valid_settings(self):
        for chatid in ("42", "-123", "-1001234567890", "@nas_alerts"):
            with self.subTest(chatid=chatid):
                request = mtproto.check(LINK, "123456", API_HASH, chatid)
                self.assertEqual(request["chat_id"], chatid)
        self.assertEqual(mtproto.check(LINK, "123456", API_HASH, "42"), {
            "api_id": 123456, "api_hash": API_HASH, "chat_id": "42",
            "proxy": {"server": "proxy.example", "port": 443, "secret": SECRET},
        })

    def test_invalid_api_id(self):
        for apiid in ("", "0", "abc", "2147483648", "12345678901"):
            with self.subTest(apiid=apiid):
                with self.assertRaisesRegex(mtproto.MTProtoError, "API ID"):
                    mtproto.check(LINK, apiid, API_HASH, "42")

    def test_invalid_api_hash(self):
        for apihash in ("", "a" * 31, "g" * 32):
            with self.subTest(apihash=apihash):
                with self.assertRaisesRegex(mtproto.MTProtoError, "API hash"):
                    mtproto.check(LINK, "123456", apihash, "42")

    def test_invalid_chat_id(self):
        for chatid in ("", "0", "abc", "@", "@bad-name", "12345678901234567"):
            with self.subTest(chatid=chatid):
                with self.assertRaisesRegex(mtproto.MTProtoError, "chat ID"):
                    mtproto.check(LINK, "123456", API_HASH, chatid)


class DeliverTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.helper = self.dir / "helper.py"
        for name, value in (("RUNTIME_PYTHON", sys.executable), ("HELPER", self.helper)):
            patcher = mock.patch.object(mtproto, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.urlopen = mock.Mock()
        patcher = mock.patch.object(channels, "_urlopen", self.urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = make_config()

    def write_helper(self, code):
        self.helper.write_text(code, encoding="utf-8")

    def record_helper(self):
        record = self.dir / "record.json"
        self.write_helper(
            "import json, sys\n"
            f"open({str(record)!r}, 'w').write(json.dumps("
            "{'argv': sys.argv, 'request': json.load(sys.stdin)}))\n"
        )
        return record

    def test_helper_gets_the_request_on_stdin(self):
        record = self.record_helper()
        channels.deliver(mtproxy_channel(), rendered(), self.config)
        recorded = json.loads(record.read_text())
        self.assertEqual(recorded["request"], {
            "api_id": 123456, "api_hash": API_HASH, "chat_id": "42", "bot_token": TOKEN,
            "proxy": {"server": "proxy.example", "port": 443, "secret": SECRET},
            "text": "nas: Test notification\n\nSeverity: info",
        })
        self.assertFalse(any(TOKEN in arg or SECRET in arg for arg in recorded["argv"]))
        self.urlopen.assert_not_called()

    def test_helper_failure_reports_its_last_line_without_secrets(self):
        self.write_helper(
            "import sys\n"
            "print('starting', file=sys.stderr)\n"
            f"print('rejected {TOKEN} {API_HASH} {SECRET}', file=sys.stderr)\n"
            "sys.exit(3)\n"
        )
        with self.assertRaises(channels.DeliveryError) as raised:
            channels.deliver(mtproxy_channel(), rendered(), self.config)
        self.assertEqual(str(raised.exception),
                         "MTProxy helper failed with exit status 3: rejected *** *** ***")

    def test_missing_helper_is_reported(self):
        with self.assertRaisesRegex(channels.DeliveryError, "exit status 2: .*helper.py"):
            channels.deliver(mtproxy_channel(), rendered(), self.config)

    def test_missing_runtime_is_reported(self):
        with mock.patch.object(mtproto, "RUNTIME_PYTHON", str(self.dir / "missing" / "python3")):
            with self.assertRaisesRegex(channels.DeliveryError, "runtime .* is not installed"):
                channels.deliver(mtproxy_channel(), rendered(), self.config)

    def test_slow_helper_is_stopped(self):
        self.write_helper("import time\ntime.sleep(10)\n")
        with mock.patch.object(mtproto, "TIMEOUT", 0.5):
            with self.assertRaisesRegex(channels.DeliveryError, "did not finish within 0.5 seconds"):
                channels.deliver(mtproxy_channel(), rendered(), self.config)

    def test_invalid_settings_do_not_start_the_helper(self):
        record = self.record_helper()
        with self.assertRaisesRegex(channels.DeliveryError, "API ID"):
            channels.deliver(mtproxy_channel(apiid="x"), rendered(), self.config)
        self.assertFalse(record.exists())


class DatamodelTest(unittest.TestCase):
    def test_channel_models_agree_on_the_connection_fields(self):
        models = Path(__file__).parents[1] / "usr/share/openmediavault/datamodels"
        parent = json.loads((models / "conf.service.notifier.json").read_text())
        child = json.loads((models / "conf.service.notifier.channel.json").read_text())
        rpc = {entry["id"]: entry for entry in json.loads((models / "rpc.notifier.json").read_text())}
        nested = parent["properties"]["channels"]["properties"]["channel"]["items"]["properties"]
        setchannel = rpc["rpc.notifier.setchannel"]["params"]["properties"]
        for field in ("transport", "mtproxy", "apiid", "apihash"):
            with self.subTest(field=field):
                self.assertEqual(nested[field], child["properties"][field])
                self.assertTrue(setchannel[field]["required"])
        self.assertEqual(child["properties"]["transport"]["enum"], ["botapi", "mtproxy"])
        self.assertEqual(setchannel["transport"]["enum"], ["botapi", "mtproxy"])


if __name__ == "__main__":
    unittest.main()
