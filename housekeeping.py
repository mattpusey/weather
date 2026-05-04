"""
Application-independent helpers for Inky Frame apps.

Keeps boot/runtime concerns out of the weather code:
- WiFi connect/disconnect
- RTC sanity checks and NTP sync
- UK local time conversion (the Pico RTC stores UTC)
- Error diagnostics collection
- Generic e-ink error screen rendering
"""

import time
import network
import inky_frame

from inky_frame import WHITE, BLACK, RED


LAST_ERROR_DETAILS = []


def clear_error_details():
    """Reset details collected for the next visible error screen."""
    global LAST_ERROR_DETAILS
    LAST_ERROR_DETAILS = []


def add_error_detail(label, value):
    """Record one short diagnostic line for the error screen and serial log."""
    if value is None:
        return

    try:
        value = str(value)
    except:
        value = "<unprintable>"

    detail = f"{label}: {value}"
    print(f"ERROR DETAIL - {detail}")
    LAST_ERROR_DETAILS.append(detail)


def get_error_details():
    """Return the currently collected diagnostic details."""
    return LAST_ERROR_DETAILS


def get_exception_name(error):
    """Return a MicroPython-friendly exception class name."""
    try:
        return error.__class__.__name__
    except:
        return "Exception"


def safe_response_snippet(response, max_chars=180):
    """Best-effort response body snippet without assuming full CPython APIs."""
    try:
        if hasattr(response, "text"):
            body = response.text
        elif hasattr(response, "content"):
            body = response.content
        else:
            return None
    except Exception as e:
        return f"<could not read body: {get_exception_name(e)} {e}>"

    try:
        if isinstance(body, bytes):
            body = body.decode("utf-8")
    except:
        body = str(body)

    body = str(body).replace("\n", " ").replace("\r", " ").strip()
    if len(body) > max_chars:
        body = body[:max_chars] + "..."
    return body


