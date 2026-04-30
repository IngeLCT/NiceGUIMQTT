# Protocolo de comunicación - lado MQTT / NiceGUIMQTT

## 1. Propósito

Este documento describe la **nueva lógica objetivo** del lado **MQTT / NiceGUIMQTT** para sensores que usan protocolo binario fijo por `sensor_id`.

La idea es dejar documentado:
- qué topics usa la aplicación
- qué formato de trama espera por sensor
- qué comandos publica hacia los sensores
- qué validaciones hace antes de aceptar una trama
- qué estado mínimo guarda por sensor
- cómo obtiene rangos, unidades y offsets sin depender de metadata enviada por el sensor

Este documento debe tomarse como la referencia para adaptar el código de:
- `state.py`
- `sensor_config.py`
- `mqtt_handler.py`
- `pages/selector_page.py`
- `pages/dashboard_page.py`

---

## 2. Idea central del nuevo protocolo

La nueva arquitectura cambia la responsabilidad del protocolo así:

### Antes
- el sensor podía mandar heartbeat corto
- el sensor podía mandar metadata
- el sensor podía mandar mediciones con tiempo dentro del payload
- MQTT dependía de metadata para rango y UI

### Ahora
- **cada sensor tiene un `sensor_id` fijo**
- **cada sensor manda siempre el mismo tamaño de trama** según su tipo
- **MQTT ya conoce por `sensor_id`**:
  - nombre del sensor
  - tamaño esperado
  - offsets
  - tipos de datos
  - unidades
  - rangos min/max por variable
- el sensor **ya no manda metadata**
- el sensor **ya no manda tiempo** en la trama
- el tiempo de sesión lo controla **MQTT / dashboard**
- el sensor conserva tiempo interno solo para cálculos que necesite localmente

En resumen:
- el sensor publica datos fijos
- MQTT interpreta por tabla fija de configuración

---

## 3. Rol del lado MQTT

`NiceGUIMQTT` actúa como capa intermedia entre:
- los sensores físicos que publican por MQTT
- la interfaz de visualización y control

Su responsabilidad objetivo es:
- descubrir sensores activos
- permitir seleccionar un sensor
- suscribirse al topic de datos del sensor elegido
- decodificar tramas binarias por `sensor_id`
- enviar comandos (`SELECT`, `START`, `STOP`, `DESELECT`, `OK`)
- llevar el tiempo de sesión del dashboard
- almacenar el estado mínimo necesario para graficar y controlar la sesión
- usar configuración fija local para rangos, unidades y offsets

No debe depender de metadata del sensor para conocer la estructura de los datos.

---

## 4. Conexión MQTT

Configuración actual en `state.py`:

```text
MQTT_BROKER = 192.168.1.136
MQTT_PORT   = 1883
MQTT_USER   = eq1
```

### 4.1 Dos clientes MQTT lógicos

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
- recibir estados y mediciones
- publicar comandos hacia el sensor

---

## 5. Topics usados

### 5.1 Discovery

```text
EQ1/#
```

### 5.2 Datos del sensor

Formato general:

```text
EQ1/<sensor>/data
```

Ejemplos:

```text
EQ1/Lux1/data
EQ1/Movimiento1/data
```

### 5.3 Comandos al sensor

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

## 6. Discovery y detección de sensores

Cuando el cliente supervisor recibe un mensaje en un topic tipo:

```text
EQ1/<sensor>/data
```

registra:
- el nombre del sensor en `state.available_sensors`
- la hora de la última actividad en `state.sensor_last_seen`

### 6.1 Sensores considerados vivos

Un sensor se considera vivo si publicó dentro del tiempo:

```text
SENSOR_STALE_S = 5.0
```

Si deja de publicar por más de ese tiempo:
- desaparece de la lista visible en el selector

---

## 7. Selección de sensores en UI

Actualmente la UI trabaja en práctica con **selección única**.

### Flujo objetivo
1. el usuario abre la página `/`
2. se muestran sensores detectados
3. el usuario elige uno
4. `mqtt_handler.set_current_sensors([sensor])`
5. se navega a:

```text
/dashboard/<sensor>
```

