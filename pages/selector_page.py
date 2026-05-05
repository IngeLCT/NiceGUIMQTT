"""
Página de NiceGUI para seleccionar un sensor.

Esta página inicia un escaneo automático al abrirse y mantiene una vigilancia
ligera en segundo plano. La lista solo se vuelve a renderizar cuando cambia de
verdad: si aparece un sensor nuevo o si uno disponible deja de estarlo.
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
        'Al abrir, la página detecta sensores automáticamente y solo actualiza la lista cuando hay cambios reales.'
    ).classes('text-sm').style('color: #f2f2f2')

    selected_sensor: str | None = None
    discovered_sensors: list[str] = []
    initial_scan_in_progress = False
    INITIAL_SCAN_S = 10.0
    INITIAL_POLL_S = 0.25
    MONITOR_POLL_S = 1.0

    with ui.row().classes('w-full items-center gap-4'):
        ui.label('Sensores').classes('text-sm')
        status = ui.label('Preparando escaneo inicial...').classes('text-sm')
        proto_status = ui.label('Seleccionado: --').classes('text-xs')

    with ui.row().classes('w-full items-center gap-2') as search_indicator:
        ui.spinner(size='lg', color='orange')
        ui.label('Detectando sensores...').classes('text-sm text-orange-300')
    search_indicator.set_visibility(False)

    @ui.refreshable
    def sensor_checklist() -> None:
        nonlocal selected_sensor

        if not discovered_sensors:
            with ui.card().classes('w-full max-w-2xl'):
                ui.label('No hay sensores disponibles.').classes('text-sm text-gray-400')
                ui.label('La página seguirá vigilando y actualizará la lista cuando detecte cambios.').classes('text-xs text-gray-500')
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

        proto_status.text = 'Seleccionado: ' + (selected_sensor if selected_sensor in discovered_sensors else '--')

    sensor_checklist()

    def clear_selection() -> None:
        nonlocal selected_sensor
        selected_sensor = None
        sensor_checklist.refresh()

    def sync_sensor_list() -> bool:
        nonlocal selected_sensor, discovered_sensors

        now = time.time()
        with state.sensor_lock:
            alive: list[str] = []
            for s in list(state.available_sensors):
                last = state.sensor_last_seen.get(s, 0.0)
                if now - last <= state.SENSOR_STALE_S:
                    alive.append(s)
                else:
                    state.available_sensors.discard(s)
                    state.sensor_last_seen.pop(s, None)

        alive_sorted = sorted(alive)
        if selected_sensor is not None and selected_sensor not in alive_sorted:
            selected_sensor = None

        changed = alive_sorted != discovered_sensors
        discovered_sensors = alive_sorted
        proto_status.text = 'Seleccionado: ' + (selected_sensor if selected_sensor in discovered_sensors else '--')
        status.text = f'Sensores disponibles: {len(discovered_sensors)}' if discovered_sensors else 'Sin sensores disponibles por ahora.'
        return changed

    def update_search_indicator() -> None:
        has_sensors = bool(discovered_sensors)
        search_indicator.set_visibility(not has_sensors)
        if has_sensors:
            status.text = f'Sensores disponibles: {len(discovered_sensors)}'
        else:
            status.text = 'Buscando sensores...'

    async def initial_discovery() -> None:
        nonlocal initial_scan_in_progress
        if initial_scan_in_progress:
            return

        initial_scan_in_progress = True
        update_search_indicator()

        started_at = time.time()
        saw_change = False
        while (time.time() - started_at) < INITIAL_SCAN_S:
            if sync_sensor_list():
                saw_change = True
                sensor_checklist.refresh()
            update_search_indicator()
            if discovered_sensors:
                break
            await asyncio.sleep(INITIAL_POLL_S)

        if sync_sensor_list() or not saw_change:
            sensor_checklist.refresh()
        update_search_indicator()
        initial_scan_in_progress = False

    async def monitor_sensor_changes() -> None:
        if initial_scan_in_progress:
            return
        if sync_sensor_list():
            sensor_checklist.refresh()
        update_search_indicator()

    async def connect_and_open_dashboard() -> None:

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

    with ui.row().classes('gap-2'):
        ui.button('Limpiar selección', on_click=clear_selection).style('background-color:#737373 !important; color:#ffffff !important')
        ui.button('Conectar', on_click=connect_and_open_dashboard).style('background-color:#ff8533 !important; color:#ffffff !important')

    ui.timer(0.1, lambda: asyncio.create_task(initial_discovery()), once=True)
    ui.timer(MONITOR_POLL_S, lambda: asyncio.create_task(monitor_sensor_changes()))
