# Protocolo de comunicación - lado MQTT / NiceGUIMQTT

## 1. Propósito

Este documento describe cómo funciona actualmente el lado **MQTT / NiceGUIMQTT** frente a los sensores del proyecto, en especial frente a sensores que usan el protocolo binario por estados como:

- `Movimiento1` (MB1000)
- `Lux1` (VEML7700)

La idea es dejar claro:
- qué topics escucha la aplicación
- qué tipos de tramas sabe interpretar
- qué comandos publica hacia los sensores
- qué estado mínimo guarda por sensor
- cómo usa la metadata y las mediciones en la UI

Este documento describe el comportamiento implementado hoy en:
- `state.py`
- `sensor_config.py`
- `mqtt_handler.py`
- `pages/selector_page.py`
- `pages/dashboard_page.py`

---

## 2. Rol del lado MQTT

`NiceGUIMQTT` actúa como capa intermedia entre:
- los sensores físicos que publican por MQTT
- la interfaz de visualización y control

Su responsabilidad actual es:
- descubrir sensores activos
- permitir seleccionar un sensor
- suscribirse al topic de datos del sensor elegido
- decodificar tramas JSON o binarias
- enviar comandos (`SELECT`, `START`, `STOP`, `DESELECT`, `ACK_METADATA`)
- almacenar el estado mínimo necesario para graficar y controlar la sesión

No intenta hacer inteligencia compleja del sensor. Su función es principalmente:
- **recibir**
- **convertir**
- **almacenar lo necesario**
- **graficar**

---

## 3. Conexión MQTT

Configuración actual en `state.py`:

```text
MQTT_BROKER = 192.168.1.136
MQTT_PORT   = 1883
MQTT_USER   = eq1
```

### 3.1 Dos clientes MQTT lógicos

Actualmente se levantan dos clientes:

### Cliente supervisor
Se usa para **discovery**.

Se suscribe a:

```text
EQ1/#
```

Su objetivo es detectar sensores vivos al ver publicaciones en topics tipo:

```text
EQ1/<sensor>/data
```

### Cliente de medición
Se usa para:
- suscribirse al topic de datos del sensor seleccionado
- recibir metadata, ACKs y mediciones
- publicar comandos hacia el sensor

---

## 4. Topics usados

### 4.1 Discovery

```text
EQ1/#
```

### 4.2 Datos del sensor

Formato general:

```text
EQ1/<sensor>/data
```

Ejemplos:

```text
EQ1/Lux1/data
EQ1/Movimiento1/data
```

### 4.3 Comandos al sensor

Formato general:

```text
EQ1/<sensor>/cmd
```

Ejemplos:

```text
EQ1/Lux1/cmd
EQ1/Movimiento1/cmd
```

---

## 5. Discovery y detección de sensores

Cuando el cliente supervisor recibe un mensaje en un topic tipo:

```text
EQ1/<sensor>/data
```

registra:
- el nombre del sensor en `state.available_sensors`
- la hora de la última actividad en `state.sensor_last_seen`

### 5.1 Sensores considerados vivos

Un sensor se considera vivo si publicó dentro del tiempo:

```text
SENSOR_STALE_S = 5.0
```

Si deja de publicar por más de ese tiempo:
- desaparece de la lista visible en el selector

---

## 6. Selección de sensores en UI

Actualmente la UI trabaja en práctica con **selección única**.

### Flujo actual
1. el usuario abre la página `/`
2. se muestran sensores detectados
3. el usuario elige uno
4. `mqtt_handler.set_current_sensors([sensor])`
5. se navega a:

```text
/dashboard/<sensor>
```

Aunque el código interno soporta listas de sensores, la interfaz actual quedó simplificada para evitar mezcla ambigua de buffers.

---

## 7. Estado global mínimo que guarda MQTT

En `state.py` se conserva solo el estado mínimo necesario.

## 7.1 Discovery
- `available_sensors`
- `sensor_last_seen`

## 7.2 Estado de protocolo
- `sensor_protocol_state[sensor_name]`

Valores típicos:
- `heartbeat`
- `metadata`
- `measuring`

## 7.3 Metadata del sensor
- `sensor_metadata[sensor_name]`

Ejemplo para Lux:

```python
{
    'lux_min': 0.0,
    'lux_max': 36000.0,
    'updated_at': ...,
}
```

## 7.4 Selección actual
- `selected_sensor`
- `selected_sensors`
- `current_topic`
- `current_topics`

## 7.5 Buffers de visualización
- `buf_t_s`
- `buf_values`
- `last_values`
- `last_t_s`

## 7.6 Estado de medición
- `is_measuring`
- `measurement_sample_index`
- `measurement_elapsed_s`

