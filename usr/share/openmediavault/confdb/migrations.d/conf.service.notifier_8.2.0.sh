#!/usr/bin/env dash

set -e

. /usr/share/openmediavault/scripts/helper-functions

omv_config_add_key "/config/services/notifier/channels/channel" "transport" "botapi"
omv_config_add_key "/config/services/notifier/channels/channel" "mtproxy" ""
omv_config_add_key "/config/services/notifier/channels/channel" "apiid" ""
omv_config_add_key "/config/services/notifier/channels/channel" "apihash" ""

exit 0
