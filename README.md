# openmediavault-notifier

[![CI](https://github.com/ruia/openmediavault-notifier/actions/workflows/ci.yml/badge.svg)](https://github.com/ruia/openmediavault-notifier/actions/workflows/ci.yml)

openmediavault 8 plugin that forwards system notifications to Discord, Slack,
Telegram, ntfy and Gotify, and sends improved email messages.

Every notification openmediavault emits is classified, enriched and rendered
before delivery. A file system alert names the disk label, device, model and
the shared folders on it instead of a bare UUID:

```
storagecenter: Disk Media back under the space threshold (92.4% used)
Severity: info
Disk: Media
Device: /dev/sda1
Model: WDC WD40EFRX-68N32N0
Mount point: /srv/dev-disk-by-uuid-01fd2738-e207-4442-b826-a6ac1025953a
Shared folders: movies, tv
Event: Resource limit succeeded
Details: space usage test succeeded [current space usage = 92.4%]
```

## Features

- Channels: Discord, Slack, Telegram, ntfy, Gotify, Email (text + HTML).
- Event classes: monitoring file systems, monitoring CPU/memory/load,
  monitoring services, S.M.A.R.T., RAID (mdadm), package updates, scheduled
  tasks, authentication, system, other.
- Per channel: enable, event filter, skip recovery events, sender name.
- Disk and share enrichment for file system and S.M.A.R.T. events.
- Optional replacement of the stock openmediavault emails.
- Test button per channel.
- Python standard library only at runtime, no third-party modules.

## Requirements

- openmediavault 8.0.5-2 or later. Older 8.x releases drop all outgoing mail
  once email notifications are enabled after the installation.
- Email notifications enabled in System > Notification > Settings. The
  notification pipeline that feeds this plugin only runs when the mail
  system is active. You can keep an external SMTP server configured and still
  discard the stock emails, see Settings below.

## Install

Download the `.deb` from the [releases](https://github.com/ruia/openmediavault-notifier/releases)
page, copy it to the server and install it:

```
apt install ./openmediavault-notifier_8.1.0_all.deb
```

Then hard-reload the web interface (Ctrl+Shift+R). The web interface caches
its route table at start, a plugin page opened before a reload shows the
"Software Failure" 404 page.

System > Plugins lists the installed version. Its repository shows `/now`,
apt's name for packages installed from a file.

Upgrades use the same command with the newer file. Uninstalling from
System > Plugins or with `apt purge` restores stock email delivery and
removes the configuration.

## Configuration

System > Notification > Notifier.

### Channels

Create one channel per destination.

| Type | Fields |
|---|---|
| Discord | incoming webhook URL, optional sender name |
| Slack | incoming webhook URL, optional sender name |
| Telegram | bot token, chat id |
| ntfy | server URL, topic, optional access token |
| Gotify | server URL, application token |
| Email | recipients (defaults to the notification settings addresses), optional sender name |

Common fields:

- Events: the event classes forwarded to this channel, empty means all.
- Skip recovery events: drop "back to normal" messages.
- Sender name: shown as the sender in Discord and Slack, used in the From
  header of emails. Defaults to the host name.

After saving, apply the pending configuration, then use the test button.

### Settings

- Enabled: global switch.
- Replace openmediavault emails: discards the stock emails to the primary
  and secondary addresses of the notification settings through the Postfix
  transport map `/etc/postfix/notifier_transport`, which the plugin adds to
  `OMV_POSTFIX_MAIN_TRANSPORT_MAPS` on install. Mail to other addresses, for
  example to users, is still delivered. Keep an Email channel to receive the
  improved emails. Requires an external SMTP server in the notification
  settings, mails sent through a local Postfix would be discarded too.
- Web interface URL: optional link added to notifications.

## How it works

openmediavault hands a copy of every outgoing notification email to the
scripts in `/usr/share/openmediavault/notification/sink.d/`. This plugin
installs one that runs `omv-notifier dispatch`, which:

1. reads `/etc/openmediavault-notifier/config.json`, rendered by the Salt
   state on every apply (channels, SMTP settings, mount points, shared folders)
2. classifies the message by subject and body into an event class and severity
3. enriches file system and disk events with `lsblk` output and the shared
   folder configuration
4. renders a title, plain text and HTML body
5. delivers to every enabled channel whose event filter matches

The sink runs as the unprivileged `openmediavault-notify` user, uses short
network timeouts and always exits 0 so mail delivery is never affected.

## Troubleshooting

```
journalctl -t omv-notifier -n 50          # delivery log
omv-notifier test <channel uuid>          # same as the test button
omv-notifier events                       # known event classes
cat /etc/openmediavault-notifier/config.json
```

Channel uuids are in the datatable row (edit URL) or in `config.json`.

## Development

```
make test    # unit tests (python3 -m unittest)
make lint    # compile check, php -l, JSON and YAML validation
make build   # dpkg-buildpackage, writes ../openmediavault-notifier_<version>_all.deb
```

Build dependencies: `debhelper`, `dpkg-dev`, `fakeroot`, `make`, `python3`.
Lint additionally uses `php-cli` and `python3-yaml`.

Layout follows the omv-extras plugin conventions:

```
debian/                                  packaging, maintainer scripts, changelog
srv/salt/omv/deploy/notifier/            Salt state rendering the runtime config
usr/share/openmediavault/confdb/         config database creation and migrations
usr/share/openmediavault/datamodels/     config and RPC schemas
usr/share/openmediavault/engined/        PHP module (listeners) and RPC service
usr/share/openmediavault/notification/   sink script
usr/share/openmediavault/workbench/      navigation, routes and pages (YAML)
usr/share/openmediavault-notifier/       Python package
usr/sbin/omv-notifier                    command line entry point
tests/                                   unit tests
```

### Versioning

The version lives in `debian/changelog` and follows the omv-extras scheme:
the first number is the openmediavault major release, so `8.x.y` targets
openmediavault 8. Every release adds a changelog entry with a higher version,
apt only upgrades when the version increases. Configuration migrations in
`confdb/migrations.d/` are named after the version that introduces them and
run once when upgrading from an older version. Tagging `v<version>` on GitHub
builds the package and attaches it to a release, with the changelog entry as
the release notes.

### Roadmap

- Editable message templates per event class.
- Avatar for Discord and Slack.
- Translations.

## License

GPL-3.0-or-later, see [LICENSE](LICENSE).