No se guarda lógica compleja de autoscaling ni historial extra por sensor más allá de lo necesario para la vista actual y series guardadas.

---

## 8. Formatos de payload soportados

`NiceGUIMQTT` soporta dos familias de formato:

### 8.1 JSON
Para sensores más simples o antiguos.

### 8.2 Binario con estados
Usado por sensores como:
- MB1000
- VEML7700 (`Lux1`)

En `sensor_config.py`, el perfil `Lux` está definido como:

```text
payload_format = sensor_state_frame_v2
sensor_id = 0x02
binary_fields = [time_s, lux]
metadata_fields = [lux_min, lux_max]
```

---

## 9. Decodificación binaria en MQTT

Toda la lógica central está en `mqtt_handler.py`.

## 9.1 Validaciones generales
Antes de interpretar una trama binaria, MQTT verifica:
- que el payload sea `bytes`
- que tenga al menos header
- que `len(payload) == total_bytes`
- que el ACK sea `0x06`
- que el `sensor_id` coincida con el esperado por el perfil del sensor

Si alguna de esas validaciones falla, la trama se ignora.

---

## 10. Tipos de trama que MQTT reconoce

### 10.1 Heartbeat
Longitud:

```text
3 bytes
```

Cuando la recibe:
- marca el estado del sensor como `heartbeat`
- no actualiza buffers de datos

### 10.2 ACK corto
Longitud:

```text
4 bytes
```

MQTT interpreta el `ack_code` y actualiza el estado:

- `ACK_SELECT` -> `metadata`
- `ACK_START` -> `measuring`
- `ACK_STOP` -> `metadata`
- `ACK_DESELECT` -> `heartbeat`
- `ACK_METADATA_TIMEOUT` -> `heartbeat`

Además:
- `ACK_START` activa `state.is_measuring = True`
- `ACK_STOP`, `ACK_DESELECT`, `ACK_METADATA_TIMEOUT` ponen `state.is_measuring = False`

### 10.3 Metadata
Cuando llega metadata válida:
- actualiza `sensor_protocol_state[sensor] = metadata`
- guarda el rango en `state.sensor_metadata`
- publica automáticamente `ACK_METADATA` al sensor
- no agrega nada a buffers de gráfica

### 10.4 Medición
Cuando llega una medición válida:
- actualiza `sensor_protocol_state[sensor] = measuring`
- activa `state.is_measuring = True`
- convierte los campos binarios a valores físicos usando `scale`
- agrega los puntos a los buffers si la sesión está midiendo

---

## 11. Comandos que MQTT publica hacia el sensor

Los comandos se generan con una trama binaria de 4 bytes:

```text
Byte 0 -> ACK         = 0x06
Byte 1 -> total_bytes = 0x04
Byte 2 -> sensor_id
Byte 3 -> command
```

### Comandos soportados

```text
SELECT        = 0x10
START         = 0x11
STOP          = 0x12
DESELECT      = 0x13
ACK_METADATA  = 0x20
```

### Helpers actuales
En `mqtt_handler.py` existen:
- `publish_select_command(sensor_names)`
- `publish_measurement_command(sensor_names, start=True|False)`
- `publish_deselect_command(sensor_names)`
- `publish_sensor_command(sensor_names, command)`

---

## 12. Flujo operativo actual en UI

## 12.1 Selector
En la página de selector:
- se muestran sensores vivos
- se muestra el estado actual visto (`heartbeat`, `metadata`, `measuring`)
- el usuario elige un sensor
- se navega al dashboard

## 12.2 Al abrir dashboard
Actualmente el dashboard hace esto:
1. fija el sensor actual
2. asegura suscripción al topic `/data`
3. publica `SELECT`

Es decir, el `SELECT` sale automáticamente al abrir dashboard.

## 12.3 Al recibir metadata
MQTT:
- guarda `lux_min` y `lux_max`
- responde `ACK_METADATA`

La UI usa esos valores como rango Y cuando existen.

## 12.4 Al dar START
La UI publica `START`.

Después espera:
- `ACK_START`
- mediciones reales

## 12.5 Durante medición
La UI actualiza:
- gráfica
- etiquetas de valor
- estado de protocolo
- tabla en vivo

## 12.6 Al dar STOP
La UI publica `STOP`.

Después espera:
- `ACK_STOP`
- retorno a `metadata`

## 12.7 Al volver atrás
Al salir del dashboard:
- publica `DESELECT`
- vuelve al selector

---

## 13. Cómo usa la metadata la UI

La UI no calcula escalado complejo por su cuenta cuando existe metadata válida.

