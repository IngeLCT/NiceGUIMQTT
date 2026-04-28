# NiceGUIMQTT

Panel NiceGUI para descubrimiento, selección, visualización y control de sensores vía MQTT.

## Estado actual del proyecto

Este proyecto ya tiene una base funcional para:

- descubrir sensores por MQTT
- seleccionar uno o varios sensores
- suscribirse a sus topics de datos
- mostrar gráficas en vivo con NiceGUI + Plotly
- enviar comandos simples de medición (`START` / `STOP`)
- guardar series y exportarlas a CSV

Actualmente el proyecto mezcla dos modelos de datos:

1. **sensores JSON**
2. **sensores binarios con `sensor_id_frame_v1`**

El soporte binario actual está pensado principalmente para el **MB1000 anterior**, antes del nuevo protocolo con estados, metadata y `frame_type`.

---

## Estructura del proyecto

```text
NiceGUIMQTT/
├── main.py
├── mqtt_handler.py
├── sensor_config.py
├── state.py
├── pages/
│   ├── selector_page.py
│   └── dashboard_page.py
├── requirements.txt
└── .gitignore
```

---

## Descripción de archivos

### `main.py`
Punto de entrada de la aplicación.

Responsabilidades:
- importa páginas NiceGUI
- arranca el cliente MQTT de supervisión
- arranca el cliente MQTT de medición
- ejecuta la app web

### `mqtt_handler.py`
Es el núcleo MQTT del sistema.

Responsabilidades actuales:
- conexión MQTT de discovery/supervisión
- conexión MQTT de medición
- suscripciones dinámicas a topics de sensores
- decodificación de payload JSON o binario
- publicación de comandos `START` / `STOP`
- almacenamiento de datos en `state.py`

### `sensor_config.py`
Configura perfiles por tipo de sensor.

Responsabilidades:
- mapear un nombre de sensor a un tipo lógico (`Movimiento`, `Lux`, `Gyro`, etc.)
- definir métricas, unidades, colores, labels y defaults de UI
- declarar si el payload es JSON o binario
- definir `sensor_id` esperado si el sensor es binario

### `state.py`
Contiene el estado global compartido de la app.

Responsabilidades:
- configuración MQTT y UI
- sensores disponibles detectados
- sensores seleccionados
- topics activos
- buffers de tiempo y valores
- series guardadas
- control de medición en vivo

### `pages/selector_page.py`
Pantalla principal para detectar y seleccionar sensores.

Responsabilidades:
- mostrar sensores vivos descubiertos por MQTT
- permitir seleccionar varios sensores
- abrir dashboard con los sensores elegidos

### `pages/dashboard_page.py`
Dashboard principal de visualización.

Responsabilidades:
- construir gráficas Plotly por canal/métrica
- enviar `START` / `STOP`
- guardar series
- exportar CSV
- permitir activar/desactivar canales

---

## Flujo actual del proyecto

## 1. Discovery

El cliente supervisor se suscribe a:

```text
EQ1/#
```

Y considera sensores detectados cuando recibe publicaciones en topics tipo:

```text
EQ1/<sensor>/data
```

Esto alimenta:
- `state.available_sensors`
- `state.sensor_last_seen`

## 2. Selección de sensores

En `selector_page.py` el usuario marca sensores detectados.

Luego:
- se llama `mqtt_handler.set_current_sensors(...)`
- se suscribe a los topics `/data` de cada sensor seleccionado
- se prepara el dashboard

## 3. Dashboard

El dashboard:
- construye gráficas a partir de `sensor_config.py`
- recibe muestras nuevas desde `mqtt_handler.py`
- actualiza buffers y gráficas periódicamente

## 4. Control de medición

Actualmente la UI envía únicamente:
- `START`
- `STOP`

Usando `mqtt_handler.publish_measurement_command(...)`

---

## Formatos de datos soportados actualmente

## A. JSON

Para sensores como `Lux`, `Gyro`, `TeHu`, etc.

El parser actual espera JSON y busca claves según el perfil del sensor.

Ejemplo conceptual:

```json
{
  "t_ms": 1000,
  "temp": 24.5,
  "hume": 55.0
}
```

## B. Binario `sensor_id_frame_v1`

Soporte actual orientado al MB1000 anterior.

### Header actual esperado

```text
Byte 0 -> ACK
Byte 1 -> total_bytes
Byte 2 -> sensor_id
```

