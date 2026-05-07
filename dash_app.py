from datetime import datetime, timedelta
import calendar
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import openmeteo_requests
from dash import Dash, dcc, html, Input, Output, State, callback
from functools import lru_cache

openmeteo = openmeteo_requests.Client()

url = "https://archive-api.open-meteo.com/v1/archive"

LAT = 42.81
LNG = 17.52

CENTER_START = [LAT, LNG]
ZOOM = 9

@lru_cache(maxsize=128)
def get_month(month, years_tuple, coords_tuple):
    years = list(years_tuple)
    coords = list(coords_tuple)
    
    def last_day_of_month(date_value):
        first_day_of_month = date_value.replace(day=1)
        last_day = (first_day_of_month.replace(month=first_day_of_month.month + 1) - timedelta(days=1))
        return last_day.day

    all_times = np.array([], dtype='datetime64')
    hourly_data = {
        'utc_time': np.array([], dtype='datetime64'),
        'local hour': np.array([]),
        'hour_bin': np.array([], dtype=int),
        'wind_speed_10m': np.array([]),
        'wind_speed_bin': np.array([], dtype=int),
        'wind_direction_10m': np.array([]),
        'compass_point': np.array([])
    }
    
    for year in years:
        params = {
            "latitude": coords[0],
            "longitude": coords[1],
            "start_date": f"{year}-{month:02d}-01",
            "end_date": f"{year}-{month:02d}-{last_day_of_month(datetime(year, month, 1))}",
            "timezone": 'auto',
            "wind_speed_unit": 'kn',
            "hourly": ["wind_speed_10m", "wind_direction_10m"]
        }

        responses = openmeteo.weather_api(url, params=params)
        response = responses[0]

        resp_coords = [response.Latitude(), response.Longitude()]

        time_offset = response.UtcOffsetSeconds()
        time_zone = response.TimezoneAbbreviation().decode('utf-8') if response.TimezoneAbbreviation() else ''
        elevation = response.Elevation()

        hourly = response.Hourly()
        hourly_wind_speed_10m = hourly.Variables(0).ValuesAsNumpy()
        hourly_wind_direction_10m = hourly.Variables(1).ValuesAsNumpy()

        times = pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly.Interval()),
            inclusive="left"
        )
        all_times = np.concatenate([all_times, times])
        local_times = (times.hour + time_offset // 3600) % 24
        hourly_data['utc_time'] = np.concatenate([hourly_data['utc_time'], times])
        hourly_data['local hour'] = np.concatenate([hourly_data['local hour'], local_times])
        hourly_data['hour_bin'] = np.concatenate([hourly_data['hour_bin'], local_times // 6 * 6])

        hourly_data["wind_speed_10m"] = np.concatenate([hourly_data["wind_speed_10m"],
                                                        hourly_wind_speed_10m])
        hourly_data['wind_speed_bin'] = np.concatenate([hourly_data['wind_speed_bin'],
                                                        hourly_wind_speed_10m // 5 * 5 + 5])

        hourly_data["wind_direction_10m"] = np.concatenate([hourly_data["wind_direction_10m"],
                                                            hourly_wind_direction_10m])
        hourly_data["compass_point"] = np.concatenate([hourly_data["compass_point"],
                                                        (hourly_wind_direction_10m + 11.25) % 360 // 22.5 * 22.5])

    return pd.DataFrame(data=hourly_data), resp_coords, time_zone, elevation


months_dict = {v: i for i, v in enumerate(calendar.month_name)}
months_dict.pop('')

time_frames = {
    'morning': 'Morning (6AM to Noon)',
    'afternoon': 'Afternoon (Noon to 6PM)',
    'evening': 'Evening (6PM to Midnight)',
    'night': 'Night (Midnight to 6AM)'
}

# Initialize Dash app
app = Dash(__name__)

app.layout = html.Div([
    html.Div([
        # Header
        html.H1("Wind Rose Analysis", style={'textAlign': 'center', 'marginBottom': 30}),
        
        html.Div([
            # Left column
            html.Div([
                # Settings Panel
                html.Div([
                    html.H3("Settings"),
                    html.Div([
                        html.Label("Month:"),
                        dcc.Dropdown(
                            id='month-dropdown',
                            options=[{'label': month, 'value': month} for month in months_dict.keys()],
                            value='September',
                            clearable=False
                        ),
                    ], style={'marginBottom': 15}),
                    html.Div([
                        html.Label("Years:"),
                        dcc.Dropdown(
                            id='years-dropdown',
                            options=[{'label': str(2000 + x), 'value': 2000 + x} for x in range(26)],
                            value=[2020, 2021, 2022, 2023, 2024],
                            multi=True,
                            clearable=False
                        ),
                    ], style={'marginBottom': 15}),
                    html.Div([
                        html.Label("Latitude:"),
                        dcc.Input(
                            id='lat-input',
                            type='number',
                            value=LAT,
                            step=0.01
                        ),
                    ], style={'marginBottom': 10}),
                    html.Div([
                        html.Label("Longitude:"),
                        dcc.Input(
                            id='lng-input',
                            type='number',
                            value=LNG,
                            step=0.01
                        ),
                    ], style={'marginBottom': 15}),
                    html.Button('Update Data', id='update-button', n_clicks=0,
                               style={'width': '100%', 'padding': '10px', 'backgroundColor': '#4CAF50',
                                     'color': 'white', 'border': 'none', 'borderRadius': '4px',
                                     'cursor': 'pointer', 'fontSize': '16px'})
                ], style={'border': '1px solid #ddd', 'padding': '15px', 'borderRadius': '4px',
                         'marginBottom': '20px', 'backgroundColor': '#f9f9f9'}),
                
                # Map
                html.Div([
                    html.H3("Location"),
                    dcc.Graph(id='location-map', style={'height': '400px'})
                ], style={'border': '1px solid #ddd', 'padding': '15px', 'borderRadius': '4px',
                         'marginBottom': '20px'}),
                
                # Data Table
                html.Div([
                    html.H3("All Data"),
                    html.Div(id='data-table-container',
                            style={'maxHeight': '400px', 'overflowY': 'auto'})
                ], style={'border': '1px solid #ddd', 'padding': '15px', 'borderRadius': '4px'})
            ], style={'flex': '1', 'marginRight': '20px'}),
            
            # Right column
            html.Div([
                html.Div([
                    html.Label("Timeframe:"),
                    dcc.RadioItems(
                        id='timeframe-radio',
                        options=[{'label': ' ' + time_frames[tf], 'value': tf}
                                for tf in ['morning', 'afternoon', 'evening', 'night']],
                        value='morning',
                        style={'marginBottom': '15px'}
                    ),
                ], style={'border': '1px solid #ddd', 'padding': '15px', 'borderRadius': '4px',
                         'marginBottom': '20px', 'backgroundColor': '#f9f9f9'}),
                
                # Wind Rose Chart
                html.Div([
                    dcc.Loading(
                        id="loading",
                        type="default",
                        children=[
                            dcc.Graph(id='windrose-chart', style={'height': '600px'})
                        ]
                    )
                ], style={'border': '1px solid #ddd', 'padding': '15px', 'borderRadius': '4px'})
            ], style={'flex': '1'})
        ], style={'display': 'flex', 'gap': '20px'})
    ], style={'padding': '20px', 'maxWidth': '1600px', 'margin': '0 auto'})
], style={'fontFamily': 'Arial, sans-serif', 'backgroundColor': '#f5f5f5', 'minHeight': '100vh', 'padding': '20px'})

# Store for caching data
app.layout.children.append(dcc.Store(id='dataframe-store'))
app.layout.children.append(dcc.Store(id='location-store', data={'coords': CENTER_START, 'timezone': '', 'elevation': 0}))


@callback(
    [Output('dataframe-store', 'data'),
     Output('location-store', 'data')],
    Input('update-button', 'n_clicks'),
    [State('month-dropdown', 'value'),
     State('years-dropdown', 'value'),
     State('lat-input', 'value'),
     State('lng-input', 'value')],
    prevent_initial_call=False
)
def update_data(n_clicks, month, years, lat, lng):
    if not all([month, years, lat, lng]):
        return None, {'coords': CENTER_START, 'timezone': '', 'elevation': 0}
    
    month_num = months_dict.get(month, 8)
    years_tuple = tuple(sorted(years))
    coords_tuple = (lat, lng)
    
    hourly_dataframe, resp_coords, time_zone, elevation = get_month(month_num, years_tuple, coords_tuple)
    
    # Store dataframe as JSON
    df_json = hourly_dataframe.to_json(date_format='iso', orient='split')
    
    location_data = {
        'coords': resp_coords,
        'timezone': time_zone,
        'elevation': elevation
    }
    
    return df_json, location_data


@callback(
    Output('location-map', 'figure'),
    Input('location-store', 'data'),
    prevent_initial_call=False
)
def update_map(location_data):
    if location_data is None:
        return go.Figure().add_annotation(text="No location data available")
    
    coords = location_data['coords']
    
    # Create a simple scatter mapbox with a marker at the location
    fig = px.scatter_mapbox(
        pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]], 'name': ['Location']}),
        lat='lat',
        lon='lon',
        hover_name='name',
        title='Location',
        zoom=ZOOM
    )
    
    fig.update_layout(
        mapbox_style='open-street-map',
        height=400,
        margin={"r": 0, "t": 30, "l": 0, "b": 0}
    )
    
    return fig


@callback(
    Output('windrose-chart', 'figure'),
    [Input('dataframe-store', 'data'),
     Input('timeframe-radio', 'value')],
    prevent_initial_call=False
)
def update_windrose(df_json, timeframe):
    if df_json is None:
        return go.Figure().add_annotation(text="No data available")
    
    hourly_dataframe = pd.read_json(df_json, orient='split')
    hourly_dataframe['utc_time'] = pd.to_datetime(hourly_dataframe['utc_time'])
    
    # Filter wind speed > 3
    hourly_dataframe = hourly_dataframe[hourly_dataframe["wind_speed_10m"] > 3]
    mean_hourly_dataframe = hourly_dataframe.groupby(['hour_bin', 'compass_point', 'wind_speed_bin'],
                                                      as_index=False).size()
    
    # Get data for selected timeframe
    hour_bins = {'morning': 6, 'afternoon': 12, 'evening': 18, 'night': 0}
    timeframe_data = mean_hourly_dataframe[mean_hourly_dataframe['hour_bin'] == hour_bins[timeframe]]
    
    fig = px.bar_polar(timeframe_data,
                       r="size", theta="compass_point",
                       color="wind_speed_bin", template="ygridoff",
                       title=time_frames[timeframe],
                       color_discrete_sequence=px.colors.sequential.Plasma_r)
    
    fig.update_layout(height=600)
    return fig


@callback(
    Output('data-table-container', 'children'),
    Input('dataframe-store', 'data'),
    prevent_initial_call=False
)
def update_table(df_json):
    if df_json is None:
        return html.P("No data available")
    
    hourly_dataframe = pd.read_json(df_json, orient='split')
    hourly_dataframe['utc_time'] = pd.to_datetime(hourly_dataframe['utc_time'])
    
    # Display a subset of columns
    display_df = hourly_dataframe[['utc_time', 'local hour', 'wind_speed_10m', 
                                   'wind_direction_10m', 'compass_point']].head(100)
    
    return html.Table([
        html.Thead(
            html.Tr([html.Th(col) for col in display_df.columns])
        ),
        html.Tbody([
            html.Tr([html.Td(str(val)) for val in row])
            for row in display_df.values
        ])
    ], style={'width': '100%', 'borderCollapse': 'collapse', 'fontSize': '12px'})


if __name__ == '__main__':
    app.run_server(debug=True)
