# sensor_config.py
# Configuración dinámica por tipo de sensor (Sensor<Tipo>)

from __future__ import annotations
from typing import Any, Dict, List, Optional


def sensor_type(sensor_name: str) -> str:
    """
    Extrae el tipo desde el nombre 'Sensor<Tipo>'.
    Ej:
      SensorMov  -> Mov
      SensorTemp -> Temp
    """
    if sensor_name.startswith('Sensor') and len(sensor_name) > len('Sensor'):
        return sensor_name[len('Sensor'):]
    return sensor_name


# -------------------------
# CONFIGURACIÓN POR TIPO
# -------------------------
# Cada tipo define:
#   required_keys: claves mínimas que deben existir en el JSON (además de t_ms)
#   metrics: lista de métricas para graficar/mostrar (dinámicas)
#     - id: nombre interno (buffers, tabla)
#     - json_key: clave en el JSON
#     - scale: multiplicador (cm->m = 0.01)
#     - label, unit, color, hover_name: para UI
#   avg_dropped_key: (opcional) clave para indicador avg_dropped

SENSOR_TYPES: Dict[str, Dict[str, Any]] = {
    "Mov": {
        "Name": "Sensor de Movimiento",
        "required_keys": ["t_ms", "cm", "v_cm_s", "a_cm_s2"],
        "metrics": [
            {
                "id": "dist_m",
                "json_key": "cm",
                "scale": 0.01,
                "label": "Distancia",
                "unit": "m",
                "color": "#1f77b4",
                "hover_name": "Distancia",
                "Default": True,
            },
            {
                "id": "vel_m_s",
                "json_key": "v_cm_s",
                "scale": 0.01,
                "label": "Velocidad",
                "unit": "m/s",
                "color": "#2ca02c",
                "hover_name": "Velocidad",
                "Default": False,
            },
            {
                "id": "acc_m_s2",
                "json_key": "a_cm_s2",
                "scale": 0.01,
                "label": "Aceleracion",
                "unit": "m/s²",
                "color": "#ff0000",
                "hover_name": "Aceleracion",
                "Default": False,
            },
        ],
        "avg_dropped_key": None,  # indicador opcional
    },

    "Gyro": {
        "Name": "Sensor Giroscopio y Aceleracion",
        # claves mínimas esperadas (si falta una, se ignora el mensaje)
        "required_keys": ["t_ms", "temp_c", "ax", "ay", "az", "gx", "gy", "gz"],

        # métricas que se van a graficar (una gráfica por métrica)
        "metrics": [
            {
                "id": "temp_c",
                "json_key": "temp_c",
                "scale": 1.0,
                "label": "Temperatura",
                "unit": "°C",
                "color": "#ff7f0e",
                "Default": True,
                "hover_name": "Temperatura",

            },

            # Aceleración (unidades: depende de tu IMU; común: m/s² o g)
            # Si tu IMU entrega en "g", deja unit="g" y scale=1.0
            # Si entrega en m/s², unit="m/s²" y scale=1.0
            {
                "id": "ax",
                "json_key": "ax",
                "scale": 1.0,
                "label": "Aceleracion X",
                "unit": "m/s²",
                "color": "#1f77b4",
                "Default": True,
                "hover_name": "Ax",
            },
            {
                "id": "ay",
                "json_key": "ay",
                "scale": 1.0,
                "label": "Aceleracion Y",
                "unit": "m/s²",
                "color": "#2ca02c",
                "Default": False,
                "hover_name": "Ay",
            },
            {
                "id": "az",
                "json_key": "az",
                "scale": 1.0,
                "label": "Aceleracion Z",
                "unit": "m/s²",
                "color": "#d62728",
                "hover_name": "Az",
                "Default": False,
            },

            # Giro (unidades: común: deg/s o rad/s)
            # Ajusta unit según lo que mandes realmente.
            {
                "id": "gx",
                "json_key": "gx",
                "scale": 1.0,
                "label": "Giro X",
                "unit": "rad/s",
                "color": "#9467bd",
                "hover_name": "Gx",
                "Default": False,
            },
            {
                "id": "gy",
                "json_key": "gy",
                "scale": 1.0,
                "label": "Giro Y",
                "unit": "rad/s",
                "color": "#8c564b",
                "hover_name": "Gy",
                "Default": False,
            },
            {
                "id": "gz",
                "json_key": "gz",
                "scale": 1.0,
                "label": "Giro Z",
                "unit": "rad/s",
                "color": "#e377c2",
                "hover_name": "Gz",
                "Default": False,
            },
        ],

        "avg_dropped_key": None,
    },

    "Lux": {
        "required_keys": ["t_ms", "Lux"],
        "Name": "Sensor de Lux",
        "metrics": [
            {
                "id": "Lux",
                "json_key": "Lux",
                "scale": 1.0,
                "label": "Lux",
                "unit": "lux",
                "color": "#003300",
                "hover_name": "Lux",
                "Default": True,
            },
        ],
        "avg_dropped_key": None,
    },
}

# Fallback si llega un sensor no configurado (recomendado dejarlo para no "tronar" la app)
DEFAULT_TYPE_PROFILE: Optional[Dict[str, Any]] = {
    "required_keys": ["t_ms"],
    "metrics": [],
    "avg_dropped_key": "avg_dropped",
}


def get_profile(sensor_name: str) -> Dict[str, Any]:
    """
    Devuelve el perfil para un sensor.
    Busca por tipo extraído de Sensor<Tipo>. Si no existe, usa DEFAULT_TYPE_PROFILE.
    """
    t = sensor_type(sensor_name)
    return SENSOR_TYPES.get(
        t,
        DEFAULT_TYPE_PROFILE or {"required_keys": ["t_ms"], "metrics": [], "avg_dropped_key": None},
    )


def get_metrics(sensor_name: str) -> List[Dict[str, Any]]:
    return list(get_profile(sensor_name).get("metrics", []))


def is_default_metric(metric: Dict[str, Any]) -> bool:
    """Indica si una métrica debe iniciar habilitada.

    Acepta la clave "Default" (como la pides) y también "default".
    Si no existe ninguna de las dos, se asume True (compatibilidad).
    """
    if "Default" in metric:
        return bool(metric.get("Default"))
    return bool(metric.get("default", True))


def get_default_metrics(sensor_name: str) -> List[Dict[str, Any]]:
    """Métricas que inician habilitadas según Default/default."""
    return [m for m in get_metrics(sensor_name) if is_default_metric(m)]


def get_default_metric_ids(sensor_name: str) -> List[str]:
    """IDs de métricas habilitadas por defecto."""
    return [m["id"] for m in get_default_metrics(sensor_name)]


def get_metric_ids(sensor_name: str) -> List[str]:
    return [m["id"] for m in get_metrics(sensor_name)]

def get_sensor_display_name(sensor_name: str) -> str:
    """Nombre amigable para mostrar en UI."""
    prof = get_profile(sensor_name)
    name = prof.get('Name') or prof.get('name')
    return str(name) if name else sensor_name
