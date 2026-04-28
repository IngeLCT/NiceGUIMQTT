from __future__ import annotations

import json
import struct
import time
from typing import Any, Optional

import paho.mqtt.client as mqtt

import sensor_config
import state

MB1000_SENSOR_ID = 0x01
SENSOR_FRAME_ACK = 0x06
SENSOR_FRAME_HEADER_SIZE = 3
SENSOR_HEARTBEAT_FRAME_SIZE = 3
SENSOR_SHORT_ACK_FRAME_SIZE = 4
MB1000_METADATA_FRAME_SIZE = 17
MB1000_MEASUREMENT_FRAME_SIZE = 14
SENSOR_COMMAND_FRAME_SIZE = 4

SENSOR_COMMAND_SELECT = 0x10
SENSOR_COMMAND_START = 0x11
SENSOR_COMMAND_STOP = 0x12
SENSOR_COMMAND_DESELECT = 0x13
SENSOR_COMMAND_ACK_METADATA = 0x20

ACK_SELECT = 0x90
ACK_START = 0x91
ACK_STOP = 0x92
ACK_DESELECT = 0x93
ACK_METADATA_TIMEOUT = 0x95

FRAME_TYPE_METADATA = 0x30
FRAME_TYPE_MEASUREMENT = 0x31


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


def _decode_mb1000_metadata_payload(payload: bytes) -> tuple[dict[str, int], None]:
    if len(payload) != MB1000_METADATA_FRAME_SIZE:
        raise ValueError(f'Metadata MB1000 requiere {MB1000_METADATA_FRAME_SIZE} bytes, recibidos {len(payload)}')

    frame_type, dmin, dmax, vmin, vmax, amin, amax, expected_ack = struct.unpack_from('<BhhhhhhB', payload, SENSOR_FRAME_HEADER_SIZE)
    if frame_type != FRAME_TYPE_METADATA:
        raise ValueError(f'frame_type metadata invalido: 0x{frame_type:02X}')

    raw_data = {
        'frame_type': frame_type,
        'distance_min_m': dmin,
        'distance_max_m': dmax,
        'velocity_min_m_s': vmin,
        'velocity_max_m_s': vmax,
        'acceleration_min_m_s2': amin,
        'acceleration_max_m_s2': amax,
        'expected_ack': expected_ack,
    }
    return raw_data, None


def _decode_mb1000_measurement_payload(payload: bytes) -> tuple[dict[str, int], float]:
    if len(payload) != MB1000_MEASUREMENT_FRAME_SIZE:
        raise ValueError(f'Medicion MB1000 requiere {MB1000_MEASUREMENT_FRAME_SIZE} bytes, recibidos {len(payload)}')

    frame_type, t_s_x100, d_m_x100, v_ms_x100, a_ms2_x100 = struct.unpack_from('<BIHhh', payload, SENSOR_FRAME_HEADER_SIZE)
    if frame_type != FRAME_TYPE_MEASUREMENT:
        raise ValueError(f'frame_type medicion invalido: 0x{frame_type:02X}')

    raw_data = {
        'frame_type': frame_type,
        'time_s': t_s_x100,
        'distance_m': d_m_x100,
        'velocity_m_s': v_ms_x100,
        'acceleration_m_s2': a_ms2_x100,
    }
    return raw_data, t_s_x100 / 100.0


def _decode_short_ack_payload(payload: bytes) -> tuple[dict[str, int], None]:
    if len(payload) != SENSOR_SHORT_ACK_FRAME_SIZE:
        raise ValueError(f'ACK corto requiere {SENSOR_SHORT_ACK_FRAME_SIZE} bytes, recibidos {len(payload)}')
    ack_code = payload[SENSOR_FRAME_HEADER_SIZE]
    return {'ack_code': ack_code}, None


def _decode_sensor_frame(payload: Any, sensor_name: str) -> tuple[str, int, dict[str, int], float | None] | None:
    if not isinstance(payload, bytes):
        print(f'[MEAS] Payload binario invalido para {sensor_name}: tipo {type(payload).__name__}, esperado bytes')
        return None

    if len(payload) < SENSOR_FRAME_HEADER_SIZE:
        print(f'[MEAS] Payload binario incompleto para {sensor_name}: {len(payload)} bytes, falta header de {SENSOR_FRAME_HEADER_SIZE}')
        return None

    ack, total_bytes, sensor_id = struct.unpack_from('<BBB', payload, 0)

    if len(payload) != total_bytes:
        status = 'incompleto' if len(payload) < total_bytes else 'con bytes extra'
        print(f'[MEAS] Payload binario {status} para {sensor_name}: {len(payload)} bytes (total_bytes={total_bytes}, sensor_id=0x{sensor_id:02X})')
        return None

    if ack != SENSOR_FRAME_ACK:
        print(f'[MEAS] ACK invalido para {sensor_name}: 0x{ack:02X} (esperado 0x{SENSOR_FRAME_ACK:02X})')
        return None

    try:
        if total_bytes == SENSOR_HEARTBEAT_FRAME_SIZE:
            return 'heartbeat', sensor_id, {}, None
        if total_bytes == SENSOR_SHORT_ACK_FRAME_SIZE:
            raw_data, payload_t_s = _decode_short_ack_payload(payload)
            return 'short_ack', sensor_id, raw_data, payload_t_s
        if total_bytes == MB1000_METADATA_FRAME_SIZE:
            raw_data, payload_t_s = _decode_mb1000_metadata_payload(payload)
            return 'metadata', sensor_id, raw_data, payload_t_s
        if total_bytes == MB1000_MEASUREMENT_FRAME_SIZE:
            raw_data, payload_t_s = _decode_mb1000_measurement_payload(payload)
            return 'measurement', sensor_id, raw_data, payload_t_s
    except Exception as e:
        print(f'[MEAS] Error al decodificar frame de {sensor_name}:', e)
        return None

    print(f'[MEAS] Longitud de trama no soportada para {sensor_name}: total_bytes={total_bytes}')
    return None


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