### Heartbeat actual soportado

```text
06 03 01
```

### Medición MB1000 actualmente soportada por MQTT

Longitud esperada hoy en el código:

```text
13 bytes
```

Estructura esperada hoy por `_decode_mb1000_payload()`:

```text
Byte 0      ACK
Byte 1      total_bytes
Byte 2      sensor_id
Byte 3..6   tiempo_s_x100
Byte 7..8   distancia_m_x100
Byte 9..10  velocidad_m_s_x100
Byte 11..12 aceleracion_m_s2_x100
```

Decodificación actual:

```python
struct.unpack_from('<IHhh', payload, 3)
```

---

## Nuevo protocolo MB1000 que ahora debe soportarse

El MB1000 ya cambió en el proyecto **Sensores**.

Nuevo modelo acordado:

### Estados del sensor
1. `HEARTBEAT`
2. `METADATA + espera de START`
3. `MEASURING`

### Comandos MQTT -> ESP

```text
0x10 = SELECT
0x11 = START
0x12 = STOP
0x13 = DESELECT
0x20 = ACK_METADATA
```

### ACKs ESP -> MQTT

```text
0x90 = ACK_SELECT
0x91 = ACK_START
0x92 = ACK_STOP
0x93 = ACK_DESELECT
0x95 = ACK_METADATA_TIMEOUT
```

### Tramas de datos nuevas

#### Heartbeat
```text
3 bytes
```

#### Metadata
```text
17 bytes
```

#### Medición nueva
```text
14 bytes
```

La medición nueva incluye `frame_type`:

```text
Byte 3 -> frame_type = 0x31
```

Y la metadata usa `frame_type = 0x30`.

---

## Qué entiende hoy MQTT y qué NO entiende todavía

## Ya entiende hoy
- descubrimiento básico por topic `/data`
- heartbeat de 3 bytes
- medición binaria antigua MB1000 de 13 bytes
- sensores JSON
- múltiples sensores seleccionados
- múltiples canales por sensor

## No entiende todavía
- `SELECT`
- `DESELECT`
- `ACK_METADATA`
- ACKs cortos de transición (`ACK_SELECT`, `ACK_START`, etc.)
- metadata de visualización de 17 bytes
- medición nueva del MB1000 con `frame_type` y longitud 14 bytes
- rangos sugeridos de visualización enviados por el sensor
- lógica de “sensor armado/seleccionado” previa a `START`

---

## Cambios necesarios para adaptar MQTT al nuevo protocolo

## 1. `mqtt_handler.py`
Es el archivo que más debe cambiar.

### Cambios necesarios

#### a) Nuevas constantes de protocolo
Agregar soporte para:
- `SELECT`
- `START`
- `STOP`
- `DESELECT`
- `ACK_METADATA`
- `ACK_SELECT`
- `ACK_START`
- `ACK_STOP`
- `ACK_DESELECT`
- `ACK_METADATA_TIMEOUT`
- `FRAME_TYPE_METADATA = 0x30`
- `FRAME_TYPE_MEASUREMENT = 0x31`

#### b) Nuevo tamaño de tramas
Hoy el código tiene:

```python
MB1000_FRAME_SIZE = 13
```

Esto debe cambiar porque ahora hay:
- heartbeat: `3`
- ACK corto: `4`
- metadata: `17`
- medición: `14`

#### c) Nuevo decodificador MB1000
Hoy `_decode_mb1000_payload()` espera la trama antigua.

Debe separarse en algo como:
- `_decode_short_ack_frame(...)`
- `_decode_metadata_frame(...)`
- `_decode_mb1000_measurement_frame(...)`

#### d) `_decode_sensor_frame(...)`
Hoy solo distingue:
- heartbeat
- medición

Debe poder distinguir al menos:
- heartbeat
- ack corto
- metadata
- medición

#### e) Publicación de comandos
Hoy `publish_measurement_command()` solo envía:
- `START`
- `STOP`

Debe evolucionar a algo más general, por ejemplo:
- publicar `SELECT`
- publicar `DESELECT`
- publicar `START`
- publicar `STOP`
- publicar `ACK_METADATA`

#### f) Respuesta a metadata
Cuando MQTT reciba una trama metadata válida del MB1000, debe responder con:

```text
ACK_METADATA = 0x20
```

Eso hoy no existe.

---

## 2. `sensor_config.py`
El perfil del sensor de movimiento debe actualizarse al nuevo formato real.

