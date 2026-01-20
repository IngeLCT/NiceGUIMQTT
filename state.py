from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Optional

# =========================
# CONFIG MQTT (ajusta aqui)
# =========================
MQTT_BROKER = '192.168.1.136'   # o 'localhost'
MQTT_PORT = 1883

# Credenciales normales para leer un sensor especifico
MQTT_USER = 'eq1'
MQTT_PASS = 'LCT17773180940'

# Credenciales del usuario supervisor (acceso a EQ1/#)
SUPERVISOR_USER = 'supervisor'
SUPERVISOR_PASS = '7773180940'

EQ_PREFIX = 'EQ1'
AVAILABLE_TOPIC_PATTERN = f'{EQ_PREFIX}/#'

# =========================
# CONFIG UI (NiceGUI)
# =========================
UI_HOST = '0.0.0.0'
UI_PORT = 8765

# =========================
# CONFIG TIEMPO / VENTANA
# =========================
SAMPLE_HZ = 4
SAMPLE_PERIOD_S = 1.0 / SAMPLE_HZ
WINDOW_S = 60
MAX_POINTS = int(WINDOW_S * SAMPLE_HZ + 10)
REFRESH_S = 0.25

CSV_EXPORT_FILE = 'series_export.csv'

# =========================
# ESTADO GLOBAL
# =========================

data_lock = threading.Lock()
sensor_lock = threading.Lock()

# Sensores detectados en EQ1/#
available_sensors: set[str] = set()

# Última vez que se vio cada sensor (time.time())
sensor_last_seen: dict[str, float] = {}

# Si un sensor no publica por más de este tiempo (s), se considera desconectado
SENSOR_STALE_S = 5.0

# Sensor seleccionado y topico actual
selected_sensor: Optional[str] = None
current_topic: Optional[str] = None

# Lista de sensores actualmente seleccionados (pueden ser varios).
# Cuando ``selected_sensors`` contiene al menos un elemento, ``selected_sensor`` y
# ``current_topic`` mantendrán el valor del primer sensor para preservar compatibilidad
# hacia atrás. Utilice ``selected_sensors`` y ``current_topics`` para acceder a todos
# los sensores y sus respectivos tópicos.
selected_sensors: list[str] = []

# Diccionario sensor -> tópico actual. Cada sensor seleccionado tiene su propia
# suscripción en el broker MQTT, almacenada en este mapeo.
current_topics: dict[str, str] = {}

# Mapa de sensor -> conjunto de canales (métricas) actualmente activas. Se
# actualiza desde la interfaz de usuario para permitir al usuario elegir qué
# métricas graficar para cada sensor. Las claves son los nombres de los
# sensores y los valores son conjuntos de identificadores de métricas (sin
# prefijo de sensor). Si no existe una entrada para un sensor se asume que
# todas sus métricas están activas.
selected_channel_map: dict[str, set[str]] = {}

# Clientes MQTT (tipados como Any para no acoplar a paho aqui)
mqtt_client: Any = None
supervisor_client: Any = None

# Buffers de graficado
buf_t_s = deque(maxlen=MAX_POINTS)

# Buffers dinamicos por metrica: mid -> deque(y)
buf_values: dict[str, deque] = {}

# Ultimos valores (para etiquetas)
last_t_s: Optional[float] = None
last_values: dict[str, Optional[float]] = {}
last_avg_dropped: Optional[int] = None

# Metricas activas para el sensor actual
current_metric_ids: list[str] = []

# Control de medicion
measurement_duration_s: Optional[float] = None  # None = sin limite
is_measuring: bool = False
measurement_sample_index: int = 0
measurement_elapsed_s: float = 0.0

# Series guardadas
# Estructura por serie:
# { 'name': 'Serie 1', 't_s': [...], 'values': {mid: [...]} }
series_data: list[dict[str, Any]] = []
series_counter: int = 0

# Vista
# None = vista en vivo, entero = indice de serie
display_series_index: Optional[int] = None


def ensure_metric_buffers(metric_ids: list[str]) -> None:
    """Asegura que existan buffers/last_values para las metricas activas."""
    global current_metric_ids

    with data_lock:
        current_metric_ids = list(metric_ids)

        # Crear buffers/last si no existen
        for mid in metric_ids:
            if mid not in buf_values:
                buf_values[mid] = deque(maxlen=MAX_POINTS)
            if mid not in last_values:
                last_values[mid] = None

        # Quitar los que ya no aplican
        for mid in list(buf_values.keys()):
            if mid not in metric_ids:
                buf_values.pop(mid, None)
        for mid in list(last_values.keys()):
            if mid not in metric_ids:
                last_values.pop(mid, None)


def reset_all_state() -> None:
    """Reinicia buffers/series/estado de medicion (sin tocar sensor/topic ni discovery)."""
    global last_t_s, last_avg_dropped
    global measurement_duration_s, is_measuring, measurement_sample_index, measurement_elapsed_s
    global series_data, series_counter, display_series_index

    with data_lock:
        buf_t_s.clear()
        for d in buf_values.values():
            d.clear()

        last_t_s = None
        for k in list(last_values.keys()):
            last_values[k] = None
        last_avg_dropped = None

        measurement_duration_s = None
        is_measuring = False
        measurement_sample_index = 0
        measurement_elapsed_s = 0.0

        series_data = []
        series_counter = 0
        display_series_index = None