---

## 8. Estado global mínimo que guarda MQTT

En `state.py` se debería conservar solo el estado mínimo necesario.

## 8.1 Discovery
- `available_sensors`
- `sensor_last_seen`

## 8.2 Estado de protocolo
- `sensor_protocol_state[sensor_name]`

Valores esperados:
- `heartbeat`
- `selected`
- `measuring`

## 8.3 Configuración fija del sensor
MQTT debe conocer por `sensor_id` y/o nombre del sensor:
- `sensor_id`
- `payload_format`
- `total_bytes`
- offsets de cada campo
- tipos (`uint16`, `int16`, etc.)
- escala
- unidades
- rango Y sugerido por métrica

Ejemplo conceptual:

```python
{
    'Movimiento1': {
        'sensor_id': 0x01,
        'total_bytes': 10,
        'state_offset': 3,
        'fields': {
            'distancia': {'offset': (4, 5), 'type': 'uint16', 'scale': 0.01, 'unit': 'm', 'y_range': [0, 5]},
            'velocidad': {'offset': (6, 7), 'type': 'int16', 'scale': 0.01, 'unit': 'm/s', 'y_range': [-6, 6]},
            'aceleracion': {'offset': (8, 9), 'type': 'int16', 'scale': 0.01, 'unit': 'm/s^2', 'y_range': [-11, 11]},
        },
    }
}
```

## 8.4 Selección actual
- `selected_sensor`
- `selected_sensors`
- `current_topic`
- `current_topics`

## 8.5 Buffers de visualización
- `buf_t_s`
- `buf_values`
- `last_values`
- `last_t_s`

## 8.6 Estado de medición
- `is_measuring`
- `measurement_start_ts`
- `measurement_elapsed_s`
- `measurement_sample_index`

En el nuevo diseño, el tiempo de la gráfica debe salir del lado MQTT y ya no del payload del sensor.

---

## 9. Formato de payload soportado

Para este protocolo, MQTT debe trabajar con una familia principal:

### 9.1 Binario con trama fija por `sensor_id`

Cada sensor define:
- su propio tamaño fijo
- su propio layout fijo
- su propio conjunto fijo de variables

MQTT debe interpretar la trama usando una tabla local ya conocida.

---

## 10. Validaciones binarias que MQTT debe hacer

Antes de interpretar una trama binaria, MQTT debe verificar:

1. que el payload sea `bytes`
2. que tenga al menos header
3. que `len(payload) == total_bytes`
4. que el ACK sea `0x06`
5. que el `sensor_id` coincida con el esperado por el sensor seleccionado
6. que el `total_bytes` coincida también con el tamaño esperado para ese `sensor_id`

Si alguna de esas validaciones falla, la trama se ignora.

Esta doble verificación es importante:
- validación contra lo que dice el payload
- validación contra lo que MQTT ya sabe del sensor

---

## 11. Estructura general de comandos MQTT -> sensor

Los comandos se generan con una trama binaria de 4 bytes:

```text
Byte 0 -> ACK         = 0x06
Byte 1 -> total_bytes = 0x04
Byte 2 -> sensor_id
Byte 3 -> command
```

### Comandos soportados

```text
SELECT   = 0x10
START    = 0x11
STOP     = 0x12
DESELECT = 0x13
OK       = 0x20
```

### Uso esperado
- `SELECT`: el dashboard toma el sensor
- `START`: comienza medición
- `STOP`: detiene medición
- `DESELECT`: libera el sensor al salir del dashboard
- `OK`: keepalive breve mientras el sensor esté en estado `selected`

---

## 12. Estado publicado por el sensor (`sensor_state`)

El byte 3 del payload publicado por el sensor queda reservado para `sensor_state`.

Valores definidos:

```text
0x00 = heartbeat / disponible / no seleccionado
0x11 = seleccionado / dashboard abierto / conectado
0x22 = midiendo
```

MQTT debe usar este valor como referencia principal para saber en qué estado operativo está el sensor.

---

## 13. Trama fija del MB1000

El sensor `Movimiento1` / MB1000 usa una trama fija de **10 bytes**.

