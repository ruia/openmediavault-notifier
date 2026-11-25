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
- Python standard library only at runtime, no third-party modules. The
  optional Telegram MTProxy connection is the one exception, it uses a
  separately installed runtime.

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
| Telegram | bot token, chat id, connection (Bot API or MTProxy) |
| ntfy | server URL, topic, optional access token |
| Gotify | server URL, application token |
| Email | recipients (defaults to the notification settings addresses), optional sender name |

Common fields:

- Events: the event classes forwarded to this channel, empty means all.
- Skip recovery events: drop "back to normal" messages.
- Sender name: shown as the sender in Discord and Slack, used in the From
  header of emails. Defaults to the host name.

After saving, apply the pending configuration, then use the test button.

#### Telegram connection

- Bot API (HTTPS), the default: messages go to `api.telegram.org` over
  HTTPS. Nothing else is needed.
- MTProxy: for networks that block `api.telegram.org` but can reach a
  Telegram proxy. Besides the bot token and chat id (a numeric chat id or an
  `@username`) it needs:
  - the proxy link as shared in Telegram, `https://t.me/proxy?…` or
    `tg://proxy?…`, with a simple, `dd` or `ee` (Fake TLS) secret
  - the API ID and API hash of an application registered at
    [my.telegram.org](https://my.telegram.org/apps)

Saving checks the link and the API credentials. Switching a channel back to
the Bot API clears the three MTProxy fields.

MTProxy delivery runs a helper with the interpreter at
`/opt/openmediavault-notifier-mtproxy/bin/python3`, which holds TDLib,
Telegram's own client library. The runtime and the helper are not shipped
yet, until they are an MTProxy channel reports that the runtime is not
installed. Progress is tracked in
[#3](https://github.com/ruia/openmediavault-notifier/issues/3).

The proxy link, the API hash and the bot token never appear on a command
line: they reach `omv-notifier` and the helper on stdin. Error messages show
them as `***`. The proxy cannot read the messages or the bot token, it only
forwards Telegram's encrypted traffic.

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

### MTProxy helper

Telegram channels with the MTProxy connection hand the message to
`usr/share/openmediavault-notifier/omvnotifier/mtproxy_helper.py`, run as
`/opt/openmediavault-notifier-mtproxy/bin/python3 -I <helper>` by the
notification user. The helper:

- reads one JSON object on stdin: `api_id` (number), `api_hash`,
  `bot_token`, `chat_id`, `proxy` (`server`, `port` as a number, `secret` in
  hex) and `text`
- exits 0 once Telegram confirmed the message
- otherwise exits non-zero, the last line it writes to stderr becomes the
  error message, with the bot token, API hash and proxy secret masked
- is stopped after 30 seconds

`omvnotifier/mtproto.py` validates the settings before the helper starts, so
the helper receives a well-formed request.

### Roadmap

- Editable message templates per event class.
- Avatar for Discord and Slack.
- Translations.

## Credits

Telegram MTProxy support was proposed and first built by
[ddark008](https://github.com/ddark008) in
[#3](https://github.com/ruia/openmediavault-notifier/issues/3). The plugin
uses their proxy link parser and settings checks.

## License

GPL-3.0-or-later, see [LICENSE](LICENSE).