def connect_wifi(ssid, password):
    """Connect to WiFi network."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        print("Already connected to WiFi")
        return True

    print(f"Connecting to {ssid}...")
    wlan.connect(ssid, password)

    max_wait = 20
    while max_wait > 0:
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        max_wait -= 1
        print("Waiting for connection...")
        time.sleep(1)

    time.sleep(2)

    if wlan.status() >= 3:
        print(f"Connected! IP: {wlan.ifconfig()[0]}")
        return True

    print("Failed to connect to WiFi")
    add_error_detail("WiFi failed SSID", ssid)
    try:
        add_error_detail("WiFi status", wlan.status())
        add_error_detail("WiFi config", wlan.ifconfig())
    except Exception as e:
        add_error_detail("WiFi status exception", f"{get_exception_name(e)}: {e}")
    return False


def disconnect_wifi():
    """Disconnect from WiFi to save power."""
    wlan = network.WLAN(network.STA_IF)
    wlan.disconnect()
    wlan.active(False)


def get_wifi_ip():
    """Return the current WiFi IP address."""
    wlan = network.WLAN(network.STA_IF)
    return wlan.ifconfig()[0]


def pcf_to_pico_rtc():
    """Sync the Pico RTC from the Inky Frame RTC."""
    inky_frame.pcf_to_pico_rtc()


def clear_button_leds():
    """Turn off all Inky Frame button LEDs."""
    inky_frame.button_a.led_off()
    inky_frame.button_b.led_off()
    inky_frame.button_c.led_off()
    inky_frame.button_d.led_off()
    inky_frame.button_e.led_off()


def sleep_for(minutes):
    """Set an RTC alarm and cut power for the requested number of minutes."""
    inky_frame.sleep_for(minutes)


def rtc_date_is_valid(min_year=2024):
    """Return True when the Pico RTC has a plausible date."""
    try:
        t = time.localtime()
        return t[0] >= min_year
    except:
        return False


def sync_time_if_needed(min_year=2024):
    """Use NTP only when the RTC date is clearly wrong."""
    if rtc_date_is_valid(min_year):
        add_error_detail("RTC sync", "Skipped, date is valid")
        return True

    add_error_detail("RTC sync", "Date invalid, trying NTP")
    try:
        print("RTC date invalid, syncing time with NTP...")
        inky_frame.set_time()
        print("Time synced to Pico RTC and Inky RTC")
    except Exception as e:
        add_error_detail("NTP sync exception", f"{get_exception_name(e)}: {e}")
        return False

    if rtc_date_is_valid(min_year):
        try:
            t = time.localtime()
            add_error_detail("RTC synced time", f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}")
        except Exception as e:
            add_error_detail("RTC synced time exception", f"{get_exception_name(e)}: {e}")
        return True

    add_error_detail("RTC sync", "NTP completed but date still invalid")
    return False


def _weekday(year, month, day):
    """Day of week using Zeller's congruence (Monday=0 ... Sunday=6)."""
    y, m = year, month
    if m < 3:
        m += 12
        y -= 1
    k = y % 100
    j = y // 100
    h = (day + (13 * (m + 1)) // 5 + k + k // 4 + j // 4 - 2 * j) % 7
    return (h + 5) % 7


def _last_sunday_of_month(year, month):
    """Day-of-month of the last Sunday in the given month."""
    if month in (1, 3, 5, 7, 8, 10, 12):
        last_day = 31
    elif month in (4, 6, 9, 11):
        last_day = 30
    elif (year % 4 == 0 and year % 100 != 0) or year % 400 == 0:
        last_day = 29
    else:
        last_day = 28
    return last_day - ((_weekday(year, month, last_day) + 1) % 7)


def is_bst(utc_year, utc_month, utc_day, utc_hour):
    """Return True if the given UTC moment falls within British Summer Time.

    BST runs from 01:00 UTC on the last Sunday of March to 01:00 UTC on the
    last Sunday of October.
    """
    if utc_month < 3 or utc_month > 10:
        return False
    if 4 <= utc_month <= 9:
        return True
    transition_day = _last_sunday_of_month(utc_year, utc_month)
    if utc_month == 3:
        if utc_day != transition_day:
            return utc_day > transition_day
        return utc_hour >= 1
    if utc_day != transition_day:
        return utc_day < transition_day
    return utc_hour < 1


def utc_to_uk_local(utc_t):
    """Convert a UTC time tuple to UK local time, applying BST when active."""
    if not is_bst(utc_t[0], utc_t[1], utc_t[2], utc_t[3]):
        return utc_t
    return time.localtime(time.mktime(tuple(utc_t)) + 3600)


def uk_local_now():
    """Current UK local time tuple, derived from the device's (UTC) RTC."""
    return utc_to_uk_local(time.localtime())


def utc_iso_to_uk_local(time_str):
    """Parse 'YYYY-MM-DDTHH:MMZ' UTC and return (date_str, hour) in UK local."""
    try:
        y = int(time_str[0:4])
        mo = int(time_str[5:7])
        d = int(time_str[8:10])
        h = int(time_str[11:13])
    except (ValueError, IndexError):
        return None, None
    local = utc_to_uk_local((y, mo, d, h, 0, 0, 0, 0))
    return f"{local[0]:04d}-{local[1]:02d}-{local[2]:02d}", local[3]


def draw_wrapped_text(graphics, text, x, y, max_chars, scale=1, line_height=12, max_lines=None):
    """Draw wrapped bitmap text and return the next y position."""
    lines_drawn = 0
    words = str(text).split(" ")
    line = ""

    for word in words:
        while len(word) > max_chars:
            chunk = word[:max_chars]
            word = word[max_chars:]
            if line:
                graphics.text(line, x, y, scale=scale)
                y += line_height
                lines_drawn += 1
                line = ""
                if max_lines is not None and lines_drawn >= max_lines:
                    return y
            graphics.text(chunk, x, y, scale=scale)
            y += line_height
            lines_drawn += 1
            if max_lines is not None and lines_drawn >= max_lines:
                return y

        candidate = word if not line else line + " " + word
        if len(candidate) <= max_chars:
            line = candidate
        else:
            graphics.text(line, x, y, scale=scale)
            y += line_height
            lines_drawn += 1
            if max_lines is not None and lines_drawn >= max_lines:
                return y
            line = word

    if line and (max_lines is None or lines_drawn < max_lines):
        graphics.text(line, x, y, scale=scale)
        y += line_height

    return y


def draw_error_screen(graphics, message, width, height, details=None, title="Application Error", checks_text=None):
    """Draw an error message on screen."""
    graphics.set_pen(WHITE)
    graphics.clear()

    graphics.set_pen(RED)
    graphics.rectangle(0, 0, width, 50)

    graphics.set_pen(WHITE)
    graphics.set_font("bitmap8")
    graphics.text(title, 10, 15, scale=3)

    graphics.set_pen(BLACK)
    draw_wrapped_text(graphics, message, 20, 70, 38, scale=2, line_height=22, max_lines=2)

    y = 125
    graphics.text("Diagnostics:", 20, y, scale=2)
    y += 26

    if details:
        for detail in details:
            if y > height - 58:
                graphics.text("More details in serial output", 20, y, scale=1)
                y += 14
                break
            y = draw_wrapped_text(graphics, "- " + detail, 20, y, 92, scale=1, line_height=12, max_lines=3)
    else:
        graphics.text("- No extra diagnostics captured", 20, y, scale=1)
        y += 14

    if checks_text:
        graphics.text("Please check:", 20, height - 48, scale=1)
        graphics.text(checks_text, 20, height - 32, scale=1)

    graphics.update()
