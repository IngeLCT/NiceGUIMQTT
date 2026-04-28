"""
Página de NiceGUI para seleccionar un sensor.

Esta página enumera todos los sensores detectados y permite al usuario
seleccionar un solo sensor. Al seleccionar un sensor, la aplicación
accede a la página del panel. La lista de sensores disponibles se actualiza
periódicamente leyendo el conjunto ``available_sensors`` de ``state``.

Para registrar la página con NiceGUI, simplemente importe este módulo en su
script principal. La ruta se define mediante el decorador ``@ui.page``.
"""

from __future__ import annotations

import time

from nicegui import ui

import mqtt_handler
import state


@ui.page('/')
def page_index() -> None:
    """Sensor selection page."""
    ui.dark_mode().enable()
    ui.label(f'Selector de Sensor {state.EQ_PREFIX}/').classes('text-2xl font-bold')
    ui.label(
        f'Se detectan automáticamente los sensores de {state.EQ_PREFIX}/; puedes seleccionar y abrir el dashboard.'
    ).classes('text-sm').style('color: #f2f2f2')

    # NOTE (NiceGUI 3.5.0):
    # ``ui.select(multiple=True)`` puede lanzar el error
    # "list indices must be integers or slices, not str" en algunos entornos
    # (proviene del manejo interno de eventos del select).
    # Para hacerlo 100% estable, usamos una lista de checkboxes,
    # pero con selección exclusiva de un solo sensor.
    selected_sensor: str | None = None

    with ui.row().classes('w-full items-center gap-4'):
        ui.label('Sensores').classes('text-sm')
        status = ui.label('Buscando sensores...').classes('text-sm')
        proto_status = ui.label('').classes('text-xs')

    @ui.refreshable
    def sensor_checklist() -> None:
        nonlocal selected_sensor
        now = time.time()
        with state.sensor_lock:
            alive: list[str] = []
            # limpiar sensores que ya no publican
            for s in list(state.available_sensors):
                last = state.sensor_last_seen.get(s, 0.0)
                if now - last <= state.SENSOR_STALE_S:
                    alive.append(s)
                else:
                    state.available_sensors.discard(s)
                    state.sensor_last_seen.pop(s, None)
                    if selected_sensor == s:
                        selected_sensor = None
            opts = sorted(alive)

        if not opts:
            status.text = ('No se detectaron sensores, Buscando sensores...')
            proto_status.text = ''
            return

        status.text = f'Sensores detectados: {len(opts)}'
        with ui.card().classes('w-full max-w-2xl'):
            with ui.column().classes('max-h-72 overflow-auto gap-1'):
                for s in opts:
                    def _on_change(e, name=s) -> None:
                        nonlocal selected_sensor
                        if e.value:
                            selected_sensor = name
                        elif selected_sensor == name:
                            selected_sensor = None
                        sensor_checklist.refresh()

                    with ui.row().classes('items-center gap-3'):
                        ui.checkbox(s, value=(s == selected_sensor), on_change=_on_change)
                        with state.data_lock:
                            pstate = state.sensor_protocol_state.get(s, 'heartbeat')
                        ui.label(f'estado: {pstate}').classes('text-xs text-gray-400')

        proto_status.text = 'Seleccionado: ' + (selected_sensor if selected_sensor in opts else '--')

    sensor_checklist()
    ui.timer(0.5, sensor_checklist.refresh)

    def clear_selection() -> None:
        nonlocal selected_sensor
        selected_sensor = None
        sensor_checklist.refresh()

    with ui.row().classes('gap-2'):
        ui.button('Limpiar', on_click=clear_selection).style('background-color:#737373 !important; color:#ffffff !important')

    def open_dashboard() -> None:
        if not selected_sensor:
            ui.notify('Selecciona un sensor', type='negative')
            return
        mqtt_handler.set_current_sensors([selected_sensor])
        ui.navigate.to(f'/dashboard/{selected_sensor}')

    ui.button('Abrir dashboard', on_click=open_dashboard).props('color=primary')