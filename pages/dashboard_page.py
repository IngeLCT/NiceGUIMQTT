from __future__ import annotations

import csv
from typing import Any, Dict, List, Optional

import plotly.graph_objects as go
from nicegui import ui

import mqtt_handler
import sensor_config
import state


def create_figure(metric: Dict[str, Any]) -> go.Figure:
    """Crea una grafica Plotly para una metrica (configurada en sensor_config.py)."""
    fig = go.Figure()
    hover_name = metric.get('hover_name', metric.get('label', metric.get('id', 'value')))
    unit = metric.get('unit', '')
    color = metric.get('color', '#1f77b4')

    fig.add_trace(
        go.Scatter(
            type='scatter',
            x=[],
            y=[],
            name=hover_name,
            mode='lines',
            line={'color': color},
            connectgaps=True,
            hovertemplate=f"t=%{{x:.2f}} s<br>{hover_name}=%{{y}} {unit}<extra></extra>",
            showlegend=False,
        )
    )

    fig.update_layout(
        title=f"{metric.get('label', hover_name)} - Tiempo",
        showlegend=False,
        plot_bgcolor='#ffffff',
        paper_bgcolor='#ffffff',
        margin={'l': 55, 'r': 20, 'b': 85, 't': 30, 'pad': 4},
        yaxis={
            'title': {'text': f"{metric.get('label', hover_name)} ({unit})".strip(), 'font': {'family': 'Arial', 'color': color, 'size': 14}},
            'tickfont': {'family': 'Arial', 'color': color, 'size': 14},
            'color': color,
            'autorange': True,
            'showgrid': True,
        },
        xaxis={
            'title': {'text': 'Tiempo transcurrido (s)', 'font': {'family': 'Arial', 'color': '#000000', 'size': 14}},
            'tickfont': {'family': 'Arial', 'color': '#000000', 'size': 14},
            'type': 'linear',
            'showgrid': True,
        },
    )
    return fig


