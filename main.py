"""
Inky Frame 7.3" Weather Display - Met Office DataHub
=====================================================
A dual-screen weather display for the Pimoroni Inky Frame 7.3":
- Main screen: Hourly meteogram (08:00-18:00, today or tomorrow)
- Secondary screen (A button): 7-day daily forecast

Uses data from the Met Office DataHub API.

Before running:
1. Create a secrets.py file with your WiFi credentials and API key:
   WIFI_SSID = "your_ssid"
   WIFI_PASSWORD = "your_password"
   MET_OFFICE_API_KEY = "your_api_key"

2. Get a free API key from https://datahub.metoffice.gov.uk/
   Subscribe to the "Site Specific" Global Spot data plan.

Author: Claude (Anthropic)
License: MIT
"""

import gc
import time
import urequests
import housekeeping

# Import Inky Frame specific modules
import inky_frame
from picographics import PicoGraphics, DISPLAY_INKY_FRAME_SPECTRA_7 as DISPLAY
from housekeeping import add_error_detail, clear_error_details, get_exception_name, safe_response_snippet
from housekeeping import connect_wifi, disconnect_wifi, rtc_date_is_valid, sync_time_if_needed
from housekeeping import uk_local_now, utc_iso_to_uk_local, weekday

# Try to import secrets - will fail if file doesn't exist
try:
    from secrets import WIFI_SSID, WIFI_PASSWORD, ALT_SSID, ALT_PASSWORD, MET_OFFICE_API_KEY, MET_OFFICE_OBS_KEY
except ImportError:
    print("ERROR: Please create secrets.py with WIFI_SSID, WIFI_PASSWORD, MET_OFFICE_API_KEY, and MET_OFFICE_OBS_KEY")
    raise

# =============================================================================
# CONFIGURATION - Edit these values for your location
# =============================================================================

# Hardcoded location: London, UK (change to your location)
LATITUDE = 53.9504
LONGITUDE = -1.0389
LOCATION_NAME = "Badger Hill"

# Nearest observation station geohash (find using find_nearest_station.py)
OBSERVATION_GEOHASH = "gcxh27"

# Display dimensions for Inky Frame 7.3"
WIDTH = 800
HEIGHT = 480

# =============================================================================
# COLOUR DEFINITIONS
# =============================================================================

# Inky Frame 7.3" has 6 colours available
from inky_frame import WHITE, BLACK, RED, BLUE, GREEN, YELLOW

# =============================================================================
# MET OFFICE WEATHER CODES
# =============================================================================

# Weather code to description and icon mapping
# Based on Met Office DataPoint code definitions
WEATHER_CODES = {
    -1: ("Trace Rain", "rain_light"),
    0: ("Clear", "clear_night"),
    1: ("Sunny", "sunny"),
    2: ("Partly Cloudy", "cloudy_night"),
    3: ("Partly Cloudy", "partly_cloudy"),
    5: ("Mist", "mist"),
    6: ("Fog", "fog"),
    7: ("Cloudy", "cloudy"),
    8: ("Overcast", "overcast"),
    9: ("Light Rain", "rain_light"),
    10: ("Light Rain", "rain_light"),
    11: ("Drizzle", "drizzle"),
    12: ("Light Rain", "rain_light"),
    13: ("Heavy Rain", "rain_heavy"),
    14: ("Heavy Rain", "rain_heavy"),
    15: ("Heavy Rain", "rain_heavy"),
    16: ("Sleet", "sleet"),
    17: ("Sleet", "sleet"),
    18: ("Sleet", "sleet"),
    19: ("Hail", "hail"),
    20: ("Hail", "hail"),
    21: ("Hail", "hail"),
    22: ("Light Snow", "snow_light"),
    23: ("Light Snow", "snow_light"),
    24: ("Light Snow", "snow_light"),
    25: ("Heavy Snow", "snow_heavy"),
    26: ("Heavy Snow", "snow_heavy"),
    27: ("Heavy Snow", "snow_heavy"),
    28: ("Thunder", "thunder"),
    29: ("Thunder", "thunder"),
    30: ("Thunder", "thunder"),
}


# =============================================================================
# WEATHER ICON DRAWING FUNCTIONS
# =============================================================================

