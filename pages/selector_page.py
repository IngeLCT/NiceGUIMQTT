"""
Página de NiceGUI para seleccionar un sensor.

Esta página enumera todos los sensores detectados y permite al usuario
seleccionar uno o varios(Max 3). Al seleccionar un sensor, la aplicación
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
    ui.label('Selector de Sensor EQ1/').classes('text-2xl font-bold')
    ui.label(
        'Se detectan automáticamente los sensores de EQ1/; puedes seleccionar y abrir el dashboard.'
    ).classes('text-sm text-gray-600')

    # NOTE (NiceGUI 3.5.0):
    # ``ui.select(multiple=True)`` puede lanzar el error
    # "list indices must be integers or slices, not str" en algunos entornos
    # (proviene del manejo interno de eventos del select).
    # Para hacerlo 100% estable, usamos una lista de checkboxes.
    selected_sensors: set[str] = set()

    with ui.row().classes('w-full items-center gap-4'):
        ui.label('Sensores').classes('text-sm')
        status = ui.label('Buscando sensores...').classes('text-sm')

    @ui.refreshable
    def sensor_checklist() -> None:
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
                    selected_sensors.discard(s)
            opts = sorted(alive)

        if not opts:
            status.text = 'No se detectaron sensores, Buscando sensores...'
            ui.label('Buscando sensores...').classes('text-sm text-gray-600')
            return

        status.text = f'Sensores detectados: {len(opts)}'
        with ui.card().classes('w-full max-w-2xl'):
            with ui.column().classes('max-h-72 overflow-auto gap-1'):
                for s in opts:
                    def _on_change(e, name=s) -> None:
                        if e.value:
                            selected_sensors.add(name)
                        else:
                            selected_sensors.discard(name)

                    ui.checkbox(s, value=(s in selected_sensors), on_change=_on_change)

    sensor_checklist()
    ui.timer(0.5, sensor_checklist.refresh)

    def select_all() -> None:
        with state.sensor_lock:
            selected_sensors.update(state.available_sensors)
        sensor_checklist.refresh()

    def clear_selection() -> None:
        selected_sensors.clear()
        sensor_checklist.refresh()

    with ui.row().classes('gap-2'):
        ui.button('Seleccionar todo', on_click=select_all).props('outline')
        ui.button('Limpiar', on_click=clear_selection).props('outline')

    def open_dashboard() -> None:
        selected_list = sorted(selected_sensors)
        if not selected_list:
            ui.notify('Selecciona al menos un sensor', type='negative')
            return
        # Preparar cadena para la URL separada por comas
        sensors_str = ','.join(selected_list)
        mqtt_handler.set_current_sensors(selected_list)
        ui.navigate.to(f'/dashboard/{sensors_str}')

    ui.button('Abrir dashboard', on_click=open_dashboard).props('color=primary')