@ui.page('/dashboard/{sensor}')
def page_dashboard(sensor: str) -> None:
    # Asegura que el cliente de medicion este suscrito al sensor seleccionado
    mqtt_handler.set_current_sensor(sensor)

    metric_defs: List[Dict[str, Any]] = sensor_config.get_metrics(sensor)
    if not metric_defs:
        ui.button('⟵ Volver', on_click=lambda: ui.navigate.to('/')).props('flat color=primary')
        ui.label(f'No hay configuración de métricas para: {sensor}').classes('text-xl font-bold')
        ui.label('Agrega este sensor/tipo a sensor_config.py para poder ver gráficas.').classes('text-sm text-gray-600')
        return

    metric_ids = [m['id'] for m in metric_defs]

    # Figuras y plots (dinámicos)
    figures: Dict[str, go.Figure] = {m['id']: create_figure(m) for m in metric_defs}
    plots: Dict[str, Any] = {}

    # Referencias UI
    t_label = None
    dropped_label = None
    metric_labels: Dict[str, Any] = {}

    config_dialog = None
    duration_input = None
    unit_select = None

    series_selector = None
    series_table = None

    def configure_time(value: Any, unit: str) -> None:
        """Configura la duración de la medición. Si value <= 0 -> sin límite."""
        try:
            v = float(value)
        except Exception:
            v = 0.0

        if v <= 0:
            state.measurement_duration_s = None
        else:
            state.measurement_duration_s = v * (60.0 if unit == 'minutos' else 1.0)

        ui.notify(
            'Duración configurada: sin límite' if state.measurement_duration_s is None else f'Duración configurada: {state.measurement_duration_s:.1f} s',
            type='info',
        )

    def clear_current_measurement(clear_buffers: bool = False) -> None:
        """Limpia datos en vivo (y opcionalmente buffers) y restaura UI."""
        with state.data_lock:
            if clear_buffers:
                state.buf_t_s.clear()
                for mid in state.current_metric_ids:
                    state.buf_values[mid].clear()

            state.last_t_s = None
            for mid in state.current_metric_ids:
                state.last_values[mid] = None
            state.measurement_sample_index = 0
            state.measurement_elapsed_s = 0.0

        # limpiar figuras
        for mid in metric_ids:
            fig = figures[mid]
            fig.data[0].x = []
            fig.data[0].y = []
            fig.update_layout(yaxis={'autorange': True})

        # etiquetas
        if t_label is not None:
            t_label.text = 't_s: --'

        for m in metric_defs:
            mid = m['id']
            lbl = metric_labels.get(mid)
            if lbl is not None:
                lbl.text = f"{m['label']}: -- {m.get('unit','')}".strip()

        if dropped_label is not None:
            dropped_label.text = 'avg_dropped: --'

        # tabla
        if series_table is not None:
            series_table.rows = []
            series_table.update()

        # actualizar plots
        for p in plots.values():
            p.update()

    def start_measurement() -> None:
        """Inicia la medición y reinicia el tiempo relativo."""
        state.display_series_index = None
        state.is_measuring = True

        if series_selector is not None:
            series_selector.value = None
            series_selector.update()

        clear_current_measurement(clear_buffers=True)
        ui.notify('Medición iniciada', type='positive')

    def stop_measurement() -> None:
        if state.is_measuring:
            state.is_measuring = False
            ui.notify('Medición detenida', type='warning')

    def save_series() -> None:
        """Guarda la medición actual como una serie y prepara para la siguiente."""
        state.is_measuring = False

        with state.data_lock:
            x = list(state.buf_t_s)
            values_copy = {mid: list(state.buf_values.get(mid, [])) for mid in metric_ids}

        if not x:
            ui.notify('No hay datos para guardar', type='negative')
            return

        state.series_counter += 1
        name = f'Serie {state.series_counter}'
        state.series_data.append({'name': name, 't_s': x, 'values': values_copy, 'metric_ids': list(metric_ids)})

        if series_selector is not None:
            series_selector.options = [s['name'] for s in state.series_data]
            series_selector.update()

        state.display_series_index = None
        clear_current_measurement(clear_buffers=True)
        ui.notify(f'{name} guardada', type='positive')

    def export_csv() -> None:
        """Exporta todas las series a un CSV. Columnas: serie, t_s y todas las metricas."""
        if not state.series_data:
            ui.notify('No hay series guardadas para exportar', type='negative')
            return

        header = ['serie', 't_s'] + metric_ids

        with open(state.CSV_EXPORT_FILE, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(header)
            for s in state.series_data:
                name = s['name']
                x = s.get('t_s', [])
                vals = s.get('values', {})
                for i in range(len(x)):
                    row = [name, f"{x[i]:.2f}" if x[i] is not None else '']
                    for mid in metric_ids:
                        v = None
                        try:
                            v = vals.get(mid, [])[i]
                        except Exception:
                            v = None
                        row.append('' if v is None else f"{v}")
                    w.writerow(row)

        ui.download.file(state.CSV_EXPORT_FILE)

    def clear_all() -> None:
        """Borra todas las series guardadas y reinicia todo."""
        state.is_measuring = False
        state.series_data = []
        state.series_counter = 0
        state.display_series_index = None

        if series_selector is not None:
            series_selector.options = []
            series_selector.value = None
            series_selector.update()

        clear_current_measurement(clear_buffers=True)
        ui.notify('Series eliminadas. Listo para iniciar de nuevo.', type='positive')

    def display_series(event) -> None:
        """Muestra una serie guardada en las gráficas y tabla."""
        state.is_measuring = False
        value = event.value
        if not value:
            state.display_series_index = None
            return

        idx = None
        for i, s in enumerate(state.series_data):
            if s.get('name') == value:
                idx = i
                break
        state.display_series_index = idx

    def _build_table_rows(x: List[float], y_map: Dict[str, List[Optional[float]]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for i in range(len(x)):
            row: Dict[str, Any] = {'t_s': f'{x[i]:.2f}'}
            for mid in metric_ids:
                y = y_map.get(mid, [])
                val = y[i] if i < len(y) else None
                row[mid] = '' if val is None else f'{val}'
            rows.append(row)
        return rows

    def update_plots() -> None:
        """Actualiza gráficas, etiquetas y tabla."""
        # Paro automático basado en tiempo relativo
        if state.is_measuring and state.measurement_duration_s is not None:
            with state.data_lock:
                elapsed = state.measurement_elapsed_s
            if elapsed >= state.measurement_duration_s:
                stop_measurement()

        # Obtener datos
        with state.data_lock:
            if state.display_series_index is None:
                x = list(state.buf_t_s)
                y_map = {mid: list(state.buf_values.get(mid, [])) for mid in metric_ids}
                lts = state.last_t_s
                last_map = {mid: state.last_values.get(mid) for mid in metric_ids}
                lavg = state.last_avg_dropped
                show_avg = True
            else:
                s = state.series_data[state.display_series_index] if (state.display_series_index is not None and 0 <= state.display_series_index < len(state.series_data)) else None
                x = list(s.get('t_s', [])) if s else []
                vals = s.get('values', {}) if s else {}
                y_map = {mid: list(vals.get(mid, [])) for mid in metric_ids}
                lts = x[-1] if x else None
                last_map = {mid: (y_map[mid][-1] if y_map.get(mid) else None) for mid in metric_ids}
                lavg = None
                show_avg = False

        # Etiquetas
        if t_label is not None:
            t_label.text = f"t_s: {lts if lts is not None else '--'}"

        for m in metric_defs:
            mid = m['id']
            lbl = metric_labels.get(mid)
            if lbl is not None:
                val = last_map.get(mid)
                unit = m.get('unit', '')
                if val is None:
                    s = '--'
                else:
                    s = f'{float(val):.2f}'.rstrip('0').rstrip('.')  # 26.0 -> "26", 26.50 -> "26.5"

                lbl.text = f"{m['label']}: {s} {unit}".strip()

        if dropped_label is not None:
            dropped_label.text = f"avg_dropped: {lavg if (show_avg and lavg is not None) else '--'}"

        # Figuras
        for m in metric_defs:
            mid = m['id']
            fig = figures[mid]
            fig.data[0].x = x
            fig.data[0].y = y_map.get(mid, [])

        # Rango X: solo ventana en vivo
        if state.display_series_index is None and x:
            x_max = x[-1]
            x_min = max(0.0, x_max - state.WINDOW_S)
            for mid in metric_ids:
                figures[mid].update_layout(
                    xaxis={'range': [x_min, x_max], 'showgrid': True},
                    yaxis={'autorange': True, 'showgrid': True},
                )
        else:
            for mid in metric_ids:
                figures[mid].update_layout(
                    xaxis={'showgrid': True},
                    yaxis={'autorange': True, 'showgrid': True},
                )

        for p in plots.values():
            p.update()

        if series_table is not None:
            series_table.rows = _build_table_rows(x, y_map)
            series_table.update()

    # =========================
    # UI
    # =========================

    ui.button('⟵ Volver', on_click=lambda: ui.navigate.to('/')).props('flat color=primary')
    ui.label(f'Dashboard - Sensor: {sensor}').classes('text-2xl font-bold')

    with ui.row().classes('w-full items-center gap-6'):
        t_label = ui.label('t_s: --').classes('text-lg font-bold')
        for m in metric_defs:
            metric_labels[m['id']] = ui.label(f"{m['label']}: -- {m.get('unit','')}".strip()).classes('text-lg font-bold')
        dropped_label = ui.label('avg_dropped: --').classes('text-lg font-bold')

    # Dialogo configuracion de tiempo
    with ui.dialog() as config_dialog, ui.card():
        ui.label('Configurar duración de la medición').classes('text-lg font-bold')
        duration_input = ui.number(label='Duración (0 = sin límite)', value=1, min=0, precision=0)
        unit_select = ui.select(options=['segundos', 'minutos'], value='segundos')
        with ui.row().classes('gap-2'):
            ui.button(
                'Aceptar',
                on_click=lambda: (configure_time(duration_input.value, unit_select.value), config_dialog.close()),
            ).props('color=primary')
            ui.button('Cancelar', on_click=config_dialog.close).props('color=negative')

    # Barra de controles
    with ui.row().classes('gap-2'):
        ui.button('Configurar tiempo', on_click=config_dialog.open).props('color=primary')
        ui.button('Iniciar', on_click=start_measurement).props('color=positive')
        ui.button('Detener', on_click=stop_measurement).props('color=negative')
        ui.button('Guardar serie', on_click=save_series).style('background-color:#cccc00 !important; color:#000000 !important')
        ui.button('Exportar CSV', on_click=export_csv).style('background-color:#6600ff !important; color:#ffffff !important')
        ui.button('Limpiar', on_click=clear_all).style('background-color:#7a7a52 !important; color:#ffffff !important')

    with ui.row().classes('w-full items-center gap-4'):
        ui.label('Serie').classes('text-sm')
        series_selector = ui.select(
            options=[s['name'] for s in state.series_data],
            label='Serie',
            on_change=display_series,
        ).props('clearable')

    ui.separator()

    # Gráficas dinámicas
    for m in metric_defs:
        mid = m['id']
        plots[mid] = ui.plotly(figures[mid]).classes('w-full h-72')

    # Tabla
    ui.separator()
    ui.label('Tabla de datos').classes('text-lg font-bold')
    ui.label('Muestra los puntos visibles (en vivo o de la serie seleccionada).').classes('text-sm text-gray-600')

    columns = [{'name': 't_s', 'label': 't_s (s)', 'field': 't_s', 'align': 'left'}]
    for m in metric_defs:
        mid = m['id']
        unit = m.get('unit', '')
        columns.append({'name': mid, 'label': f"{m['label']} ({unit})".strip(), 'field': mid, 'align': 'left'})

    series_table = ui.table(columns=columns, rows=[], row_key='t_s').classes('w-full')

    ui.timer(state.REFRESH_S, update_plots)
    update_plots()

