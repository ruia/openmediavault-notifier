import unittest

from omvnotifier.message import Notification, classify
from omvnotifier.render import MAX_BODY_LINES, body_excerpt, render

from helpers import MONIT_FS_BODY, MONIT_FS_SUBJECT, make_config


class HeadlineTest(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_filesystem_recovery_uses_label_and_usage(self):
        notification = classify(MONIT_FS_SUBJECT, MONIT_FS_BODY, hostname="storagecenter")
        notification.fields.update({"label": "Media", "shares": "movies, tv"})
        rendered = render(notification, self.config)
        self.assertEqual(rendered.title, "storagecenter: Disk Media back under the space threshold (92.4% used)")
        self.assertIn("Shared folders: movies, tv", rendered.text)
        self.assertIn("Severity: info", rendered.text)
        self.assertNotIn("You have received this notification", rendered.text)

    def test_filesystem_alert_falls_back_to_tag_then_mount_dir(self):
        notification = Notification(subject="s", body="", event="monit-filesystem", severity="warning",
                                    fields={"service": "filesystem_x", "tags": "backup, cold", "mount_dir": "/srv/x"})
        self.assertIn("Disk backup is running out of space", render(notification, self.config).title)
        notification = Notification(subject="s", body="", event="monit-filesystem", severity="warning",
                                    fields={"service": "filesystem_x", "mount_dir": "/srv/x"})
        self.assertIn("Disk /srv/x is running out of space", render(notification, self.config).title)

    def test_missing_mountpoint(self):
        notification = Notification(subject="s", body="", event="monit-filesystem", severity="warning",
                                    fields={"service": "mountpoint_srv_x", "mount_dir": "/srv/x"})
        self.assertIn("Mount point /srv/x is missing", render(notification, self.config).title)

    def test_resource_kinds(self):
        for description, kind in (("cpu user usage of 97%", "CPU"), ("mem usage of 91%", "Memory"),
                                  ("loadavg (1min) of 5.0", "Load average"), ("something", "Resource")):
            notification = Notification(subject="s", body="", event="monit-resource", severity="warning",
                                        fields={"description": description})
            self.assertIn(f"{kind} usage is high", render(notification, self.config).title, description)
        notification = Notification(subject="s", body="", event="monit-resource", recovery=True,
                                    fields={"description": "cpu user usage of 10%"})
        self.assertIn("CPU back to normal", render(notification, self.config).title)

    def test_process(self):
        notification = classify("Monitoring alert -- Does not exist nginx", "Service: nginx\nEvent: Does not exist\n")
        self.assertEqual(render(notification, self.config).title, "storagecenter: Service nginx: does not exist")

    def test_smart_prefers_model(self):
        notification = Notification(subject="s", body="", event="smart", severity="critical",
                                    fields={"type": "Health", "device": "/dev/sda", "model": "WDC WD40EFRX"})
        self.assertIn("SMART Health on WDC WD40EFRX (/dev/sda)", render(notification, self.config).title)

    def test_mdadm_splits_camel_case(self):
        notification = classify("DegradedArray event on /dev/md0:nas", "")
        self.assertIn("RAID /dev/md0: degraded array", render(notification, self.config).title)

    def test_cron_and_unknown(self):
        self.assertIn("Scheduled task 'Nightly backup' finished", render(classify("Cron - Nightly backup", ""), self.config).title)
        self.assertIn("Scheduled task finished", render(classify("Cron", ""), self.config).title)
        self.assertEqual(render(classify("Whatever happened", ""), self.config).title, "storagecenter: Whatever happened")


class BodyTest(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_body_excerpt_truncates(self):
        body = "\n".join(str(i) for i in range(MAX_BODY_LINES + 5))
        excerpt = body_excerpt(body)
        self.assertTrue(excerpt.endswith("[... 5 more lines]"))
        self.assertEqual(body_excerpt("a\nb"), "a\nb")

    def test_cron_output_is_included_monit_body_is_not(self):
        rendered = render(classify("Cron - Job", "line 1\nline 2\n"), self.config)
        self.assertIn("line 2", rendered.text)
        self.assertIn("<pre>line 1\nline 2</pre>", rendered.html)
        rendered = render(classify(MONIT_FS_SUBJECT, MONIT_FS_BODY), self.config)
        self.assertNotIn("<pre>", rendered.html)

    def test_html_escapes_and_links(self):
        rendered = render(classify("Cron - <b>", "<script>x</script>"), self.config)
        self.assertIn("&lt;script&gt;", rendered.html)
        self.assertIn("Scheduled task &#x27;&lt;b&gt;&#x27; finished", rendered.html)
        self.assertIn('href="https://nas.local/"', rendered.html)
        self.assertIn("storagecenter.home.arpa", rendered.html)

    def test_html_without_ui_url(self):
        rendered = render(classify("Cron", ""), make_config(uiurl=""))
        self.assertNotIn("href", rendered.html)


if __name__ == "__main__":
    unittest.main()