def draw_sun(graphics, x, y, size=30):
    """Draw a sun icon"""
    graphics.set_pen(YELLOW)
    graphics.circle(x, y, size // 2)
    # Draw rays
    ray_length = size // 3
    for angle in range(0, 360, 45):
        import math
        rad = math.radians(angle)
        x1 = int(x + (size // 2 + 4) * math.cos(rad))
        y1 = int(y + (size // 2 + 4) * math.sin(rad))
        x2 = int(x + (size // 2 + ray_length) * math.cos(rad))
        y2 = int(y + (size // 2 + ray_length) * math.sin(rad))
        graphics.line(x1, y1, x2, y2)


def draw_cloud(graphics, x, y, size=30, colour=WHITE):
    """Draw a cloud icon with black outline"""
    r = size // 4
    
    # Draw black outline first (slightly larger)
    graphics.set_pen(BLACK)
    graphics.circle(x - r, y, r + 2)
    graphics.circle(x + r, y, r + 2)
    graphics.circle(x, y - r // 2, int(r * 1.2) + 2)
    graphics.circle(x - r // 2, y + r // 3, r + 2)
    graphics.circle(x + r // 2, y + r // 3, r + 2)
    
    # Draw white cloud on top
    graphics.set_pen(colour)
    graphics.circle(x - r, y, r)
    graphics.circle(x + r, y, r)
    graphics.circle(x, y - r // 2, int(r * 1.2))
    graphics.circle(x - r // 2, y + r // 3, r)
    graphics.circle(x + r // 2, y + r // 3, r)


def draw_rain(graphics, x, y, size=30, heavy=False):
    """Draw rain drops"""
    graphics.set_pen(BLUE)
    drops = 5 if heavy else 3
    for i in range(drops):
        dx = x - size // 2 + (i * size // (drops - 1)) if drops > 1 else x
        dy = y + size // 4
        # Draw rain drop
        graphics.line(dx, dy, dx - 3, dy + 10)


def draw_snow(graphics, x, y, size=30):
    """Draw snowflakes"""
    graphics.set_pen(WHITE)
    for i in range(3):
        dx = x - size // 3 + (i * size // 3)
        dy = y + size // 4 + (i % 2) * 8
        # Simple asterisk snowflake
        graphics.line(dx - 4, dy, dx + 4, dy)
        graphics.line(dx, dy - 4, dx, dy + 4)
        graphics.line(dx - 3, dy - 3, dx + 3, dy + 3)
        graphics.line(dx - 3, dy + 3, dx + 3, dy - 3)


def draw_thunder(graphics, x, y, size=30):
    """Draw a lightning bolt"""
    graphics.set_pen(YELLOW)
    # Simple lightning bolt shape
    points = [
        (x, y - size // 2),
        (x - size // 4, y),
        (x + size // 8, y),
        (x - size // 8, y + size // 2),
        (x + size // 4, y - size // 6),
        (x, y - size // 6),
    ]
    for i in range(len(points) - 1):
        graphics.line(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])


def draw_mist(graphics, x, y, size=30):
    """Draw mist/fog lines"""
    graphics.set_pen(WHITE)
    for i in range(4):
        dy = y - size // 3 + (i * size // 4)
        width = size - abs(i - 1.5) * 8
        graphics.line(int(x - width // 2), dy, int(x + width // 2), dy)


def draw_weather_icon(graphics, x, y, weather_code, size=40):
    """Draw weather icon based on Met Office weather code"""
    desc, icon_type = WEATHER_CODES.get(weather_code, ("Unknown", "cloudy"))
    
    if icon_type == "sunny":
        draw_sun(graphics, x, y, size)
    elif icon_type == "clear_night":
        # Moon - just a circle with dark bite
        graphics.set_pen(YELLOW)
        graphics.circle(x, y, size // 2)
        graphics.set_pen(BLACK)
        graphics.circle(x + size // 4, y - size // 6, size // 3)
    elif icon_type in ("partly_cloudy", "cloudy_night"):
        draw_sun(graphics, x - size // 4, y - size // 4, size // 2)
        draw_cloud(graphics, x + size // 6, y + size // 6, size // 2)
    elif icon_type in ("cloudy", "overcast"):
        draw_cloud(graphics, x, y, size)
    elif icon_type == "rain_light":
        draw_cloud(graphics, x, y - size // 4, size)
        draw_rain(graphics, x, y, size, heavy=False)
    elif icon_type == "rain_heavy":
        draw_cloud(graphics, x, y - size // 4, size)
        draw_rain(graphics, x, y, size, heavy=True)
    elif icon_type == "drizzle":
        draw_cloud(graphics, x, y - size // 4, size)
        draw_rain(graphics, x, y, size, heavy=False)
    elif icon_type in ("snow_light", "snow_heavy"):
        draw_cloud(graphics, x, y - size // 4, size)
        draw_snow(graphics, x, y, size)
    elif icon_type == "sleet":
        draw_cloud(graphics, x, y - size // 4, size)
        draw_rain(graphics, x, y - 5, size // 2, heavy=False)
        draw_snow(graphics, x, y + 10, size // 2)
    elif icon_type == "hail":
        draw_cloud(graphics, x, y - size // 4, size)
        graphics.set_pen(WHITE)
        for i in range(3):
            dx = x - size // 3 + (i * size // 3)
            graphics.circle(dx, y + size // 3, 3)
    elif icon_type == "thunder":
        draw_cloud(graphics, x, y - size // 4, size)
        draw_thunder(graphics, x, y + size // 4, size // 2)
        draw_rain(graphics, x, y, size, heavy=True)
    elif icon_type in ("mist", "fog"):
        draw_mist(graphics, x, y, size)
    else:
        # Default: question mark
        graphics.set_pen(WHITE)
        graphics.text("?", x - 8, y - 10, scale=3)


# =============================================================================
# MET OFFICE API FUNCTIONS
# =============================================================================

def fetch_daily_forecast():
    """
    Fetch 7-day daily forecast from Met Office DataHub API
    Returns list of daily forecast dictionaries
    """
    # Met Office DataHub Global Spot Daily API endpoint
    url = f"https://data.hub.api.metoffice.gov.uk/sitespecific/v0/point/daily?latitude={LATITUDE}&longitude={LONGITUDE}"
    
    headers = {
        "apikey": MET_OFFICE_API_KEY,
        "accept": "application/json"
    }
    
    print(f"Fetching weather for {LOCATION_NAME} ({LATITUDE}, {LONGITUDE})...")
    add_error_detail("Daily endpoint", url)
    
    try:
        gc.collect()  # Free up memory before request
        response = urequests.get(url, headers=headers)
        add_error_detail("Daily HTTP status", response.status_code)
        
        if response.status_code == 200:
            data = response.json()
            response.close()
            gc.collect()
            forecasts = parse_daily_forecast(data)
            if not forecasts:
                add_error_detail("Daily result", "No usable daily forecasts parsed")
            return forecasts
        else:
            print(f"API Error: {response.status_code}")
            add_error_detail("Daily response", safe_response_snippet(response))
            response.close()
            return None
            
    except Exception as e:
        print(f"Request failed: {e}")
        add_error_detail("Daily exception", f"{get_exception_name(e)}: {e}")
        return None


def get_today_date_str():
    """Get today's UK-local date as YYYY-MM-DD string."""
    t = uk_local_now()
    return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"


def parse_daily_forecast(data):
    """
    Parse the Met Office API response into a simpler format
    Returns list of dicts with keys: date, day_temp, night_temp, weather_code, 
    rain_prob, description
    """
    forecasts = []
    today = get_today_date_str()
    print(f"Today's date: {today}")
    
    try:
        # The API returns GeoJSON format
        features = data.get("features", [])
        if not features:
            print("No forecast features found")
            add_error_detail("Daily parse", "No features in API response")
            return None
        
        properties = features[0].get("properties", {})
        time_series = properties.get("timeSeries", [])
        add_error_detail("Daily timeSeries items", len(time_series))
        
        # Process each day, skipping past dates
        day_count = 0
        i = 0
        
        while i < len(time_series) and day_count < 7:
            entry = time_series[i]
            
            # Get the date from the time field
            time_str = entry.get("time", "")
            date_str = time_str[:10] if time_str else "Unknown"
            
            # Skip past dates - only include today and future
            if date_str < today:
                print(f"Skipping past date: {date_str}")
                i += 1
                continue
            
            # Daily data includes separate day and night values
            day_max_temp = entry.get("dayMaxScreenTemperature")
            night_min_temp = entry.get("nightMinScreenTemperature")
            
            # Weather type (significant weather code)
            weather_code = entry.get("daySignificantWeatherCode", 7)
            
            # Precipitation probability
            rain_prob_day = entry.get("dayProbabilityOfPrecipitation", 0)
            
            # Get weather description
            desc, _ = WEATHER_CODES.get(weather_code, ("Cloudy", "cloudy"))
            
            forecast = {
                "date": date_str,
                "day_temp": day_max_temp,
                "night_temp": night_min_temp,
                "weather_code": weather_code,
                "rain_prob": rain_prob_day,
                "description": desc
            }
            
            forecasts.append(forecast)
            day_count += 1
            i += 1
        
        if not forecasts:
            add_error_detail("Daily parse", f"No forecasts on or after {today}")

        return forecasts

    except Exception as e:
        print(f"Error parsing forecast: {e}")
        add_error_detail("Daily parse exception", f"{get_exception_name(e)}: {e}")
        return None


def fetch_hourly_forecast():
    """
    Fetch hourly forecast from Met Office DataHub API
    Returns tuple of (hourly_data, day_label, target_date)
    """
    url = f"https://data.hub.api.metoffice.gov.uk/sitespecific/v0/point/hourly?latitude={LATITUDE}&longitude={LONGITUDE}"

    headers = {
        "apikey": MET_OFFICE_API_KEY,
        "accept": "application/json"
    }

    print(f"Fetching hourly weather for {LOCATION_NAME}...")
    add_error_detail("Hourly endpoint", url)

    try:
        gc.collect()
        response = urequests.get(url, headers=headers)
        add_error_detail("Hourly HTTP status", response.status_code)

        if response.status_code == 200:
            data = response.json()
            response.close()
            gc.collect()
            hourly_data, day_label, target_date = parse_hourly_forecast(data)
            if not hourly_data:
                add_error_detail("Hourly result", "No usable hourly forecasts parsed")
            return hourly_data, day_label, target_date
        else:
            print(f"API Error: {response.status_code}")
            add_error_detail("Hourly response", safe_response_snippet(response))
            response.close()
            return None, None, None

    except Exception as e:
        print(f"Request failed: {e}")
        add_error_detail("Hourly exception", f"{get_exception_name(e)}: {e}")
        return None, None, None


def fetch_observations():
    """
    Fetch hourly observations from Met Office DataHub Land Observations API.
    Returns list of observation dictionaries for past 48 hours.
    """
    url = f"https://data.hub.api.metoffice.gov.uk/observation-land/1/{OBSERVATION_GEOHASH}"

    headers = {
        "apikey": MET_OFFICE_OBS_KEY,
        "accept": "application/json"
    }

    print(f"Fetching observations for station {OBSERVATION_GEOHASH}...")
    add_error_detail("Observations endpoint", url)

    try:
        gc.collect()
        response = urequests.get(url, headers=headers)
        add_error_detail("Observations HTTP status", response.status_code)

        if response.status_code == 200:
            data = response.json()
            response.close()
            gc.collect()
            return data
        else:
            print(f"Observations API Error: {response.status_code}")
            add_error_detail("Observations response", safe_response_snippet(response))
            response.close()
            return None

    except Exception as e:
        print(f"Observations request failed: {e}")
        add_error_detail("Observations exception", f"{get_exception_name(e)}: {e}")
        return None


def get_target_date():
    """
    Get the target UK-local date for the meteogram.
    Returns today if before 18:00 local, tomorrow if after.
    Also returns a label string.
    """
    t = uk_local_now()
    current_hour = t[3]

    if current_hour < 18:
        date_str = f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"
        label = "Today"
    else:
        tomorrow = time.localtime(time.mktime(tuple(t)) + 86400)
        date_str = f"{tomorrow[0]:04d}-{tomorrow[1]:02d}-{tomorrow[2]:02d}"
        label = "Tomorrow"

    return date_str, label


def parse_hourly_forecast(data):
    """
    Parse hourly API response, extracting 08:00-18:00 for target day.
    Returns list of dicts with: time, temp, weather_code, rain_prob, wind_speed, wind_dir
    Also returns target_date for use in backfilling.
    """
    forecasts = []
    target_date, day_label = get_target_date()
    print(f"Extracting hourly data for {day_label} ({target_date}), 08:00-18:00")
    add_error_detail("Hourly target", f"{day_label} {target_date} 08:00-18:00")

    try:
        features = data.get("features", [])
        if not features:
            print("No forecast features found")
            add_error_detail("Hourly parse", "No features in API response")
            return None, None, None

        properties = features[0].get("properties", {})
        time_series = properties.get("timeSeries", [])
        add_error_detail("Hourly timeSeries items", len(time_series))

        for entry in time_series:
            time_str = entry.get("time", "")
            if not time_str:
                continue

            # API timestamps are UTC (e.g. 2024-12-27T08:00Z); convert to UK
            # local so the 08:00-18:00 window matches the user's wall clock.
            entry_date, entry_hour = utc_iso_to_uk_local(time_str)
            if entry_date is None:
                continue

            if entry_date == target_date and 8 <= entry_hour <= 18:
                forecast = {
                    "hour": entry_hour,
                    "temp": entry.get("screenTemperature"),
                    "weather_code": entry.get("significantWeatherCode", 7),
                    "rain_prob": entry.get("probOfPrecipitation", 0),
                    "wind_speed": entry.get("windSpeed10m"),
                    "wind_gust": entry.get("windGustSpeed10m"),
                    "wind_dir": entry.get("windDirectionFrom10m"),
                    "feels_like": entry.get("feelsLikeTemperature"),
                    "humidity": entry.get("screenRelativeHumidity"),
                    "uv_index": entry.get("uvIndex"),
                }
                forecasts.append(forecast)

        add_error_detail("Hourly matched items", len(forecasts))
        if not forecasts:
            add_error_detail("Hourly parse", "No entries matched target date/hour window")

        return forecasts, day_label, target_date

    except Exception as e:
        print(f"Error parsing hourly forecast: {e}")
        add_error_detail("Hourly parse exception", f"{get_exception_name(e)}: {e}")
        return None, None, None


def backfill_from_observations(forecasts, observations, target_date):
    """
    Backfill missing hours (08:00 to first forecast hour) from observations.
    """
    if not forecasts or not observations:
        return forecasts

    first_forecast_hour = forecasts[0]["hour"]

    # Build dict of observations by hour for target date (UK local)
    obs_by_hour = {}
    for obs in observations:
        dt = obs.get("datetime", "")
        if not dt:
            continue
        obs_date, obs_hour = utc_iso_to_uk_local(dt)
        if obs_date is None:
            continue
        if obs_date == target_date and 8 <= obs_hour < first_forecast_hour:
            obs_by_hour[obs_hour] = obs

    # Create backfill entries
    backfill = []
    for hour in range(8, first_forecast_hour):
        if hour in obs_by_hour:
            obs = obs_by_hour[hour]
            entry = {
                "hour": hour,
                "temp": obs.get("temperature"),
                "weather_code": obs.get("weather_code", 7),
                "rain_prob": None,  # Observations don't have rain probability
                "wind_speed": obs.get("wind_speed"),
                "wind_gust": obs.get("wind_gust"),
                "wind_dir": obs.get("wind_direction"),
                "feels_like": None,
                "humidity": obs.get("humidity"),
                "uv_index": None,
            }
            backfill.append(entry)
            print(f"  Backfilled {hour}:00 from observations: {obs.get('temperature')}C")
        else:
            print(f"  No observation data for {hour}:00")

    # Prepend backfill to forecasts
    return backfill + forecasts


# =============================================================================
# DISPLAY FUNCTIONS
# =============================================================================

def get_day_name(date_str):
    """Convert a YYYY-MM-DD string to a short day name."""
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    try:
        year = int(date_str[0:4])
        month = int(date_str[5:7])
        day = int(date_str[8:10])
        return days[weekday(year, month, day)]
    except:
        return "???"


def draw_header(graphics, location, update_time):
    """Draw the header with location and update time"""
    # Background bar
    graphics.set_pen(BLUE)
    graphics.rectangle(0, 0, WIDTH, 50)
    
    # Title
    graphics.set_pen(WHITE)
    graphics.set_font("bitmap8")
    graphics.text(f"Weather: {location}", 10, 15, scale=3)
    
    # Update time
    graphics.text(f"Updated: {update_time}", WIDTH - 250, 18, scale=2)


def draw_day_column(graphics, x, width, forecast, is_today=False):
    """Draw a single day's forecast in a column"""
    y_start = 60
    col_height = HEIGHT - y_start - 10
    
    # Background for today
    if is_today:
        graphics.set_pen(GREEN)
        graphics.rectangle(x, y_start, width, col_height)
        graphics.set_pen(BLACK)
    else:
        graphics.set_pen(BLACK)
    
    # Day name
    day_name = get_day_name(forecast["date"])
    if is_today:
        day_name = "Today"
    
    graphics.set_font("bitmap8")
    text_x = x + width // 2 - 20
    graphics.text(day_name, text_x, y_start + 10, scale=2)
    
    # Date
    date_short = forecast["date"][5:10]  # MM-DD
    graphics.text(date_short, text_x - 5, y_start + 35, scale=1)
    
    # Weather icon
    icon_y = y_start + 100
    draw_weather_icon(graphics, x + width // 2, icon_y, forecast["weather_code"], size=50)
    
    # Day temperature (high)
    day_temp = forecast.get("day_temp")
    if day_temp is not None:
        temp_str = f"{int(day_temp)}C"
        # Use RED for negative temperatures
        if day_temp < 0:
            graphics.set_pen(RED)
        else:
            graphics.set_pen(BLACK)
        graphics.text(temp_str, x + width // 2 - 20, y_start + 170, scale=3)
    
    # Night temperature (low)
    night_temp = forecast.get("night_temp")
    if night_temp is not None:
        temp_str = f"{int(night_temp)}C"
        # Use RED for negative temperatures
        if night_temp < 0:
            graphics.set_pen(RED)
        else:
            graphics.set_pen(BLUE)
        graphics.text(temp_str, x + width // 2 - 15, y_start + 210, scale=2)
    
    # Rain probability
    rain_prob = forecast.get("rain_prob", 0)
    if rain_prob is not None:
        graphics.set_pen(BLUE)
        graphics.text(f"{int(rain_prob)}%", x + width // 2 - 15, y_start + 250, scale=2)
        # Small rain icon
        if rain_prob > 30:
            draw_rain(graphics, x + width // 2, y_start + 290, size=20, heavy=(rain_prob > 60))
    
    # Weather description
    desc = forecast.get("description", "")[:10]  # Truncate long descriptions
    graphics.set_pen(BLACK)
    graphics.text(desc, x + 5, y_start + 320, scale=1)


def draw_legend(graphics):
    """Draw a legend at the bottom"""
    y = HEIGHT - 40
    graphics.set_pen(BLACK)
    graphics.set_font("bitmap8")

    # Temperature legend
    graphics.set_pen(BLACK)
    graphics.text("High", 10, y, scale=1)
    graphics.set_pen(BLUE)
    graphics.text("Low", 50, y, scale=1)
    graphics.set_pen(RED)
    graphics.text("= Below 0C", 85, y, scale=1)

    # Rain legend
    graphics.set_pen(BLUE)
    graphics.text("Rain %", 200, y, scale=1)

    # Navigation hint
    graphics.set_pen(BLACK)
    graphics.text("Press A for hourly meteogram", 350, y, scale=1)

    # Attribution (required by Met Office)
    graphics.text("Powered by Matt Orifice data", WIDTH - 200, y + 15, scale=1)


# =============================================================================
# METEOGRAM DISPLAY FUNCTIONS
# =============================================================================

def draw_meteogram(graphics, hourly_data, day_label):
    """Draw full-screen meteogram for 08:00-18:00"""
    import math

    # Clear screen
    graphics.set_pen(WHITE)
    graphics.clear()

    # Layout constants
    MARGIN_LEFT = 50      # Space for Y-axis labels
    MARGIN_RIGHT = 20
    MARGIN_TOP = 60       # Space for header
    MARGIN_BOTTOM = 80    # Space for time labels and legend

    GRAPH_LEFT = MARGIN_LEFT
    GRAPH_RIGHT = WIDTH - MARGIN_RIGHT
    GRAPH_TOP = MARGIN_TOP + 60     # Below icons row
    GRAPH_BOTTOM = HEIGHT - MARGIN_BOTTOM
    GRAPH_WIDTH = GRAPH_RIGHT - GRAPH_LEFT
    GRAPH_HEIGHT = GRAPH_BOTTOM - GRAPH_TOP

    # Get current UK-local time for header
    try:
        t = uk_local_now()
        update_time = f"{t[3]:02d}:{t[4]:02d}"
    except:
        update_time = "--:--"

    # Draw header
    graphics.set_pen(BLUE)
    graphics.rectangle(0, 0, WIDTH, 50)
    graphics.set_pen(WHITE)
    graphics.set_font("bitmap8")
    graphics.text(f"{LOCATION_NAME} - {day_label} 08:00-18:00", 10, 15, scale=3)
    graphics.text(f"Updated: {update_time}", WIDTH - 250, 18, scale=2)

    if not hourly_data or len(hourly_data) == 0:
        graphics.set_pen(BLACK)
        graphics.text("No hourly data available", 250, 230, scale=2)
        graphics.update()
        return

    # Extract data arrays
    hours = [h["hour"] for h in hourly_data]
    temps = [h["temp"] for h in hourly_data if h["temp"] is not None]
    rain_probs = [h.get("rain_prob", 0) or 0 for h in hourly_data]

    if not temps:
        graphics.set_pen(BLACK)
        graphics.text("No temperature data", 250, 230, scale=2)
        graphics.update()
        return

    # Calculate temperature range with padding
    temp_min = min(temps)
    temp_max = max(temps)
    temp_range = temp_max - temp_min
    if temp_range < 5:
        temp_range = 5
        temp_min = (temp_max + temp_min) / 2 - 2.5
        temp_max = temp_min + 5
    temp_padding = temp_range * 0.15
    temp_min -= temp_padding
    temp_max += temp_padding

    # Helper function to map temperature to Y coordinate
    def temp_to_y(temp):
        if temp is None:
            return GRAPH_BOTTOM
        ratio = (temp - temp_min) / (temp_max - temp_min)
        return int(GRAPH_BOTTOM - ratio * GRAPH_HEIGHT)

    # Helper function to map hour index to X coordinate
    num_points = len(hourly_data)
    def hour_to_x(idx):
        return int(GRAPH_LEFT + (idx * GRAPH_WIDTH) / (num_points - 1)) if num_points > 1 else GRAPH_LEFT

    # Draw weather icons row (below header, above graph)
    icon_y = MARGIN_TOP + 30
    for i, h in enumerate(hourly_data):
        x = hour_to_x(i)
        # Draw icons at regular intervals (every 2 hours to avoid crowding)
        if i % 2 == 0 or num_points <= 6:
            draw_weather_icon(graphics, x, icon_y, h["weather_code"], size=35)

    # Draw graph background and grid
    graphics.set_pen(WHITE)
    graphics.rectangle(GRAPH_LEFT, GRAPH_TOP, GRAPH_WIDTH, GRAPH_HEIGHT)

    # Draw horizontal grid lines and Y-axis labels
    graphics.set_font("bitmap8")
    num_grid_lines = 5
    for i in range(num_grid_lines + 1):
        y = GRAPH_TOP + int(i * GRAPH_HEIGHT / num_grid_lines)
        temp_val = temp_max - (i * (temp_max - temp_min) / num_grid_lines)

        # Grid line (light)
        graphics.set_pen(BLACK)
        for x in range(GRAPH_LEFT, GRAPH_RIGHT, 8):
            graphics.pixel(x, y)

        # Y-axis label
        graphics.set_pen(BLACK)
        graphics.text(f"{int(temp_val)}C", 5, y - 4, scale=2)

    # Draw vertical grid lines
    for i, h in enumerate(hourly_data):
        x = hour_to_x(i)
        for y in range(GRAPH_TOP, GRAPH_BOTTOM, 8):
            graphics.pixel(x, y)

    # Draw precipitation bars at bottom of graph
    bar_height_max = 40
    for i, h in enumerate(hourly_data):
        x = hour_to_x(i)
        rain_prob = h.get("rain_prob", 0) or 0
        if rain_prob > 0:
            bar_height = int((rain_prob / 100) * bar_height_max)
            graphics.set_pen(BLUE)
            bar_width = max(GRAPH_WIDTH // num_points - 4, 8)
            graphics.rectangle(x - bar_width // 2, GRAPH_BOTTOM - bar_height, bar_width, bar_height)

    # Draw temperature line (thick, using multiple lines)
    graphics.set_pen(RED)
    for i in range(len(hourly_data) - 1):
        x1 = hour_to_x(i)
        y1 = temp_to_y(hourly_data[i]["temp"])
        x2 = hour_to_x(i + 1)
        y2 = temp_to_y(hourly_data[i + 1]["temp"])
        # Draw thick line
        for offset in range(-2, 3):
            graphics.line(x1, y1 + offset, x2, y2 + offset)

    # Draw temperature points with values
    for i, h in enumerate(hourly_data):
        x = hour_to_x(i)
        temp = h["temp"]
        if temp is not None:
            y = temp_to_y(temp)
            # Draw point
            graphics.set_pen(RED)
            graphics.circle(x, y, 5)
            graphics.set_pen(WHITE)
            graphics.circle(x, y, 3)
            # Draw temperature value above point (every other to avoid crowding)
            if i % 2 == 0 or num_points <= 6:
                graphics.set_pen(BLACK)
                graphics.text(f"{int(temp)}", x - 8, y - 20, scale=2)

    # Draw time labels on X-axis
    graphics.set_pen(BLACK)
    for i, h in enumerate(hourly_data):
        x = hour_to_x(i)
        if i % 2 == 0 or num_points <= 6:
            graphics.text(f"{h['hour']:02d}", x - 8, GRAPH_BOTTOM + 5, scale=2)

    # Draw axis lines
    graphics.set_pen(BLACK)
    graphics.line(GRAPH_LEFT, GRAPH_TOP, GRAPH_LEFT, GRAPH_BOTTOM)  # Y-axis
    graphics.line(GRAPH_LEFT, GRAPH_BOTTOM, GRAPH_RIGHT, GRAPH_BOTTOM)  # X-axis

    # Draw legend at bottom
    legend_y = HEIGHT - 35
    graphics.set_pen(RED)
    graphics.line(10, legend_y + 5, 30, legend_y + 5)
    graphics.line(10, legend_y + 6, 30, legend_y + 6)
    graphics.set_pen(BLACK)
    graphics.text("Temp", 35, legend_y, scale=1)

    graphics.set_pen(BLUE)
    graphics.rectangle(100, legend_y, 20, 12)
    graphics.set_pen(BLACK)
    graphics.text("Rain %", 125, legend_y, scale=1)

    graphics.text("Press A for 7-day forecast", WIDTH - 250, legend_y, scale=1)
    graphics.text("Powered by Matt Office", WIDTH - 250, legend_y + 15, scale=1)

    # Update display
    print("Updating meteogram display...")
    graphics.update()
    print("Meteogram display updated!")


def draw_weather_display(graphics, forecasts):
    """Draw the complete weather display"""
    # Clear screen
    graphics.set_pen(WHITE)
    graphics.clear()
    
    # Get current UK-local time for header
    try:
        t = uk_local_now()
        update_time = f"{t[3]:02d}:{t[4]:02d}"
    except:
        update_time = "--:--"
    
    # Draw header
    draw_header(graphics, LOCATION_NAME, update_time)
    
    # Calculate column width for 7 days
    num_days = min(len(forecasts), 7)
    col_width = WIDTH // num_days
    
    # Draw each day
    for i, forecast in enumerate(forecasts[:7]):
        x = i * col_width
        is_today = (i == 0)
        draw_day_column(graphics, x, col_width, forecast, is_today)
        
        # Draw column separator
        if i > 0:
            graphics.set_pen(BLACK)
            graphics.line(x, 60, x, HEIGHT - 50)
    
    # Draw legend
    draw_legend(graphics)
    
    # Update the display
    print("Updating display...")
    graphics.update()
    print("Display updated!")


def draw_error_screen(graphics, message):
    """Draw a weather-specific error screen using shared housekeeping UI."""
    housekeeping.draw_error_screen(
        graphics,
        message,
        WIDTH,
        HEIGHT,
        details=housekeeping.get_error_details(),
        title="Weather Display Error",
        checks_text="WiFi credentials, API keys/subscriptions, quota, endpoint access, internet",
    )


# =============================================================================
# MAIN PROGRAM
# =============================================================================

# Screen modes
SCREEN_METEOGRAM = 0
SCREEN_DAILY = 1


def record_runtime_context(screen_mode):
    """Capture context that helps diagnose failures on the device screen."""
    add_error_detail("Location", f"{LOCATION_NAME} ({LATITUDE}, {LONGITUDE})")
    add_error_detail("Screen", "daily forecast" if screen_mode == SCREEN_DAILY else "hourly meteogram")
    add_error_detail("Forecast API key present", bool(MET_OFFICE_API_KEY))
    add_error_detail("Observation API key present", bool(MET_OFFICE_OBS_KEY))
    try:
        t = uk_local_now()
        add_error_detail("Device time", f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}")
    except Exception as e:
        add_error_detail("Device time exception", f"{get_exception_name(e)}: {e}")


def fetch_hourly_with_backfill():
    """Fetch hourly forecast, backfilling from observations if needed"""
    hourly_data, day_label, target_date = fetch_hourly_forecast()

    # Check if we need to backfill from observations
    if hourly_data and len(hourly_data) > 0:
        first_hour = hourly_data[0]["hour"]
        if first_hour > 8:
            print(f"Forecast starts at {first_hour}:00, fetching observations to backfill...")
            observations = fetch_observations()
            if observations:
                hourly_data = backfill_from_observations(hourly_data, observations, target_date)
            else:
                print("Could not fetch observations for backfill")

    return hourly_data, day_label


def main():
    """Main program entry point"""
    print("=" * 50)
    print("Inky Frame Weather Display")
    print("Meteogram + 7-day forecast")
    print("=" * 50)

    # Initialize display
    graphics = PicoGraphics(DISPLAY)
    graphics.set_font("bitmap8")

    # Determine which screen to show first (before fetching data)
    # Default is meteogram, but if button A woke us, show daily
    if inky_frame.woken_by_button() and inky_frame.button_a.is_pressed:
        screen_mode = SCREEN_DAILY
        print("Button A pressed - showing daily forecast")
    else:
        screen_mode = SCREEN_METEOGRAM
        print("Showing meteogram")

    clear_error_details()
    housekeeping.pcf_to_pico_rtc()
    record_runtime_context(screen_mode)
    rtc_needs_sync = not rtc_date_is_valid()
    add_error_detail("RTC date valid", not rtc_needs_sync)

    # Connect to WiFi
    if not connect_wifi(WIFI_SSID, WIFI_PASSWORD) and not connect_wifi(ALT_SSID, ALT_PASSWORD):
        draw_error_screen(graphics, "WiFi connection failed")
        return
    clear_error_details()
    record_runtime_context(screen_mode)
    try:
        add_error_detail("WiFi IP", housekeeping.get_wifi_ip())
    except Exception as e:
        add_error_detail("WiFi IP exception", f"{get_exception_name(e)}: {e}")

    if rtc_needs_sync and not sync_time_if_needed():
        disconnect_wifi()
        draw_error_screen(graphics, "Failed to sync device time")
        return

    # Fetch only the data needed for the selected screen
    hourly_data = None
    day_label = None
    daily_data = None

    if screen_mode == SCREEN_METEOGRAM:
        hourly_data, day_label = fetch_hourly_with_backfill()
    else:
        daily_data = fetch_daily_forecast()

    # Disconnect WiFi to save power
    disconnect_wifi()

    # Display the screen
    if screen_mode == SCREEN_METEOGRAM and hourly_data:
        draw_meteogram(graphics, hourly_data, day_label)
        print("Meteogram display complete!")
    elif screen_mode == SCREEN_DAILY and daily_data:
        draw_weather_display(graphics, daily_data)
        print("Daily forecast display complete!")
    else:
        draw_error_screen(graphics, "Failed to fetch weather data")

    # Clear any button presses
    housekeeping.clear_button_leds()

    # Go to sleep, wake on button press or after 3 hours
    print("Going to sleep (wake on button or 3 hours)...")
    housekeeping.sleep_for(180)


# Run the main program
if __name__ == "__main__":
    main()