En `dashboard_page.py`, para cada métrica intenta obtener el rango desde `state.sensor_metadata`.

### Para Lux
Usa:

```text
lux_min
lux_max
```

Si la metadata existe:
- fija `yaxis.range = [lux_min, lux_max]`
- desactiva autorange en Y

Si no existe metadata:
- usa `autorange = True`

Esto hace que la gráfica dependa directamente del rango sugerido por el sensor.

---

## 14. Conversión de medición a valores graficables

Para `Lux1`, el perfil define:

```text
binary_field = lux
scale = 0.01
```

Por eso, cuando MQTT recibe `lux_x100` del sensor:
- primero lo interpreta como entero
- luego lo multiplica por `0.01`
- el valor final queda en lux reales

Lo mismo pasa con `time_s`:
- el sensor manda tiempo escalado x100
- MQTT lo convierte a segundos

---

## 15. Búferes y ventana en vivo

Configuración actual:

```text
SAMPLE_HZ = 4
WINDOW_S = 60
REFRESH_S = 0.25
```

Interpretación:
- la UI considera una ventana viva de hasta 60 s
- los buffers se dimensionan según eso
- la actualización visual ocurre periódicamente

### Nota
El tiempo real que entra al buffer, cuando la trama binaria lo trae explícito, sale del payload del sensor, no del reloj local del dashboard.

---

## 16. Qué guarda y qué no guarda MQTT

## Sí guarda
- último estado del sensor
- última metadata recibida
- buffers de tiempo y valores
- series guardadas por el usuario
- selección de métricas activas

## No guarda como lógica pesada
- autoscaling inteligente por sensor
- percentiles
- histogramas
- máximos históricos complejos
- lógica de escalones del sensor

La idea del diseño actual es que MQTT sea relativamente simple y que el sensor pueda encargarse de la inteligencia específica de su rango cuando eso se implemente.

---

## 17. Comportamientos importantes actuales

### 17.1 ACK automático de metadata
Cuando llega una metadata válida, MQTT responde automáticamente:

```text
ACK_METADATA = 0x20
```

Eso evita que la UI tenga que hacerlo manualmente.

### 17.2 Solo se procesan datos del sensor seleccionado
Aunque el supervisor detecta todo `EQ1/#`, el cliente de medición solo usa de verdad los sensores actualmente seleccionados.

### 17.3 Rango Y guiado por metadata
Si hay metadata, la UI prefiere ese rango.

### 17.4 Selección única efectiva
Aunque internamente hay estructuras para varios sensores, la UI actual quedó restringida a selección práctica de un solo sensor a la vez para evitar mezclas ambiguas.

---

## 18. Flujo completo resumido desde el lado MQTT

```text
1. Supervisor detecta sensor por EQ1/<sensor>/data
2. Usuario lo selecciona en UI
3. Dashboard publica SELECT
4. Sensor responde ACK_SELECT
5. Sensor manda metadata
6. MQTT guarda metadata y responde ACK_METADATA
7. Usuario da START
8. Dashboard publica START
9. Sensor responde ACK_START
10. Sensor publica mediciones
11. MQTT decodifica, convierte y grafica
12. Usuario da STOP o el sensor termina
13. Sensor vuelve a metadata
14. Usuario sale y dashboard publica DESELECT
```

---

## 19. Ejemplo conceptual para Lux1

### Metadata recibida

```text
Topic: EQ1/Lux1/data
Payload binario: metadata
```

MQTT la convierte a algo como:

```python
state.sensor_metadata['Lux1'] = {
    'lux_min': 0.0,
    'lux_max': 36000.0,
    'updated_at': 1714420000.0,
}
```

### Medición recibida

Si llega una medición con:

```text
lux_x100 = 123456
```

MQTT la interpreta como:

```text
lux = 1234.56
```

Y la agrega al buffer de la métrica:

```text
Lux1:Lux
```

---

## 20. Limitaciones actuales

Este documento describe el estado actual implementado.

Aún no está integrado del lado MQTT:
- metadata dinámica durante `START`
- ajuste incremental de eje Y durante una sesión por nuevas metadata del sensor
- flags de `low_signal`, `high_signal`, `saturated`
- lógica especial para expansión sin contracción durante la sesión

Si esas mejoras se agregan después, este documento deberá actualizarse.

---

## 21. Recomendación de diseño vigente

Para mantener MQTT liviano y fácil de portar a otras interfaces en el futuro, este lado debería seguir siendo principalmente:
- receptor de tramas
- convertidor de datos
- emisor de comandos simples
- graficador

La lógica más específica del sensor, por ejemplo autosugerencia de rango visual, conviene mantenerla en el propio sensor siempre que sea posible.
