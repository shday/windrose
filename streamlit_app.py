from datetime import datetime, timedelta
import calendar
import streamlit as st
import numpy as np
import pandas as pd
import plotly.express as px
import openmeteo_requests
import folium
from streamlit_folium import st_folium

openmeteo = openmeteo_requests.Client()

url = "https://archive-api.open-meteo.com/v1/archive"

st.set_page_config(layout="wide")

LAT = 42.81
LNG = 17.52

CENTER_START = [LAT,LNG]
ZOOM = 9

@st.cache_data(show_spinner=False)
def get_month(month,years,coords):

    def last_day_of_month(date_value):
        first_day_of_month = date_value.replace(day=1)
        last_day = (first_day_of_month.replace(month=first_day_of_month.month + 1) - timedelta(days=1))
        return last_day.day
    

    all_times = np.array([],dtype='datetime64')
    hourly_data = {
        'utc_time' : np.array([],dtype='datetime64'),
        'local hour': np.array([]),
        'hour_bin':np.array([],dtype=int),
        'wind_speed_10m':np.array([]),
        'wind_speed_bin':np.array([],dtype=int),
        'wind_direction_10m':np.array([]),
        'compass_point':np.array([])
    }
    for year in years:
        params = {
            "latitude": coords[0],
            "longitude": coords[1],
            "start_date": f"{year}-{month:02d}-01",
            "end_date": f"{year}-{month:02d}-{last_day_of_month(datetime(year,month,1))}",
            "timezone": 'auto',
            "wind_speed_unit":'kn',
            "hourly": ["wind_speed_10m", "wind_direction_10m"]
        }

        responses = openmeteo.weather_api(url, params=params)
        # Process first location. Add a for-loop for multiple locations or weather models
        response = responses[0]

        resp_coords = [response.Latitude(), response.Longitude()]

        time_offset = response.UtcOffsetSeconds()
        time_zone = response.TimezoneAbbreviation().decode('utf-8') if response.TimezoneAbbreviation() else ''
        elevation = response.Elevation()

        # Process hourly data. The order of variables needs to be the same as requested.
        hourly = response.Hourly()
        hourly_wind_speed_10m = hourly.Variables(0).ValuesAsNumpy()# * 0.539957 #to Knots
        hourly_wind_direction_10m = hourly.Variables(1).ValuesAsNumpy()

        times = pd.date_range(
            start = pd.to_datetime(hourly.Time(), unit = "s", utc = True),
            end = pd.to_datetime(hourly.TimeEnd(), unit = "s", utc = True),
            freq = pd.Timedelta(seconds = hourly.Interval()),
            inclusive = "left"
        )
        all_times = np.concatenate([all_times,times])
        local_times = (times.hour+time_offset//3600)%24
        hourly_data['utc_time'] = np.concatenate([hourly_data['utc_time'],times])
        hourly_data['local hour'] = np.concatenate([hourly_data['local hour'],local_times])
        hourly_data['hour_bin'] = np.concatenate([hourly_data['hour_bin'],local_times // 6 * 6])

        hourly_data["wind_speed_10m"] = np.concatenate([hourly_data["wind_speed_10m"],
                                                        hourly_wind_speed_10m])
        hourly_data['wind_speed_bin'] = np.concatenate([hourly_data['wind_speed_bin'],
                                                        hourly_wind_speed_10m // 5 * 5 + 5 
                                                        ])

        hourly_data["wind_direction_10m"] = np.concatenate([hourly_data["wind_direction_10m"],
                                                            hourly_wind_direction_10m])
        hourly_data["compass_point"] = np.concatenate([hourly_data["compass_point"],
                                                        (hourly_wind_direction_10m+11.25)%360//22.5*22.5])

    return pd.DataFrame(data = hourly_data), resp_coords, time_zone, elevation

if 'center' not in st.session_state:
    st.session_state["center"] = CENTER_START
    st.session_state["last_clicked"] = CENTER_START
    st.session_state["zoom"] = ZOOM

if st.session_state.get('new') and st.session_state['new']['last_clicked']:
    st.session_state["last_clicked"] = list(st.session_state['new']['last_clicked'].values())

cols = st.columns([3,2])

months_dict = {v:i for i,v in enumerate(calendar.month_name)}
months_dict.pop('')


with cols[0]:
    with st.expander("Settings",expanded=True):
        month = st.selectbox("Month",months_dict.keys(),index=7,label_visibility='collapsed')
        years = st.multiselect('Years', [2000+x for x in range(26)],
                                default = [2020,2021,2022,2023,2024],
                                label_visibility='collapsed')


    hourly_dataframe, resp_coords, time_zone, elevation = get_month(months_dict[month],years,st.session_state['last_clicked'])
    st.session_state['marker'] = resp_coords



    m = folium.Map(location=st.session_state["center"], zoom_start=st.session_state["zoom"])

    fg = folium.FeatureGroup(name="Markers")
    fg.add_child(
        folium.Marker(
        location=st.session_state["marker"], 
        tooltip=f"""\
{st.session_state['marker'][0]:.2f}°N, {st.session_state['marker'][1]:.2f}°E<br/>
Elevation: {elevation} m<br/>
Timezone: {time_zone}""" 
        #tooltip="Click elsewhere!"
        )
    )
    st_folium(
        m,
        center=st.session_state["center"],
        zoom=st.session_state["zoom"],
        key="new",
        feature_group_to_add=fg,
        height=500,
        width=750,
    )



hourly_dataframe = hourly_dataframe[hourly_dataframe["wind_speed_10m"] > 3]
mean_hourly_dataframe = hourly_dataframe.groupby(['hour_bin','compass_point','wind_speed_bin'],as_index=False).size()

morning = mean_hourly_dataframe[mean_hourly_dataframe['hour_bin'] == 6]
afternoon = mean_hourly_dataframe[mean_hourly_dataframe['hour_bin'] == 12]
evening = mean_hourly_dataframe[mean_hourly_dataframe['hour_bin'] == 18]
night = mean_hourly_dataframe[mean_hourly_dataframe['hour_bin'] == 0]

windrose = {}

windrose['morning'] = px.bar_polar(mean_hourly_dataframe[mean_hourly_dataframe['hour_bin'] == 6],
                             r="size", theta="compass_point",
                            color="wind_speed_bin", template="plotly_dark", title=None,
                            color_discrete_sequence= px.colors.sequential.Plasma_r)
windrose['afternoon'] = px.bar_polar(mean_hourly_dataframe[mean_hourly_dataframe['hour_bin'] == 12],
                              r="size", theta="compass_point",title=None,
                            color="wind_speed_bin", template="plotly_dark",
                            color_discrete_sequence= px.colors.sequential.Plasma_r)
windrose['evening'] = px.bar_polar(mean_hourly_dataframe[mean_hourly_dataframe['hour_bin'] == 18], 
                             r="size", theta="compass_point",title=None,
                            color="wind_speed_bin", template="plotly_dark",
                            color_discrete_sequence= px.colors.sequential.Plasma_r)
windrose['night'] = px.bar_polar(mean_hourly_dataframe[mean_hourly_dataframe['hour_bin'] == 0], 
                             r="size", theta="compass_point",title=None,
                            color="wind_speed_bin", template="plotly_dark",
                            color_discrete_sequence= px.colors.sequential.Plasma_r)


with cols[1]:
    with st.expander('Morning (6AM to Noon)',expanded=True):
        st.plotly_chart(windrose['morning'])
    with st.expander('Afternoon (Noon to 6PM)',expanded=True):
        st.plotly_chart(windrose['afternoon'])
    with st.expander('Evening (6PM to Midnight)',expanded=False):
        st.plotly_chart(windrose['evening'])
    with st.expander('Night (Midnight to 6AM)',expanded=False):
        st.plotly_chart(windrose['night'])

with cols[0]:
    with st.expander("All Data"):
        st.dataframe(hourly_dataframe,
                    column_config={
                    "utc_time": st.column_config.DatetimeColumn(
                    "UTC Time",
                    format="D MMM YYYY, h a",
                    ),
                    }, hide_index=True)

