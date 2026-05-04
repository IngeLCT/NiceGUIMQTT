# sensor_config.py
# Configuración local del protocolo MQTT para sensores soportados.
# Por ahora solo se mantiene MB1000 / Movimiento.

from __future__ import annotations

from typing import Any, Dict, List


def sensor_type(sensor_name: str) -> str:
    """Extrae el tipo/base del sensor soportando alias conocidos."""
    name = (sensor_name or '').strip()

    if name.startswith('Sensor') and len(name) > len('Sensor'):
        name = name[len('Sensor'):]

    while name and name[-1].isdigit():
        name = name[:-1]

    if name in {'Mov', 'Movimiento', 'MB1000'}:
        return 'MB1000'

    return name or 'MB1000'


MB1000_PROFILE: Dict[str, Any] = {
    'Name': 'Sensor de Movimiento MB1000',
    'payload_format': 'sensor_state_fixed_v1',
    'sensor_id': 0x01,
    'sample_period_s': 0.25,
    'protocol': {
        'ack': 0x06,
        'total_bytes': 14,
        'endianness': 'little',
        'state_offset': 3,
        'state_map': {
            0x00: 'heartbeat',
            0x11: 'selected',
            0x22: 'measuring',
        },
        'command_frame': {
            'total_bytes': 4,
            'commands': {
                'select': 0x10,
                'start': 0x11,
                'stop': 0x12,
                'deselect': 0x13,
                'ok': 0x20,
            },
        },
        'fields': {
            'sensor_state': {
                'byte_start': 3,
                'byte_end': 3,
                'size_bytes': 1,
                'type': 'uint8',
                'description': 'Estado operativo del sensor',
            },
            'time_s_x100': {
                'byte_start': 4,
                'byte_end': 7,
                'size_bytes': 4,
                'type': 'uint32',
                'signed': False,
                'scale': 0.01,
                'unit': 's',
                'treatment': 'linear',
                'description': 'Tiempo de medición en segundos multiplicado por 100',
            },
            'distance_m_x100': {
                'byte_start': 8,
                'byte_end': 9,
                'size_bytes': 2,
                'type': 'uint16',
                'signed': False,
                'scale': 0.01,
                'unit': 'm',
                'treatment': 'linear',
                'description': 'Distancia en metros multiplicada por 100',
            },
            'velocity_m_s_x100': {
                'byte_start': 10,
                'byte_end': 11,
                'size_bytes': 2,
                'type': 'int16',
                'signed': True,
                'scale': 0.01,
                'unit': 'm/s',
                'treatment': 'linear',
                'description': 'Velocidad en m/s multiplicada por 100',
            },
            'acceleration_m_s2_x100': {
                'byte_start': 12,
                'byte_end': 13,
                'size_bytes': 2,
                'type': 'int16',
                'signed': True,
                'scale': 0.01,
                'unit': 'm/s²',
                'treatment': 'linear',
                'description': 'Aceleración en m/s² multiplicada por 100',
            },
        },
    },
    'metrics': [
        {
            'id': 'dist_m',
            'source_field': 'distance_m_x100',
            'scale': 0.01,
            'label': 'Distancia',
            'unit': 'm',
            'color': '#a4bdf4',
            'hover_name': 'Distancia',
            'Default': True,
            'y_range': [0.0, 5.0],
        },
        {
            'id': 'vel_m_s',
            'source_field': 'velocity_m_s_x100',
            'scale': 0.01,
            'label': 'Velocidad',
            'unit': 'm/s',
            'color': '#5fd35f',
            'hover_name': 'Velocidad',
            'Default': False,
            'y_range': [-6.0, 6.0],
        },
        {
            'id': 'acc_m_s2',
            'source_field': 'acceleration_m_s2_x100',
            'scale': 0.01,
            'label': 'Aceleracion',
            'unit': 'm/s²',
            'color': '#ff4d4d',
            'hover_name': 'Aceleracion',
            'Default': False,
            'y_range': [-11.0, 11.0],
        },
    ],
}


SENSOR_TYPES: Dict[str, Dict[str, Any]] = {
    'MB1000': MB1000_PROFILE,
}


DEFAULT_TYPE_PROFILE: Dict[str, Any] = MB1000_PROFILE


def get_profile(sensor_name: str) -> Dict[str, Any]:
    return SENSOR_TYPES.get(sensor_type(sensor_name), DEFAULT_TYPE_PROFILE)


def get_metrics(sensor_name: str) -> List[Dict[str, Any]]:
    return list(get_profile(sensor_name).get('metrics', []))


def is_default_metric(metric: Dict[str, Any]) -> bool:
    if 'Default' in metric:
        return bool(metric.get('Default'))
    return bool(metric.get('default', True))


def get_default_metrics(sensor_name: str) -> List[Dict[str, Any]]:
    return [m for m in get_metrics(sensor_name) if is_default_metric(m)]


def get_default_metric_ids(sensor_name: str) -> List[str]:
    return [m['id'] for m in get_default_metrics(sensor_name)]


def get_metric_ids(sensor_name: str) -> List[str]:
    return [m['id'] for m in get_metrics(sensor_name)]


def get_sensor_display_name(sensor_name: str) -> str:
    prof = get_profile(sensor_name)
    name = prof.get('Name') or prof.get('name')
    return str(name) if name else sensor_name


def get_metric_by_id(sensor_name: str, metric_id: str) -> Dict[str, Any] | None:
    for metric in get_metrics(sensor_name):
        if metric.get('id') == metric_id:
            return dict(metric)
    return None
