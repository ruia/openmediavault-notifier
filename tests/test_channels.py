import io
import json
import smtplib
import unittest
import urllib.error
from unittest import mock

from omvnotifier import channels
from omvnotifier.render import Rendered

from helpers import make_channel, make_config, raw_config
from omvnotifier import config as config_module


def rendered(severity="warning"):
    return Rendered(title="nas: Disk Media is running out of space", text="Severity: warning\nDisk: Media",
                    html="<h2>x</h2>", severity=severity)


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class HttpChannelTest(unittest.TestCase):
    def setUp(self):
        self.urlopen = mock.Mock(return_value=FakeResponse(b"{}"))
        patcher = mock.patch.object(channels, "_urlopen", self.urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = make_config()

    def request(self):
        self.urlopen.assert_called_once()
        request = self.urlopen.call_args.args[0]
        self.assertEqual(self.urlopen.call_args.kwargs["timeout"], channels.HTTP_TIMEOUT)
        return request, json.loads(request.data.decode("utf-8"))

    def test_discord_embed(self):
        channels.deliver(make_channel(type="discord", url="https://discord.com/api/webhooks/1/abc"), rendered(), self.config)
        request, payload = self.request()
        self.assertEqual(request.full_url, "https://discord.com/api/webhooks/1/abc")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "nas: Disk Media is running out of space")
        self.assertEqual(embed["color"], channels.DISCORD_COLORS["warning"])
        self.assertIn("Disk: Media", embed["description"])
        self.assertEqual(payload["username"], "storagecenter")

    def test_discord_sender_name_override(self):
        channel = make_channel(type="discord", url="https://discord.com/api/webhooks/1/abc", sendername="NAS")
        channels.deliver(channel, rendered(), self.config)
        _, payload = self.request()
        self.assertEqual(payload["username"], "NAS")

    def test_slack_text(self):
        channels.deliver(make_channel(type="slack", url="https://hooks.slack.com/services/T/B/x"), rendered(), self.config)
        _, payload = self.request()
        self.assertTrue(payload["text"].startswith("*nas: Disk Media"))
        self.assertEqual(payload["username"], "storagecenter")

    def test_telegram(self):
        channels.deliver(make_channel(type="telegram", token="123:abc", chatid="-100"), rendered(), self.config)
        request, payload = self.request()
        self.assertEqual(request.full_url, "https://api.telegram.org/bot123:abc/sendMessage")
        self.assertEqual(payload["chat_id"], "-100")
        self.assertTrue(payload["text"].startswith("nas: Disk Media"))

    def test_ntfy_json_publish_with_token(self):
        channels.deliver(make_channel(type="ntfy", url="https://ntfy.sh/", topic="nas", token="tk_x"), rendered("critical"), self.config)
        request, payload = self.request()
        self.assertEqual(request.full_url, "https://ntfy.sh/")
        self.assertEqual(request.get_header("Authorization"), "Bearer tk_x")
        self.assertEqual(payload["topic"], "nas")
        self.assertEqual(payload["priority"], 5)
        self.assertEqual(payload["tags"], ["rotating_light"])

    def test_ntfy_without_token_has_no_auth_header(self):
        channels.deliver(make_channel(type="ntfy", url="https://ntfy.sh", topic="nas"), rendered(), self.config)
        request, _ = self.request()
        self.assertIsNone(request.get_header("Authorization"))

    def test_gotify(self):
        channels.deliver(make_channel(type="gotify", url="https://gotify.example.com", token="app"), rendered("info"), self.config)
        request, payload = self.request()
        self.assertEqual(request.full_url, "https://gotify.example.com/message")
        self.assertEqual(request.get_header("X-gotify-key"), "app")
        self.assertEqual(payload["priority"], channels.GOTIFY_PRIORITY["info"])

    def test_http_error_hides_token_and_shows_body(self):
        error = urllib.error.HTTPError("https://api.telegram.org/bot123:abc/sendMessage", 401, "Unauthorized",
                                       {}, io.BytesIO(b'{"description":"Unauthorized"}'))
        self.urlopen.side_effect = error
        with self.assertRaisesRegex(channels.DeliveryError, r"HTTP 401 from api.telegram.org: .*Unauthorized") as ctx:
            channels.deliver(make_channel(type="telegram", token="123:abc", chatid="1"), rendered(), self.config)
        self.assertNotIn("123:abc", str(ctx.exception))

    def test_unreachable_host(self):
        self.urlopen.side_effect = urllib.error.URLError("Name or service not known")
        with self.assertRaisesRegex(channels.DeliveryError, "cannot reach discord.com"):
            channels.deliver(make_channel(type="discord", url="https://discord.com/x"), rendered(), self.config)

    def test_timeout(self):
        self.urlopen.side_effect = TimeoutError("timed out")
        with self.assertRaisesRegex(channels.DeliveryError, "failed: timed out"):
            channels.deliver(make_channel(type="discord", url="https://discord.com/x"), rendered(), self.config)

    def test_long_text_is_clipped(self):
        long_rendered = Rendered(title="t", text="x" * 10000, html="", severity="info")
        channels.deliver(make_channel(type="discord", url="https://discord.com/x"), long_rendered, self.config)
        _, payload = self.request()
        self.assertEqual(len(payload["embeds"][0]["description"]), channels.DISCORD_TEXT_LIMIT)
        self.assertTrue(payload["embeds"][0]["description"].endswith("…"))


