from __future__ import annotations

import struct
import time
from typing import Any, Optional

import paho.mqtt.client as mqtt

import sensor_config
import state

SENSOR_FRAME_ACK = 0x06
SENSOR_COMMAND_FRAME_SIZE = 4
SENSOR_STATE_HEARTBEAT = 0x00
SENSOR_STATE_SELECTED = 0x11
SENSOR_STATE_MEASURING = 0x22

SENSOR_COMMAND_SELECT = 0x10
SENSOR_COMMAND_START = 0x11
SENSOR_COMMAND_STOP = 0x12
SENSOR_COMMAND_DESELECT = 0x13
SENSOR_COMMAND_OK = 0x20


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


def _build_sensor_command_payload(sensor_id: int, command: int) -> bytes:
    return struct.pack('<BBBB', SENSOR_FRAME_ACK, SENSOR_COMMAND_FRAME_SIZE, sensor_id, command)


def _extract_field_value(payload: bytes, field_spec: dict[str, Any], endianness: str) -> int:
    byte_start = int(field_spec['byte_start'])
    byte_end = int(field_spec['byte_end'])
    signed = bool(field_spec.get('signed', False))
    raw = payload[byte_start:byte_end + 1]
    return int.from_bytes(raw, byteorder=endianness, signed=signed)


def _decode_fixed_sensor_frame(payload: Any, sensor_name: str, profile: dict[str, Any]) -> tuple[str, int, dict[str, int]] | None:
    if not isinstance(payload, bytes):
        print(f'[MEAS] Payload binario invalido para {sensor_name}: tipo {type(payload).__name__}, esperado bytes')
        return None

    protocol = profile.get('protocol', {})
    endianness = str(protocol.get('endianness', 'little'))
    total_bytes_expected = _to_int(protocol.get('total_bytes'))
    if total_bytes_expected is None:
        print(f'[MEAS] Perfil sin total_bytes para {sensor_name}')
        return None

    if len(payload) != total_bytes_expected:
        print(f'[MEAS] Longitud invalida para {sensor_name}: {len(payload)} bytes (esperado {total_bytes_expected})')
        return None

    ack, total_bytes, sensor_id = struct.unpack_from('<BBB', payload, 0)
    if ack != SENSOR_FRAME_ACK:
        print(f'[MEAS] ACK invalido para {sensor_name}: 0x{ack:02X}')
        return None
    if total_bytes != total_bytes_expected:
        print(f'[MEAS] total_bytes invalido para {sensor_name}: {total_bytes} (esperado {total_bytes_expected})')
        return None

    expected_sensor_id = _to_int(profile.get('sensor_id'))
    if expected_sensor_id is not None and sensor_id != expected_sensor_id:
        print(f'[MEAS] sensor_id no coincide para {sensor_name}: 0x{sensor_id:02X} (esperado 0x{expected_sensor_id:02X})')
        return None

    state_map = dict(protocol.get('state_map', {}))
    state_offset = _to_int(protocol.get('state_offset'))
    if state_offset is None or state_offset >= len(payload):
        print(f'[MEAS] state_offset invalido para {sensor_name}')
        return None

    sensor_state = payload[state_offset]
    protocol_state = state_map.get(sensor_state)
    if protocol_state is None:
        print(f'[MEAS] sensor_state no soportado para {sensor_name}: 0x{sensor_state:02X}')
        return None

    raw_data: dict[str, int] = {'sensor_state': sensor_state}
    fields = dict(protocol.get('fields', {}))
    for field_name, field_spec in fields.items():
        if field_name == 'sensor_state':
            continue
        try:
            raw_data[field_name] = _extract_field_value(payload, field_spec, endianness)
        except Exception as e:
            print(f'[MEAS] Error al extraer {field_name} de {sensor_name}: {e}')
            return None

    return protocol_state, sensor_id, raw_data


# =========================
# Supervisor (discovery)
# =========================

