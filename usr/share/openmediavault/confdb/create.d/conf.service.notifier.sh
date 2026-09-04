#!/usr/bin/env dash

set -e

. /usr/share/openmediavault/scripts/helper-functions

########################################################################
# Update the configuration.
# <config>
#   <services>
#     <notifier>
#       <enable>1</enable>
#       <replaceemail>0</replaceemail>
#       <uiurl></uiurl>
#       <channels>
#         <channel>
#           <uuid>xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx</uuid>
#           <enable>0|1</enable>
#           <name>xxx</name>
#           <type>discord|slack|telegram|ntfy|gotify|email</type>
#           <url>xxx</url>
#           <token>xxx</token>
#           <chatid>xxx</chatid>
#           <topic>xxx</topic>
#           <recipients>xxx</recipients>
#           <sendername>xxx</sendername>
#           <events>xxx</events>
#           <skiprecovery>0|1</skiprecovery>
#         </channel>
#       </channels>
#     </notifier>
#   </services>
# </config>
########################################################################
if ! omv_config_exists "/config/services/notifier"; then
	omv_config_add_node "/config/services" "notifier"
	omv_config_add_key "/config/services/notifier" "enable" "1"
	omv_config_add_key "/config/services/notifier" "replaceemail" "0"
	omv_config_add_key "/config/services/notifier" "uiurl" ""
	omv_config_add_node "/config/services/notifier" "channels"
fi

exit 0
