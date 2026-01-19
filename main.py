"""
Entry point for the modular MQTT dashboard application.

This script imports all the necessary components to build the
application: the page modules, the MQTT handler and global state.
It starts the supervisor and measurement MQTT clients and then
launches the NiceGUI server. When adding new pages or other
functionality, import the modules here so that the routes are
registered with NiceGUI.

Run this file with ``python main.py`` to start the dashboard.
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