def supervisor_on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None) -> None:
    rc = _rc_value(reason_code)
    print(f'[SUPERVISOR] Conectado al broker MQTT con codigo {rc}')
    if rc == 0:
        client.subscribe(state.AVAILABLE_TOPIC_PATTERN)



def supervisor_on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
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
                state.sensor_last_seen[sensor] = time.time()


# =========================
# Cliente de medicion
# =========================

def mqtt_on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None) -> None:
    rc = _rc_value(reason_code)
    print(f'[MEAS] Conectado al broker MQTT con codigo {rc}')
    if rc == 0:
        with state.data_lock:
            topics = list(state.current_topics.values()) if state.current_topics else ([state.current_topic] if state.current_topic else [])
        for t in topics:
            if t:
                try:
                    client.subscribe(t)
                except Exception as e:
                    print('Error al subscribir a', t, e)



def _update_sensor_seen(sensor_name: str) -> None:
    if sensor_name:
        with state.sensor_lock:
            state.available_sensors.add(sensor_name)
            state.sensor_last_seen[sensor_name] = time.time()



def _store_protocol_state(sensor_name: str, protocol_state: str) -> None:
    with state.data_lock:
        state.sensor_protocol_state[sensor_name] = protocol_state



def _append_measurement_values(sensor_name: str, profile: dict[str, Any], raw_data: dict[str, int], selected_channels: set[str] | None) -> None:
    metrics = profile.get('metrics', [])
    values: dict[str, Optional[float]] = {}

    for metric in metrics:
        mid = metric['id']
        if selected_channels is not None and mid not in selected_channels:
            continue
        source_field = metric.get('source_field')
        raw = raw_data.get(source_field)
        val = _to_float(raw)
        if val is not None:
            try:
                val = val * float(metric.get('scale', 1.0))
            except Exception:
                pass
        values[mid] = val

    prefixed_values: dict[str, Optional[float]] = {f'{sensor_name}:{mid}': val for mid, val in values.items()}

    with state.data_lock:
        for pref_mid, val in prefixed_values.items():
            state.last_values[pref_mid] = val

        sample_period = float(profile.get('sample_period_s', state.SAMPLE_PERIOD_S))
        t_rel_s = state.measurement_sample_index * sample_period
        state.measurement_sample_index += 1
        state.measurement_elapsed_s = t_rel_s
        state.last_t_s = t_rel_s
        state.buf_t_s.append(t_rel_s)

        for mid in state.current_metric_ids:
            if mid in prefixed_values:
                val = prefixed_values[mid]
            else:
                val = state.last_values.get(mid)
            state.buf_values[mid].append(val)



def mqtt_on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    try:
        topic = msg.topic or ''
    except Exception:
        return

    parts = topic.split('/') if topic else []
    if len(parts) < 3 or parts[0] != state.EQ_PREFIX or parts[2] != 'data':
        return
    sensor_name = parts[1]

    _update_sensor_seen(sensor_name)

    with state.data_lock:
        if sensor_name not in state.selected_sensors:
            return
        selected_channels = state.selected_channel_map.get(sensor_name)

    profile = sensor_config.get_profile(sensor_name)
    payload_format = str(profile.get('payload_format', ''))
    if payload_format != 'sensor_state_fixed_v1':
        print(f'[MEAS] payload_format no soportado para {sensor_name}: {payload_format}')
        return

    decoded = _decode_fixed_sensor_frame(msg.payload, sensor_name, profile)
    if decoded is None:
        return

    protocol_state, _sensor_id, raw_data = decoded
    _store_protocol_state(sensor_name, protocol_state)

    if protocol_state == 'heartbeat':
        with state.data_lock:
            state.is_measuring = False
        return

    if protocol_state == 'selected':
        with state.data_lock:
            state.is_measuring = False
        publish_sensor_command([sensor_name], SENSOR_COMMAND_OK)
        return

    if protocol_state != 'measuring':
        return

    with state.data_lock:
        state.is_measuring = True
    _append_measurement_values(sensor_name, profile, raw_data, selected_channels)


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



