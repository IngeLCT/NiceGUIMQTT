from __future__ import annotations

import json
from typing import Any, Optional

import paho.mqtt.client as mqtt

import sensor_config
import state


def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _to_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return None


def _rc_value(reason_code: Any) -> int:
    return int(getattr(reason_code, 'value', reason_code))


# =========================
# Supervisor (discovery)
# =========================

def supervisor_on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None) -> None:
    rc = _rc_value(reason_code)
    print(f'[SUPERVISOR] Conectado al broker MQTT con codigo {rc}')
    if rc == 0:
        client.subscribe(state.AVAILABLE_TOPIC_PATTERN)


def supervisor_on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    # Descubrimiento: EQ1/<sensor>/data
    try:
        topic = msg.topic or ''
    except Exception:
        return

    parts = topic.split('/')
    if len(parts) >= 3 and parts[0] == state.EQ_PREFIX and parts[2] == 'data':
        sensor = parts[1]
        if sensor:
            with state.sensor_lock:
                state.available_sensors.add(sensor)


# =========================
# Cliente de medicion
# =========================

def mqtt_on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None) -> None:
    rc = _rc_value(reason_code)
    print(f'[MEAS] Conectado al broker MQTT con codigo {rc}')
    if rc == 0:
        with state.data_lock:
            # Suscribirse a todos los tópicos de los sensores seleccionados. Para
            # compatibilidad, si ``current_topics`` está vacío se usa
            # ``current_topic``.
            topics = list(state.current_topics.values()) if state.current_topics else ([state.current_topic] if state.current_topic else [])
        for t in topics:
            if t:
                try:
                    client.subscribe(t)
                except Exception as e:
                    print('Error al subscribir a', t, e)


def mqtt_on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    """Parsea el JSON dependiendo del sensor seleccionado y guarda en buffers dinamicos."""

    # Determinar sensor a partir del tópico y verificar que esté seleccionado
    try:
        topic = msg.topic or ''
    except Exception:
        return
    parts = topic.split('/') if topic else []
    if len(parts) < 3 or parts[0] != state.EQ_PREFIX or parts[2] != 'data':
        return
    sensor_name = parts[1]
    with state.data_lock:
        if sensor_name not in state.selected_sensors:
            return
        selected_channels = state.selected_channel_map.get(sensor_name)

    try:
        payload = msg.payload.decode('utf-8', errors='ignore')
        j = json.loads(payload)
    except Exception as e:
        print('Error al decodificar JSON:', e)
        return

    # t_ms siempre obligatorio
    t_ms = _to_int(j.get('t_ms'))
    if t_ms is None:
        return

    # Configuración de este sensor
    profile = sensor_config.get_profile(sensor_name)
    metrics = profile.get('metrics', [])
    required = profile.get('required_keys', ['t_ms'])

    # Validar required_keys (además de t_ms)
    for rk in required:
        if rk == 't_ms':
            continue
        if rk not in j:
            return

    # Leer avg_dropped si aplica
    avg_key = profile.get('avg_dropped_key')
    avg = _to_int(j.get(avg_key)) if avg_key else None

    # Leer métricas dinámicas de este sensor
    values: dict[str, Optional[float]] = {}
    for m in metrics:
        mid = m['id']
        # Si el usuario definió un subconjunto de canales para este sensor, ignorar
        # los no seleccionados
        if selected_channels is not None and mid not in selected_channels:
            continue
        raw = j.get(m.get('json_key'))
        val = _to_float(raw)
        if val is not None:
            try:
                val = val * float(m.get('scale', 1.0))
            except Exception:
                pass
        values[mid] = val

    # Prefijar métricas con el nombre del sensor
    prefixed_values: dict[str, Optional[float]] = {f'{sensor_name}:{mid}': v for mid, v in values.items()}

    # Guardar valores en estado y en buffers si se está midiendo
    with state.data_lock:
        state.last_avg_dropped = avg
        # Actualizar últimos valores para cada métrica de este sensor
        for pref_mid, val in prefixed_values.items():
            state.last_values[pref_mid] = val

        if state.is_measuring:
            # Calcular tiempo relativo común. Utiliza periodo de muestreo global.
            sample_period = float(profile.get('sample_period_s', state.SAMPLE_PERIOD_S))
            # Avanzar el índice global de muestra
            t_rel_s = state.measurement_sample_index * sample_period
            state.measurement_sample_index += 1
            state.measurement_elapsed_s = t_rel_s
            state.last_t_s = t_rel_s

            # Guardar tiempo
            state.buf_t_s.append(t_rel_s)

            # Para cada métrica activa, añadir el valor o el último valor conocido
            for mid in state.current_metric_ids:
                # mid tiene forma sensor:metric
                if mid in prefixed_values:
                    val = prefixed_values[mid]
                else:
                    # Usar el último valor conocido (None si no hay)
                    val = state.last_values.get(mid)
                state.buf_values[mid].append(val)