## 13.1 Estructura

```text
Byte 0      -> ACK
Byte 1      -> total_bytes
Byte 2      -> sensor_id
Byte 3      -> sensor_state
Byte 4..5   -> distancia_m_x100
Byte 6..7   -> velocidad_m_s_x100
Byte 8..9   -> aceleracion_m_s2_x100
```

## 13.2 Tipos y endianess

```text
Byte(s)    Campo                    Tipo    Endian
0          ACK                      uint8   -
1          total_bytes              uint8   -
2          sensor_id                uint8   -
3          sensor_state             uint8   -
4..5       distancia_m_x100         uint16  little-endian
6..7       velocidad_m_s_x100       int16   little-endian
8..9       aceleracion_m_s2_x100    int16   little-endian
```

## 13.3 Escalas

```text
distancia_m      = distancia_m_x100 / 100.0
velocidad_m_s    = velocidad_m_s_x100 / 100.0
aceleracion_m_s2 = aceleracion_m_s2_x100 / 100.0
```

---

## 14. Cómo debe interpretar MQTT las tramas del MB1000

### 14.1 Estado `0x00` -> heartbeat

Cuando llega una trama con:

```text
sensor_state = 0x00
```

y los campos de datos en cero:
- marcar estado de protocolo como `heartbeat`
- no activar medición
- no agregar puntos a la gráfica
- mantenerlo como sensor disponible en selector

Ejemplo conceptual:

```text
06 0A 01 00 00 00 00 00 00 00
```

### 14.2 Estado `0x11` -> selected

Cuando llega una trama con:

```text
sensor_state = 0x11
```

y campos de datos en cero:
- marcar estado como `selected`
- considerar que el sensor está tomado por un dashboard
- no agregar puntos a buffers
- responder con `OK = 0x20` para mantener el estado

Ejemplo conceptual:

```text
06 0A 01 11 00 00 00 00 00 00
```

### 14.3 Estado `0x22` -> measuring

Cuando llega una trama con:

```text
sensor_state = 0x22
```
- marcar estado como `measuring`
- activar `state.is_measuring = True`
- decodificar distancia, velocidad y aceleración
- agregarlas a buffers si ese sensor es el seleccionado actual

Ejemplo conceptual:

```text
06 0A 01 22 <dist_l><dist_h> <vel_l><vel_h> <acc_l><acc_h>
```

---

## 15. Manejo del tiempo del lado MQTT

En este diseño, el sensor ya no manda tiempo en la trama.

Por lo tanto, MQTT / dashboard debe llevar el tiempo de sesión.

## 15.1 Regla general

Cuando el usuario presione `START`:
- guardar `measurement_start_ts`
- iniciar o reiniciar `measurement_sample_index`

Cuando llegue una medición:
- calcular tiempo relativo desde `measurement_start_ts`
- o usar índice de muestra si conviene más para la implementación

## 15.2 Motivación

Esto permite que la duración de la sesión quede controlada desde la UI, por ejemplo con un selector de duración, sin tener que mandar tiempo o duración detallada al sensor.

---

## 16. Keepalive del estado `selected`

Cuando el sensor está en `sensor_state = 0x11`, MQTT debe sostener ese estado mediante respuestas `OK`.

## 16.1 Lógica esperada del sensor

- el sensor publica su trama en estado `0x11` cada `15 s`
- espera recibir `OK`
- si no recibe `OK`, incrementa contador interno
- si el contador llega a `5`, vuelve a `0x00`
- si sí recibe `OK`, reinicia ese contador a `0`

## 16.2 Responsabilidad de MQTT

Cada vez que llegue una trama válida con `sensor_state = 0x11` del sensor actualmente tomado por el dashboard:
- MQTT debe publicar `OK = 0x20`

---

## 17. Flujo operativo objetivo en UI

## 17.1 Selector
En la página de selector:
- se muestran sensores vivos
- se muestra el estado actual visto (`heartbeat`, `selected`, `measuring`)
- el usuario elige un sensor
- se navega al dashboard

## 17.2 Al abrir dashboard
Al abrir el dashboard:
1. se fija el sensor actual
2. se asegura suscripción al topic `/data`
3. se publica `SELECT`

