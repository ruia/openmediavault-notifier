#!/usr/bin/env dash

set -e

. /usr/share/openmediavault/scripts/helper-functions

omv_config_add_key "/config/services/notifier/channels/channel" "sendername" ""

exit 0
