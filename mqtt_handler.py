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
            topic = state.current_topic
        if topic:
            client.subscribe(topic)


def mqtt_on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    """Parsea el JSON dependiendo del sensor seleccionado y guarda en buffers dinamicos."""

    # Filtra por topico actual (por si hay suscripciones viejas)
    with state.data_lock:
        topic = state.current_topic
        sensor_name = state.selected_sensor

    if not sensor_name:
        return

    if topic and getattr(msg, 'topic', None) and msg.topic != topic:
        return

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

    profile = sensor_config.get_profile(sensor_name)
    metrics = profile.get('metrics', [])
    required = profile.get('required_keys', ['t_ms'])

    # Validar required_keys (ademas de t_ms)
    for rk in required:
        if rk == 't_ms':
            continue
        if rk not in j:
            return

    # Leer avg_dropped si aplica
    avg_key = profile.get('avg_dropped_key')
    avg = _to_int(j.get(avg_key)) if avg_key else None

    # Leer metricas dinamicas
    values: dict[str, Optional[float]] = {}
    for m in metrics:
        mid = m['id']
        raw = j.get(m.get('json_key'))
        val = _to_float(raw)
        if val is not None:
            try:
                val = val * float(m.get('scale', 1.0))
            except Exception:
                pass
        values[mid] = val

    # Guardar y registrar en buffers si se esta midiendo
    with state.data_lock:
        state.last_avg_dropped = avg
        for mid, val in values.items():
            state.last_values[mid] = val

        if state.is_measuring:
            # Tiempo relativo ideal (por indice) - puedes hacerlo por t_ms si quieres
            sample_period = float(profile.get('sample_period_s', state.SAMPLE_PERIOD_S))
            t_rel_s = state.measurement_sample_index * sample_period
            state.measurement_sample_index += 1
            state.measurement_elapsed_s = t_rel_s
            state.last_t_s = t_rel_s

            state.buf_t_s.append(t_rel_s)
            for mid in state.current_metric_ids:
                state.buf_values[mid].append(values.get(mid))


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
    """Actualiza sensor seleccionado, prepara metricas/buffers y re-suscribe."""
    if not sensor:
        return

    # Si cambiamos de sensor, reiniciamos estado para no mezclar series
    with state.data_lock:
        prev = state.selected_sensor

    if prev is not None and prev != sensor:
        state.reset_all_state()

    new_topic = f'{state.EQ_PREFIX}/{sensor}/data'

    # Preparar buffers segun config del sensor
    metric_ids = sensor_config.get_metric_ids(sensor)
    state.ensure_metric_buffers(metric_ids)

    with state.data_lock:
        old_topic = state.current_topic
        state.selected_sensor = sensor
        state.current_topic = new_topic

    # Actualiza suscripcion en el cliente MQTT de medicion
    client = state.mqtt_client
    if client is not None:
        try:
            if old_topic:
                client.unsubscribe(old_topic)
        except Exception:
            pass
        try:
            client.subscribe(new_topic)
        except Exception as e:
            print('Error al subscribir a', new_topic, e)

