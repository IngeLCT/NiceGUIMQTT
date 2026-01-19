"""
NiceGUI page for selecting a sensor.

This page lists all discovered sensors and lets the user select
one. When a sensor is chosen, the application navigates to the
dashboard page. The list of available sensors is refreshed
periodically by reading the ``available_sensors`` set from
``state``.

To register the page with NiceGUI, simply import this module in
your main script. The route is defined by the ``@ui.page``
decorator.
"""

from __future__ import annotations

from nicegui import ui

import mqtt_handler
import state


@ui.page('/')
def page_index() -> None:
    """Sensor selection page."""
    ui.label('Selector de Sensor (EQ1/)').classes('text-2xl font-bold')
    ui.label(
        'Se detectan automáticamente los sensores en EQ1/; puedes seleccionar y abrir el dashboard.'
    ).classes('text-sm text-gray-600')

    with ui.row().classes('w-full items-center gap-4'):
        ui.label('Sensores').classes('text-sm')
        sensor_select = ui.select(options=[], value=None).props('clearable')
        status = ui.label('Buscando sensores...').classes('text-sm')

    def refresh_sensors() -> None:
        with state.sensor_lock:
            opts = sorted(state.available_sensors)
        sensor_select.options = opts
        sensor_select.update()
        status.text = f'Sensores detectados: {len(opts)}'

    ui.timer(0.5, refresh_sensors)

    def open_dashboard() -> None:
        s = sensor_select.value
        if not s:
            ui.notify('Selecciona un sensor', type='negative')
            return
        mqtt_handler.set_current_sensor(str(s))
        ui.navigate.to(f'/dashboard/{s}')

    ui.button('Abrir dashboard', on_click=open_dashboard).props('color=primary')