### Qué revisar
- `payload_format`
- campos binarios disponibles
- posible soporte de metadata
- defaults visuales por canal

Hoy el tipo `Movimiento` sigue apuntando implícitamente al formato binario viejo.

Además, aquí es un buen lugar para definir valores por defecto de UI como:
- si un canal debe iniciar visible
- labels y unidades
- quizá valores por defecto de ejes cuando aún no llegó metadata

---

## 3. `pages/selector_page.py`
Hoy solo selecciona sensores desde discovery y abre dashboard.

### Qué podría necesitar
Con el nuevo protocolo, la selección del sensor ya no es solo local en UI:
- ahora debe existir un `SELECT` real al ESP
- y luego posiblemente un `DESELECT`

Eso significa que esta página probablemente deba coordinar:
- qué sensor quedó “armado” del lado del ESP
- cuándo liberar ese estado si el usuario vuelve atrás

---

## 4. `pages/dashboard_page.py`
Aquí hay impacto importante.

### Cambios necesarios

#### a) Al abrir dashboard
Probablemente debe enviarse `SELECT` al sensor o sensores elegidos.

#### b) Al salir del dashboard
Probablemente debe enviarse `DESELECT`.

#### c) Al recibir metadata
La UI debe usarla para ajustar rangos de gráficas:
- distancia
- velocidad
- aceleración

Hoy las gráficas están con `autorange=True`.

Con el nuevo protocolo, conviene poder usar los rangos sugeridos del sensor como rango inicial o fijo.

#### d) Confirmación de metadata
La UI/backend debe confirmar recepción de metadata con `ACK_METADATA`.

---

## 5. `state.py`
Hoy no hay estructuras para almacenar metadata de visualización ni estado de protocolo por sensor.

### Faltaría agregar algo como
- metadata por sensor
- estado actual del sensor (`heartbeat`, `metadata`, `measuring`)
- timestamp de última metadata
- flags de sensor seleccionado/armado

Por ejemplo, algo como:

```python
sensor_metadata = {
    'Movimiento1': {
        'distance_min_m': ...,
        'distance_max_m': ...,
        'velocity_min_m_s': ...,
        'velocity_max_m_s': ...,
        'acceleration_min_m_s2': ...,
        'acceleration_max_m_s2': ...,
    }
}
```

---

## Diagnóstico del estado actual

## Lo bueno
- la base de NiceGUI ya está modular y ordenada
- el flujo de múltiples sensores ya existe
- el sistema de métricas por perfil ya está bastante flexible
- el decode binario ya existe como punto de partida

## Lo frágil / desactualizado frente al nuevo protocolo
- `mqtt_handler.py` todavía está acoplado al MB1000 viejo
- no existe manejo de metadata
- no existe ACK de metadata
- no existe noción de `SELECT` / `DESELECT`
- las gráficas no usan rangos sugeridos desde el sensor
- el tamaño y estructura de la medición binaria cambió

---

## Prioridad recomendada de cambios

## Fase 1
Actualizar `mqtt_handler.py` para:
- decodificar heartbeat / ack corto / metadata / medición nueva
- publicar `ACK_METADATA`
- soportar `SELECT`, `DESELECT`, `START`, `STOP`

## Fase 2
Actualizar `state.py` para guardar metadata y estado por sensor.

## Fase 3
Actualizar `dashboard_page.py` para:
- usar metadata en rangos de gráficas
- enviar `SELECT` al entrar
- enviar `DESELECT` al salir o cambiar de pantalla

## Fase 4
Ajustar `sensor_config.py` para reflejar el protocolo final y dejar perfiles coherentes.

---

## Resumen corto

Hoy el proyecto MQTT/NiceGUI:
- **sí sirve** para discovery y visualización básica
- **sí soporta** sensores JSON y MB1000 binario viejo
- **todavía no soporta** el nuevo protocolo del MB1000 con estados, metadata y `frame_type`

El archivo más importante a modificar es:

```text
mqtt_handler.py
```

porque ahí se concentra:
- parsing
- publicación de comandos
- reconocimiento de tramas
- integración entre sensor y UI

---

## Archivo clave para el siguiente paso

Cuando se empiece la adaptación real, los archivos más probables a editar serán:

- `mqtt_handler.py`
- `sensor_config.py`
- `state.py`
- `pages/dashboard_page.py`
- quizá `pages/selector_page.py`
