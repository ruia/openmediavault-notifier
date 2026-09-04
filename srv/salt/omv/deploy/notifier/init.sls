# Make sure custom Jinja filters are registered.
{% set _ = salt['omv_utils.register_jinja_filters']() %}

include:
  - .{{ salt['pillar.get']('deploy_notifier', 'default') }}
