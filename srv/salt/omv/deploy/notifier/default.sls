{% set config_dir = '/etc/openmediavault-notifier' %}
{% set settings = salt['omv_conf.get']('conf.service.notifier') %}
{% set channels = salt['omv_conf.get']('conf.service.notifier.channel') %}
{% set email = salt['omv_conf.get']('conf.system.notification.email') %}
{% set dns = salt['omv_conf.get']('conf.system.network.dns') %}
{% set mountpoints = salt['omv_conf.get_by_filter'](
  'conf.system.filesystem.mountpoint',
  {'operator': 'equals', 'arg0': 'hidden', 'arg1': '0'}) %}
{% set sharedfolders = salt['omv_conf.get']('conf.system.sharedfolder') %}

{% set channel_list = [] %}
{% for channel in channels %}
{% set _ = channel_list.append({
  'uuid': channel.uuid,
  'enable': channel.enable | to_bool,
  'name': channel.name,
  'type': channel.type,
  'url': channel.url,
  'token': channel.token,
  'chatid': channel.chatid,
  'topic': channel.topic,
  'recipients': channel.recipients,
  'sendername': channel.sendername,
  'events': channel.events,
  'skiprecovery': channel.skiprecovery | to_bool}) %}
{% endfor %}

{% set email_channel_enabled = channel_list | selectattr('type', 'equalto', 'email')
  | selectattr('enable') | list | length > 0 %}

{% set mountpoint_list = [] %}
{% for mountpoint in mountpoints %}
{% set _ = mountpoint_list.append({
  'uuid': mountpoint.uuid,
  'fsname': mountpoint.fsname,
  'dir': mountpoint.dir,
  'fstype': mountpoint.type,
  'tags': mountpoint.comment}) %}
{% endfor %}

{% set sharedfolder_list = [] %}
{% for sharedfolder in sharedfolders %}
{% set _ = sharedfolder_list.append({
  'name': sharedfolder.name,
  'mntentref': sharedfolder.mntentref,
  'reldirpath': sharedfolder.reldirpath}) %}
{% endfor %}

{% set dataset = {
  'version': 1,
  'enable': settings.enable | to_bool,
  'replaceemail': settings.replaceemail | to_bool,
  'uiurl': settings.uiurl,
  'hostname': dns.hostname,
  'domainname': dns.domainname,
  'email': {
    'enable': email.enable | to_bool,
    'server': email.server,
    'port': email.port | int,
    'tls': email.tls,
    'sender': email.sender,
    'authenable': email.authentication.enable | to_bool,
    'username': email.authentication.username,
    'password': email.authentication.password if email_channel_enabled else '',
    'primaryemail': email.primaryemail,
    'secondaryemail': email.secondaryemail},
  'channels': channel_list,
  'mountpoints': mountpoint_list,
  'sharedfolders': sharedfolder_list} %}

create_notifier_config_dir:
  file.directory:
    - name: {{ config_dir }}
    - user: root
    - group: openmediavault-notify
    - mode: '0750'

configure_notifier_config:
  file.serialize:
    - name: {{ config_dir }}/config.json
    - dataset: {{ dataset | json }}
    - serializer: json
    - user: root
    - group: openmediavault-notify
    - mode: '0640'
    - show_changes: False
    - require:
      - file: create_notifier_config_dir
