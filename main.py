"""
Punto de entrada para la aplicación modular del panel MQTT.

Este script importa todos los componentes necesarios para compilar
la aplicación: los módulos de página, el controlador MQTT y el estado global.
Inicia los clientes MQTT de supervisión y medición y, a continuación,
lanza el servidor NiceGUI. Al añadir nuevas páginas u otras funciones,
importe los módulos aquí para que las rutas se registren en NiceGUI.

Ejecute este archivo con ``python main.py`` para iniciar el panel.
"""

from __future__ import annotations

from nicegui import ui

import mqtt_handler
import pages.selector_page  # registers the index page
import pages.dashboard_page  # registers the dashboard page

# Start MQTT clients (network threads)
mqtt_handler.start_supervisor_mqtt()
mqtt_handler.start_mqtt()

# UI configuration
UI_HOST = '0.0.0.0'  # use 0.0.0.0 if you want to access from other devices
UI_PORT = 8765

ui.run(host=UI_HOST, port=UI_PORT, title='Dashboard MQTT con NiceGUI')