# =========================
# Helpers de arranque
# =========================

def start_supervisor_mqtt() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if state.SUPERVISOR_USER:
        client.username_pw_set(state.SUPERVISOR_USER, state.SUPERVISOR_PASS)
    client.on_connect = supervisor_on_connect
    client.on_message = supervisor_on_message
    client.connect(state.MQTT_BROKER, state.MQTT_PORT, keepalive=60)
    client.loop_start()
    state.supervisor_client = client
    return client


def start_mqtt() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if state.MQTT_USER:
        client.username_pw_set(state.MQTT_USER, state.MQTT_PASS)
    client.on_connect = mqtt_on_connect
    client.on_message = mqtt_on_message
    client.connect(state.MQTT_BROKER, state.MQTT_PORT, keepalive=60)
    client.loop_start()
    state.mqtt_client = client
    return client


def set_current_sensor(sensor: str) -> None:
    """
    Configura un único sensor activo. Este helper se mantiene para compatibilidad
    hacia atrás pero delega en ``set_current_sensors``. Si el valor de ``sensor``
    está vacío no realiza ningún cambio.
    """
    if not sensor:
        return
    set_current_sensors([sensor])


def set_current_sensors(sensors: list[str]) -> None:
    """
    Actualiza la lista de sensores activos, prepara métricas/buffers y re-suscribe a los
    tópicos de cada sensor.

    Recibe una lista de nombres de sensores. Cualquier sensor no incluido en la nueva
    lista será eliminado de las suscripciones. Se reinicia el estado global (series,
    buffers) si la lista de sensores cambia.
    """
    if not sensors:
        return

    # Normalizar y eliminar duplicados preservando orden
    seen = set()
    sensors_unique: list[str] = []
    for s in sensors:
        if s and s not in seen:
            sensors_unique.append(str(s))
            seen.add(s)

    with state.data_lock:
        prev_sensors = list(state.selected_sensors)

    # Si hay algún cambio en la lista de sensores, reiniciar buffers/series
    if set(prev_sensors) != set(sensors_unique):
        state.reset_all_state()

    # Construir mapa de topicos
    new_topics: dict[str, str] = {}
    metric_ids_prefixed: list[str] = []
    for sensor_name in sensors_unique:
        topic = f'{state.EQ_PREFIX}/{sensor_name}/data'
        new_topics[sensor_name] = topic
        # Obtener métricas de este sensor y prefijar con el nombre del sensor
        for mid in sensor_config.get_metric_ids(sensor_name):
            metric_ids_prefixed.append(f'{sensor_name}:{mid}')

    # Preparar buffers dinámicos
    state.ensure_metric_buffers(metric_ids_prefixed)

    # Actualizar variables de estado
    with state.data_lock:
        old_topics = dict(state.current_topics)
        state.selected_sensors = list(sensors_unique)
        state.current_topics = dict(new_topics)

        # Mantener compatibilidad: usar el primer sensor para selected_sensor/current_topic
        if sensors_unique:
            state.selected_sensor = sensors_unique[0]
            state.current_topic = new_topics[sensors_unique[0]]
        else:
            state.selected_sensor = None
            state.current_topic = None

    # Suscribirse a nuevos tópicos y desuscribirse de los que ya no apliquen
    client = state.mqtt_client
    if client is not None:
        # Desuscribir viejos tópicos
        for old_topic in old_topics.values():
            if old_topic and old_topic not in new_topics.values():
                try:
                    client.unsubscribe(old_topic)
                except Exception:
                    pass
        # Suscribir nuevos tópicos
        for sensor_name, topic in new_topics.items():
            if topic and topic not in old_topics.values():
                try:
                    client.subscribe(topic)
                except Exception as e:
                    print('Error al subscribir a', topic, e)

