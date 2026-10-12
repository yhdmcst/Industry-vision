"""Bounded workstation-owned runtime policy; no production control or implicit retries."""
PRESETS = {
    'resource': {'keep_alive_minutes': 0, 'timeout_seconds': 90},
    'balanced': {'keep_alive_minutes': 10, 'timeout_seconds': 180},
    'responsive': {'keep_alive_minutes': 30, 'timeout_seconds': 300},
}
DEFAULT_POLICY = {'profile':'balanced', **PRESETS['balanced'], 'autostart':False, 'auto_restart':False}


def validate_policy(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_POLICY): raise ValueError('运行策略字段不完整或包含未知项')
    if value['profile'] not in (*PRESETS, 'custom'): raise ValueError('运行方案无效')
    for key,minimum,maximum in [('keep_alive_minutes',0,60),('timeout_seconds',30,600)]:
        if type(value[key]) is not int or not minimum <= value[key] <= maximum: raise ValueError(f'{key} 须为 {minimum}..{maximum} 整数')
    for key in ('autostart','auto_restart'):
        if type(value[key]) is not bool: raise ValueError(f'{key} 须为布尔值')
    result = dict(value)
    if result['profile'] != 'custom' and any(result[key] != PRESETS[result['profile']][key] for key in PRESETS['balanced']):
        result['profile'] = 'custom'
    return result