Esto indica al sensor que ese dashboard lo tomó.

## 17.3 Mientras el dashboard está abierto
Si el sensor responde/publica en estado `0x11`:
- MQTT debe responder `OK`
- el sensor permanece en estado `selected`

## 17.4 Al dar START
La UI publica `START`.

Desde ese punto:
- el dashboard considera iniciada la sesión
- empieza a llevar tiempo local
- espera mediciones con `sensor_state = 0x22`

## 17.5 Durante medición
La UI actualiza:
- gráfica
- etiquetas de valor
- estado de protocolo
- tabla en vivo

## 17.6 Al dar STOP
La UI publica `STOP`.

Después espera que el sensor vuelva a `sensor_state = 0x11`.

## 17.7 Al volver atrás
Al salir del dashboard:
- MQTT debe publicar `DESELECT`
- el sensor debe volver inmediatamente a `0x00`
- luego la UI vuelve al selector

---

## 18. Rango Y y unidades de la UI

La UI ya no debe depender de metadata del sensor para rangos o unidades.

En cambio, debe tomar esa información desde la configuración local del sensor.

### Ejemplo para MB1000

Desde configuración local:
- distancia: `0 .. 5 m`
- velocidad: `-6 .. 6 m/s`
- aceleración: `-11 .. 11 m/s^2`

La gráfica debe usar esos valores como rango inicial para cada métrica.

---

## 19. Qué debe guardar y qué no debe guardar MQTT

## Sí debe guardar
- último estado del sensor
- configuración fija del sensor
- buffers de tiempo y valores
- series guardadas por el usuario
- selección de métricas activas
- hora de inicio de medición

## Ya no necesita guardar por protocolo
- metadata recibida del sensor
- ACKs de metadata
- rangos dinámicos enviados por el sensor

---

## 20. Flujo completo resumido desde el lado MQTT

```text
1. Supervisor detecta sensor por EQ1/<sensor>/data
2. Usuario lo selecciona en UI
3. Dashboard publica SELECT
4. Sensor empieza a publicar con sensor_state = 0x11
5. MQTT responde OK para sostener la sesión
6. Usuario da START
7. Dashboard publica START
8. Sensor publica mediciones con sensor_state = 0x22
9. MQTT decodifica, convierte y grafica
10. Usuario da STOP
11. Dashboard publica STOP
12. Sensor vuelve a publicar con sensor_state = 0x11
13. Usuario sale del dashboard
14. Dashboard publica DESELECT
15. Sensor vuelve a sensor_state = 0x00
```

---

## 21. Ejemplo conceptual para MB1000

### Heartbeat

```text
Topic: EQ1/Movimiento1/data
Payload: 06 0A 01 00 00 00 00 00 00 00
```

Interpretación:
- sensor disponible
- no seleccionado
- no medir

### Selected

```text
Topic: EQ1/Movimiento1/data
Payload: 06 0A 01 11 00 00 00 00 00 00
```

Interpretación:
- sensor tomado por dashboard
- MQTT debe responder `OK`

### Medición

```text
Topic: EQ1/Movimiento1/data
Payload: 06 0A 01 22 ...datos...
```

Interpretación:
- sensor midiendo
- decodificar distancia/velocidad/aceleración
- agregar a buffers del dashboard

---

## 22. Estado de Lux y otros sensores

Esta misma filosofía debe extenderse a otros sensores:
- `Lux1`
- sensores futuros

Cada sensor puede tener:
- distinto `sensor_id`
- distinto tamaño fijo
- distinto layout fijo

Pero la lógica general debe mantenerse:
- `sensor_state` en byte 3
- sin metadata
- sin tiempo dentro del payload
- interpretación por tabla local del lado MQTT

---

## 23. Recomendación de diseño vigente

Para mantener MQTT liviano y fácil de mantener, este lado debería seguir siendo principalmente:
- receptor de tramas
- convertidor de datos
- emisor de comandos simples
- gestor de tiempo de sesión
- graficador

La estructura fija por `sensor_id` hace al sistema más simple, más predecible y más fácil de depurar.
