"""
Página de NiceGUI para seleccionar un sensor.

Esta página enumera los sensores detectados bajo demanda. El usuario pulsa
"Buscar sensores" y la aplicación observa durante algunos segundos qué
sensores siguen publicando; al terminar, actualiza la lista encontrada.
Después, al seleccionar un sensor, la aplicación espera la confirmación de
conexión del protocolo antes de abrir el dashboard.

Para registrar la página con NiceGUI, simplemente importe este módulo en su
script principal. La ruta se define mediante el decorador ``@ui.page``.
"""

from __future__ import annotations

import asyncio
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
        'Pulsa "Buscar sensores" para escanear durante unos segundos y luego selecciona uno para conectar.'
    ).classes('text-sm').style('color: #f2f2f2')

    selected_sensor: str | None = None
    discovered_sensors: list[str] = []
    search_in_progress = False
    SEARCH_WINDOW_S = 5.0
    SEARCH_POLL_S = 0.25

    with ui.row().classes('w-full items-center gap-4'):
        ui.label('Sensores').classes('text-sm')
        status = ui.label('Pulsa "Buscar sensores" para iniciar un escaneo.').classes('text-sm')
        proto_status = ui.label('Seleccionado: --').classes('text-xs')

    @ui.refreshable
    def sensor_checklist() -> None:
        nonlocal selected_sensor

        if not discovered_sensors:
            with ui.card().classes('w-full max-w-2xl'):
                ui.label('No hay sensores en la lista.').classes('text-sm text-gray-400')
                ui.label('Usa el botón "Buscar sensores" para hacer un escaneo manual.').classes('text-xs text-gray-500')
            proto_status.text = 'Seleccionado: --'
            return

        with ui.card().classes('w-full max-w-2xl'):
            with ui.column().classes('max-h-72 overflow-auto gap-1'):
                for s in discovered_sensors:
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

        proto_status.text = 'Seleccionado: ' + (selected_sensor if selected_sensor in discovered_sensors else '--')

    sensor_checklist()

    def clear_selection() -> None:
        nonlocal selected_sensor
        selected_sensor = None
        sensor_checklist.refresh()

    async def search_sensors() -> None:
        nonlocal selected_sensor, discovered_sensors, search_in_progress

        if search_in_progress:
            return

        search_in_progress = True
        selected_sensor = None
        discovered: set[str] = set()
        status.text = 'Buscando sensores durante 5 s...'
        proto_status.text = 'Seleccionado: --'
        sensor_checklist.refresh()

        started_at = time.time()
        while True:
            elapsed = time.time() - started_at
            if elapsed >= SEARCH_WINDOW_S:
                break

            now = time.time()
            with state.sensor_lock:
                for s in list(state.available_sensors):
                    last = state.sensor_last_seen.get(s, 0.0)
                    if now - last <= state.SENSOR_STALE_S:
                        discovered.add(s)

            remaining = max(0.0, SEARCH_WINDOW_S - elapsed)
            status.text = f'Buscando sensores... {remaining:.1f} s'
            await asyncio.sleep(SEARCH_POLL_S)

        discovered_sensors = sorted(discovered)
        if not discovered_sensors:
            status.text = 'No se detectaron sensores en el escaneo. Puedes volver a intentar.'
        else:
            status.text = f'Sensores encontrados: {len(discovered_sensors)}'

        sensor_checklist.refresh()
        search_in_progress = False

    with ui.row().classes('gap-2'):
        ui.button('Buscar sensores', on_click=search_sensors).props('color=primary')
        ui.button('Limpiar selección', on_click=clear_selection).style('background-color:#737373 !important; color:#ffffff !important')

    async def connect_and_open_dashboard() -> None:
        if search_in_progress:
            ui.notify('Espera a que termine la búsqueda actual', type='warning')
            return

        if not selected_sensor:
            ui.notify('Selecciona un sensor', type='negative')
            return

        sensor_name = selected_sensor
        mqtt_handler.set_current_sensors([sensor_name])

        ui.notify('Conectando...', type='warning')
        if not mqtt_handler.publish_select_command([sensor_name]):
            ui.notify('No se pudo enviar SELECT al sensor', type='negative')
            return

        timeout_s = 12.0
        poll_s = 0.25
        waited_s = 0.0

        while waited_s < timeout_s:
            with state.data_lock:
                protocol_state = state.sensor_protocol_state.get(sensor_name)
            if protocol_state == 'selected':
                ui.notify('Sensor conectado, abriendo dashboard...', type='positive')
                ui.navigate.to(f'/dashboard/{sensor_name}')
                return
            await asyncio.sleep(poll_s)
            waited_s += poll_s

        ui.notify('Tiempo de espera agotado: el sensor no confirmó conexión', type='negative')

    ui.button('Conectar', on_click=connect_and_open_dashboard).props('color=primary')