def publish_sensor_command(sensor_names: list[str], command: int) -> bool:
    client = state.mqtt_client
    if client is None:
        print('[MEAS] No hay cliente MQTT para publicar comando de sensor')
        return False

    ok = True
    for sensor_name in sensor_names:
        profile = sensor_config.get_profile(sensor_name)
        sensor_id = _to_int(profile.get('sensor_id'))
        if sensor_id is None:
            print(f'[MEAS] No se puede publicar comando para {sensor_name}: perfil sin sensor_id')
            ok = False
            continue

        topic = f'{state.EQ_PREFIX}/{sensor_name}/cmd'
        payload = _build_sensor_command_payload(sensor_id, command)

        try:
            info = client.publish(topic, payload=payload, qos=1, retain=False)
            if getattr(info, 'rc', mqtt.MQTT_ERR_SUCCESS) != mqtt.MQTT_ERR_SUCCESS:
                print(f'[MEAS] Error al publicar comando 0x{command:02X} en {topic}: rc={info.rc}')
                ok = False
        except Exception as e:
            print(f'[MEAS] Error al publicar comando 0x{command:02X} en {topic}:', e)
            ok = False

    return ok



def publish_measurement_command(sensor_names: list[str], start: bool) -> bool:
    return publish_sensor_command(sensor_names, SENSOR_COMMAND_START if start else SENSOR_COMMAND_STOP)



def publish_select_command(sensor_names: list[str]) -> bool:
    return publish_sensor_command(sensor_names, SENSOR_COMMAND_SELECT)



def publish_deselect_command(sensor_names: list[str]) -> bool:
    return publish_sensor_command(sensor_names, SENSOR_COMMAND_DESELECT)



def set_current_sensor(sensor: str) -> None:
    if not sensor:
        return
    set_current_sensors([sensor])



def set_current_sensors(sensors: list[str]) -> None:
    if not sensors:
        return

    seen = set()
    sensors_unique: list[str] = []
    for s in sensors:
        if s and s not in seen:
            sensors_unique.append(str(s))
            seen.add(s)

    with state.data_lock:
        prev_sensors = list(state.selected_sensors)

    if set(prev_sensors) != set(sensors_unique):
        state.reset_all_state()

    new_topics: dict[str, str] = {}
    metric_ids_prefixed: list[str] = []

    with state.data_lock:
        channel_map = dict(state.selected_channel_map)

    for sensor_name in sensors_unique:
        topic = f'{state.EQ_PREFIX}/{sensor_name}/data'
        new_topics[sensor_name] = topic

        if sensor_name not in channel_map:
            defaults = sensor_config.get_default_metric_ids(sensor_name)
            if not defaults:
                defaults = sensor_config.get_metric_ids(sensor_name)
            channel_map[sensor_name] = set(defaults)

        ordered_mids = sensor_config.get_metric_ids(sensor_name)
        chset = channel_map[sensor_name]
        for mid in ordered_mids:
            if mid in chset:
                metric_ids_prefixed.append(f'{sensor_name}:{mid}')

    state.ensure_metric_buffers(metric_ids_prefixed)

    with state.data_lock:
        old_topics = dict(state.current_topics)
        state.selected_sensors = list(sensors_unique)
        state.current_topics = dict(new_topics)
        state.selected_channel_map = dict(channel_map)

        if sensors_unique:
            state.selected_sensor = sensors_unique[0]
            state.current_topic = new_topics[sensors_unique[0]]
        else:
            state.selected_sensor = None
            state.current_topic = None

    client = state.mqtt_client
    if client is not None:
        for old_topic in old_topics.values():
            if old_topic and old_topic not in new_topics.values():
                try:
                    client.unsubscribe(old_topic)
                except Exception:
                    pass
        for _sensor_name, topic in new_topics.items():
            if topic and topic not in old_topics.values():
                try:
                    client.subscribe(topic)
                except Exception as e:
                    print('Error al subscribir a', topic, e)
