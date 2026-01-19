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
            },
            {
                "id": "vel_m_s",
                "json_key": "v_cm_s",
                "scale": 0.01,
                "label": "Velocidad",
                "unit": "m/s",
                "color": "#2ca02c",
                "hover_name": "Velocidad",
            },
            {
                "id": "acc_m_s2",
                "json_key": "a_cm_s2",
                "scale": 0.01,
                "label": "Aceleracion",
                "unit": "m/s²",
                "color": "#ff0000",
                "hover_name": "Aceleracion",
            },
        ],
        "avg_dropped_key": "avg_dropped",  # indicador opcional
    },

    "Temp": {
        "required_keys": ["t_ms", "temp_c"],
        "metrics": [
            {
                "id": "temp_c",
                "json_key": "temp_c",
                "scale": 1.0,
                "label": "Temperatura",
                "unit": "°C",
                "color": "#ff7f0e",
                "hover_name": "Temperatura",
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


def get_metric_ids(sensor_name: str) -> List[str]:
    return [m["id"] for m in get_metrics(sensor_name)]