def _store_sensor_metadata(sensor_name: str, raw_data: dict[str, int]) -> None:
    metadata = {
        'distance_min_m': raw_data['distance_min_m'] / 100.0,
        'distance_max_m': raw_data['distance_max_m'] / 100.0,
        'velocity_min_m_s': raw_data['velocity_min_m_s'] / 100.0,
        'velocity_max_m_s': raw_data['velocity_max_m_s'] / 100.0,
        'acceleration_min_m_s2': raw_data['acceleration_min_m_s2'] / 100.0,
        'acceleration_max_m_s2': raw_data['acceleration_max_m_s2'] / 100.0,
        'updated_at': time.time(),
    }
    with state.data_lock:
        state.sensor_metadata[sensor_name] = metadata


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
    payload_format = str(profile.get('payload_format', 'json'))
    metrics = profile.get('metrics', [])
    raw_data: dict[str, Optional[float | int]] = {}
    payload_t_s: Optional[float] = None
    avg: Optional[int] = None
    frame_kind: Optional[str] = None

    if payload_format in {'sensor_id_frame_v1', 'mb1000_bin_v1', 'sensor_state_frame_v2'}:
        decoded = _decode_sensor_frame(msg.payload, sensor_name)
        if decoded is None:
            return
        frame_kind, sensor_id, raw_data, payload_t_s = decoded
        expected_sensor_id = profile.get('sensor_id')
        if expected_sensor_id is not None:
            expected_sensor_id_int = _to_int(expected_sensor_id)
            if expected_sensor_id_int is None:
                print(f'[MEAS] sensor_id invalido en perfil de {sensor_name}: {expected_sensor_id}')
                return
            if expected_sensor_id_int != sensor_id:
                print(f'[MEAS] sensor_id no coincide para {sensor_name}: 0x{sensor_id:02X} (perfil espera 0x{expected_sensor_id_int:02X})')
                return

        if frame_kind == 'heartbeat':
            _store_protocol_state(sensor_name, 'heartbeat')
            return

        if frame_kind == 'short_ack':
            ack_code = raw_data.get('ack_code')
            if ack_code == ACK_SELECT:
                _store_protocol_state(sensor_name, 'metadata')
            elif ack_code == ACK_START:
                _store_protocol_state(sensor_name, 'measuring')
                with state.data_lock:
                    state.is_measuring = True
            elif ack_code == ACK_STOP:
                _store_protocol_state(sensor_name, 'metadata')
                with state.data_lock:
                    state.is_measuring = False
            elif ack_code == ACK_DESELECT:
                _store_protocol_state(sensor_name, 'heartbeat')
                with state.data_lock:
                    state.is_measuring = False
            elif ack_code == ACK_METADATA_TIMEOUT:
                _store_protocol_state(sensor_name, 'heartbeat')
                with state.data_lock:
                    state.is_measuring = False
            return

        if frame_kind == 'metadata':
            _store_protocol_state(sensor_name, 'metadata')
            _store_sensor_metadata(sensor_name, raw_data)
            publish_sensor_command([sensor_name], SENSOR_COMMAND_ACK_METADATA)
            return

        if frame_kind == 'measurement':
            _store_protocol_state(sensor_name, 'measuring')
            with state.data_lock:
                state.is_measuring = True
    else:
        try:
            payload = msg.payload.decode('utf-8', errors='ignore')
            j = json.loads(payload)
        except Exception as e:
            print('Error al decodificar JSON:', e)
            return

        t_ms = _to_int(j.get('t_ms'))
        if t_ms is None:
            return

        required = profile.get('required_keys', ['t_ms'])
        for rk in required:
            if rk == 't_ms':
                continue
            if rk not in j:
                return

        avg_key = profile.get('avg_dropped_key')
        avg = _to_int(j.get(avg_key)) if avg_key else None
        raw_data = j

    values: dict[str, Optional[float]] = {}
    for m in metrics:
        mid = m['id']
        if selected_channels is not None and mid not in selected_channels:
            continue
        field_name = m.get('binary_field') if payload_format in {'sensor_id_frame_v1', 'mb1000_bin_v1', 'sensor_state_frame_v2'} else m.get('json_key')
        raw = raw_data.get(field_name)
        val = _to_float(raw)
        if val is not None:
            try:
                val = val * float(m.get('scale', 1.0))
            except Exception:
                pass
        values[mid] = val

    prefixed_values: dict[str, Optional[float]] = {f'{sensor_name}:{mid}': v for mid, v in values.items()}

    with state.data_lock:
        state.last_avg_dropped = avg
        for pref_mid, val in prefixed_values.items():
            state.last_values[pref_mid] = val

        if state.is_measuring:
            if payload_t_s is not None:
                t_rel_s = payload_t_s
            else:
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
        for sensor_name, topic in new_topics.items():
            if topic and topic not in old_topics.values():
                try:
                    client.subscribe(topic)
                except Exception as e:
                    print('Error al subscribir a', topic, e)