class FakeSmtp:
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls = []
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.calls.append(("quit",))

    def ehlo(self):
        self.calls.append(("ehlo",))

    def starttls(self, context=None):
        self.calls.append(("starttls",))

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message, from_addr=None, to_addrs=None):
        self.calls.append(("send", message, from_addr, to_addrs))


class FailingSmtp(FakeSmtp):
    def send_message(self, message, from_addr=None, to_addrs=None):
        raise smtplib.SMTPRecipientsRefused({to_addrs[0]: (550, b"no")})


class EmailChannelTest(unittest.TestCase):
    def setUp(self):
        FakeSmtp.instances = []
        for name in ("_smtp", "_smtp_ssl"):
            patcher = mock.patch.object(channels, name, FakeSmtp)
            patcher.start()
            self.addCleanup(patcher.stop)

    def config(self, **email_overrides):
        raw = raw_config()
        raw["email"].update(email_overrides)
        return config_module.parse(raw)

    def test_starttls_with_auth_and_default_recipients(self):
        channels.deliver(make_channel(type="email"), rendered(), self.config())
        smtp = FakeSmtp.instances[0]
        self.assertEqual((smtp.host, smtp.port), ("smtp.gmail.com", 587))
        names = [call[0] for call in smtp.calls]
        self.assertEqual(names, ["ehlo", "starttls", "ehlo", "login", "send", "quit"])
        send = smtp.calls[4]
        self.assertEqual(send[2], "smtp.storagecenter@gmail.com")
        self.assertEqual(send[3], ["admin@example.org"])
        message = send[1]
        self.assertEqual(message["From"], "storagecenter <smtp.storagecenter@gmail.com>")
        self.assertEqual(message["Subject"], "nas: Disk Media is running out of space")
        self.assertEqual(message["X-OMV-Notifier"], "1")
        self.assertTrue(message.is_multipart())
        self.assertEqual(message.get_body(("html",)).get_content_type(), "text/html")

    def test_explicit_recipients_and_ssl(self):
        channel = make_channel(type="email", recipients="a@example.org, b@example.org")
        channels.deliver(channel, rendered(), self.config(tls="ssl", port=465, authenable=False))
        smtp = FakeSmtp.instances[0]
        self.assertIsNotNone(smtp.context)
        self.assertEqual([call[0] for call in smtp.calls], ["send", "quit"])
        self.assertEqual(smtp.calls[0][3], ["a@example.org", "b@example.org"])

    def test_email_sender_name_override(self):
        channels.deliver(make_channel(type="email", sendername="Home NAS"), rendered(), self.config())
        message = FakeSmtp.instances[0].calls[4][1]
        self.assertEqual(message["From"], "Home NAS <smtp.storagecenter@gmail.com>")

    def test_auto_on_465_uses_ssl(self):
        channels.deliver(make_channel(type="email"), rendered(), self.config(tls="auto", port=465))
        self.assertNotIn(("starttls",), FakeSmtp.instances[0].calls)

    def test_plain_without_tls(self):
        channels.deliver(make_channel(type="email"), rendered(), self.config(tls="none", authenable=False))
        self.assertEqual([call[0] for call in FakeSmtp.instances[0].calls], ["send", "quit"])

    def test_local_server_uses_distinct_envelope_sender(self):
        channels.deliver(make_channel(type="email"), rendered(), self.config(server="localhost", port=25, tls="none", authenable=False))
        send = FakeSmtp.instances[0].calls[0]
        self.assertEqual(send[2], "openmediavault-notifier@storagecenter.home.arpa")
        self.assertEqual(send[1]["From"], "storagecenter <smtp.storagecenter@gmail.com>")

    def test_disabled_email_notifications(self):
        with self.assertRaisesRegex(channels.DeliveryError, "disabled"):
            channels.deliver(make_channel(type="email"), rendered(), self.config(enable=False))

    def test_no_recipients(self):
        with self.assertRaisesRegex(channels.DeliveryError, "no recipients"):
            channels.deliver(make_channel(type="email"), rendered(), self.config(primaryemail="", secondaryemail=""))

    def test_smtp_failure_is_delivery_error(self):
        with mock.patch.object(channels, "_smtp", FailingSmtp):
            with self.assertRaisesRegex(channels.DeliveryError, "SMTP delivery via smtp.gmail.com:587 failed"):
                channels.deliver(make_channel(type="email"), rendered(), self.config())


class DispatchTest(unittest.TestCase):
    def test_unknown_type(self):
        channel = make_channel(type="discord")
        bogus = channel.__class__(**{**channel.__dict__, "type": "pager"})
        with self.assertRaisesRegex(channels.DeliveryError, "unknown channel type 'pager'"):
            channels.deliver(bogus, rendered(), make_config())

    def test_clip(self):
        self.assertEqual(channels.clip("abc", 3), "abc")
        self.assertEqual(channels.clip("abcd", 3), "ab…")


if __name__ == "__main__":
    unittest.main()
