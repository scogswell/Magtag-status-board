# MagTag Status Board Display.  Use with Adafruit IO to make a notice sign you
# can update from remote.
#
# Steven Cogswell 2023
#
# Set `USE_NEOPIXEL_STATUS = False` in `code.py` have Neopixels off during
# status updates (less intrusive)
#
# SLEEP_TIME (seconds) is the time to sleep between feed checks
# SLEEP_TIME_OFFHOURS (seconds) is the time to sleep between feed checks
#    if the hour of the time is outside the range WORKING_HOURS_START and
#    WORKING_HOURS_END.  More sleep == more battery life
#
# This gets the time from Adafruit IO so make sure your time zone is set
# in secrets.py. Easier than figuring out NTP time zones.
#
# This uses the Alarm Memory on the ESP32S2 to store the value of the feed
# from the previous run since it persists across deep sleep cycles. If the
# feed value has not changed it won't refresh the e-ink display. If you reset
# the controller this will clear the sleep memory and automatically make it
# refresh.
#
# Most errors with Wifi and Adafruit IO should get caught and make the MagTag
# reboot so no manual intervention in the case of errors should be needed.
#
# Fonts are pre-generated at sizes 12,16,18,24,36,48,72,84,96.  When the display
# refreshes if tries to find the biggest font that fits on the screen with word
# wrapping to keep the display as big as possible and maintain quality on the
# e-ink (no scaled fonts).  Note that in the .pcf files I did not convert the
# entire font characterset so you may find some symbols and unicode characters
# are missing.  If you want them you can re-generate the fonts.

import ssl
import wifi
import socketpool
import adafruit_requests as requests
import secrets
from adafruit_io.adafruit_io import IO_HTTP
from adafruit_magtag.magtag import MagTag
import time
import terminalio
from adafruit_display_text import label, wrap_text_to_pixels
from adafruit_bitmap_font import bitmap_font
import alarm
import microcontroller
import espidf
import wifi_select
import rtc

DEBUG = True
SCALE_TEXT = 1
SLEEP_MEMORY_LOCATION=0
SLEEP_TIME = 2*60   # in seconds
SLEEP_TIME_OFFHOURS = 60*60*1 # in seconds
WORKING_HOURS_START=7
WORKING_HOURS_END=18
USE_NEOPIXEL_STATUS = False
IO_FEED_NAME = "status"

def magtag_message(s):
    """ Quick helper function to show error messages on the MagTag screen"""
    s += "\nRebooting..."
    M_SCALE_TEXT = 2
    font = terminalio.FONT
    M_WRAP_WIDTH = magtag.display.width/M_SCALE_TEXT
    message_label = label.Label(font=font,scale=M_SCALE_TEXT,color=0x000000,line_spacing=1.0)
    message_label.anchor_point=(0,0)
    message_label.anchored_position=(0,0)
    message_label.text = "\n".join(wrap_text_to_pixels(s, M_WRAP_WIDTH,font))
    magtag.splash.append(message_label)
    magtag.display.refresh()

def time_json_to_tuple(x):
    """
    Converts the Adafruit IO JSON time response from struct into a tuple suitable for
    setting the time with
    """
    # https://io.adafruit.com/services/time
    # Adafruit IO time JSON format:
    # {
    #   "year": 2019,
    #   "mon": 12,
    #   "mday": 2,
    #   "hour": 18,
    #   "min": 20,
    #   "sec": 37,
    #   "wday": 3,
    #   "yday": 336,
    #   "isdst": 0
    # }
    # Tuple for time.localtime():
    # Sequence of time info: (tm_year, tm_mon, tm_mday, tm_hour, tm_min, tm_sec, tm_wday, tm_yday, tm_isdst)
    t = (x["year"],x["mon"],x["mday"],x["hour"],x["min"],x["sec"],x["wday"],x["yday"],x["isdst"])
    return t

def format_datetime(datetime):
    """
    Simple pretty-print for a datetime object
    """
    if datetime.tm_hour > 12:
        ampm_hour = datetime.tm_hour - 12
        ampm_text = "PM"
    else:
        ampm_hour = datetime.tm_hour
        ampm_text = "AM"
    return "{:02}/{:02}/{} {:02}:{:02}:{:02} {}".format(
        datetime.tm_mon,
        datetime.tm_mday,
        datetime.tm_year,
        ampm_hour,
        datetime.tm_min,
        datetime.tm_sec,
        ampm_text,
    )

def inside_working_hours(datetime):
    """
    Determine if it's during working hours (shorter sleep time) or
    outside working hours (longer sleep time)
    """
    if datetime.tm_hour >= WORKING_HOURS_START and datetime.tm_hour < WORKING_HOURS_END:
        return True
    else:
        return False

def set_neopixel(n, value):
    """
    Helper function for the neopixels which lets you disable them with a global bool
    """
    if USE_NEOPIXEL_STATUS:
        magtag.peripherals.neopixels[n]=value

magtag = MagTag()

# Damn those neopixels are bright.
magtag.peripherals.neopixels.brightness=0.05

# Precompiled fonts, from largest size to smallest.   The status message will
# try them in sequence until the status box fits on the screen.
theFonts = ['fonts/FreeSans-96.pcf','fonts/FreeSans-84.pcf','fonts/FreeSans-72.pcf',
            'fonts/FreeSans-48.pcf','fonts/FreeSans-36.pcf','fonts/FreeSans-24.pcf',
            'fonts/FreeSans-18.pcf','fonts/FreeSans-16.pcf','fonts/FreeSans-12.pcf']

# Light up neopixel to let us know if a status is in sleep memory.
if not alarm.wake_alarm:
    set_neopixel(0,(255,0,0))
else:
    set_neopixel(0,(0,255,0))

# Get secrets for wifi/adafruit io/etc.
try:
    from secrets import secrets as secrets_many
except ImportError:
    print("WiFi and Adafruit IO credentials are kept in secrets.py - please add them there!")
    magtag_message("WiFi and Adafruit IO credentials are kept in secrets.py - please add them there!")
    raise

# Find a wifi network in range that's listed in the secrets file
try:
    secrets = wifi_select.select_wifi_network(secrets_many)
except Exception as e:
    print("Error scanning for wifi networks",e)
    magtag_message("Error scanning for wifi networks")
    time.sleep(10)
    microcontroller.reset()

# Get our username, key and desired timezone
aio_username = secrets["aio_username"]
aio_key = secrets["aio_key"]
location = secrets.get("timezone", None)
RTC_URL = "https://io.adafruit.com/api/v2/%s/integrations/time/struct?x-aio-key=%s&tz=%s" % (aio_username, aio_key, location)

print("My MAC addr:", [hex(i) for i in wifi.radio.mac_address])

# Figure out if we're using Enterprise WiFi or regular WPA password Wifi
# Note that enterprise Wifi is a currently unreleased feature in private testing.
if 'username' in secrets:
    if wifi_select.enterprise_wifi_available():
        print("Changing enterprise to True")
        wifi.radio.enterprise = True
        wifi.radio.set_enterprise_id(identity=secrets['identity'],username=secrets['username'],password=secrets['password'])
    else:
        print("Cannot connect to Enterprise WiFi with this version of CircuitPython")
        magtag_message("This version of Circuitpython doesn't support WPA Enterprise")
        raise ConnectionError
else:
    if wifi_select.enterprise_wifi_available():
        print("Changing enterprise to False")
        wifi.radio.enterprise = False

# Connect to WiFi
set_neopixel(3,(0,0,255))
try:
    print("Connecting to {}".format(secrets["ssid"]))
    if wifi_select.enterprise_wifi_available() and wifi.radio.enterprise:
        wifi.radio.connect(secrets["ssid"],timeout=60)
    else:
        wifi.radio.connect(secrets["ssid"], secrets["password"])
    print("Connected to %s!" % secrets["ssid"])
    set_neopixel(3,(0,255,0))
# Wi-Fi connectivity fails with error messages, not specific errors, so this except is broad.
except Exception as e:  # pylint: disable=broad-except
    print("ESPIDF Heap caps free: ", espidf.heap_caps_get_free_size())
    print("ESPIDF largest block : ", espidf.heap_caps_get_largest_free_block())
    print("Failed to connect to WiFi. Error:", e, "\nBoard will hard reset in 10 seconds.")
    set_neopixel(3,(255,0,0))
    magtag_message("Can't connect to Wifi {}".format(secrets["ssid"]))
    time.sleep(10)
    microcontroller.reset()
print("ESPIDF Heap caps free: ", espidf.heap_caps_get_free_size())
print("ESPIDF largest block : ", espidf.heap_caps_get_largest_free_block())
print("Connected to %s "%secrets["ssid"])
print("My IP address is", wifi.radio.ipv4_address)
set_neopixel(3,(0,255,0))

pool = socketpool.SocketPool(wifi.radio)
requests = requests.Session(pool, ssl.create_default_context())

# Get the Time from Adafruit IO (make sure timezone is set correctly in secrets.py)
set_neopixel(2,(0,0,255))
try:
    rtc_response = requests.get(RTC_URL)
    rtc_time = rtc_response.json()
    rtc.RTC().datetime=time.struct_time(time_json_to_tuple(rtc_time))
except Exception as e:
    set_neopixel(2,(255,0,0))
    magtag_message("Error getting time from Adafruit IO")
    time.sleep(10)
    microcontroller.reset()
print("Time is ",format_datetime(time.localtime()))

set_neopixel(2,(0,255,0))

# Initialize an Adafruit IO HTTP API object. get the last entry from the "status" feed.
set_neopixel(1,(0,255,255))
try:
    io = IO_HTTP(aio_username, aio_key, requests)
    set_neopixel(1,(0,0,255))
    # Get the 'status' feed from Adafruit IO
    status_feed = io.get_feed(IO_FEED_NAME)
    received_data = io.receive_data(status_feed["key"])
except Exception as e:
    print("Failed to connect to Adafruit IO. Error:", e, "\nBoard will hard reset in 10 seconds.")
    magtag_message("Failed to connect to Adafruit IO.")
    set_neopixel(2,(255,0,0))
    time.sleep(10)
    microcontroller.reset()

print("Data from status feed:", received_data["value"])
set_neopixel(1,(0,255,0))
theStatus = received_data["value"]

# Get the old status message from the alarm sleep memory.  If it's the same
# we won't bother refreshing the e-ink display since it's distracting.
oldStatus = None
if not alarm.wake_alarm:
    print("Did not wake up from alarm")
else:
    print("Woke up from alarm. Sleep memory has",alarm.sleep_memory[SLEEP_MEMORY_LOCATION],"bytes stored")
    b=alarm.sleep_memory[SLEEP_MEMORY_LOCATION+1:SLEEP_MEMORY_LOCATION+1+alarm.sleep_memory[SLEEP_MEMORY_LOCATION]]
    print("Stored byte array is",b)
    oldStatus = ''.join([chr(x) for x in b])
    print("Old status is [{}]".format(oldStatus))

sleep_time_seconds = SLEEP_TIME
if inside_working_hours(time.localtime()):
    print("Sleeping short time",SLEEP_TIME)
    sleep_time_seconds = SLEEP_TIME
else:
    print("Sleeping Longer time",SLEEP_TIME_OFFHOURS)
    sleep_time_seconds = SLEEP_TIME_OFFHOURS

# If the status hasn't changed, do nothing just go back to sleep
if oldStatus is not None:
    if oldStatus == theStatus:
        print("Status has not changed")
        print("Sleeping for",sleep_time_seconds,"seconds")
        magtag.exit_and_deep_sleep(sleep_time_seconds)

# The status has changed, so write the new status into the alarm sleep memory
# This probably handles unprintable unicode correctly (bytes can be longer
# than the string length because of multi-byte characters like smart quotes)
b = theStatus.encode('utf-8')
alarm.sleep_memory[SLEEP_MEMORY_LOCATION]=len(b)
print("Stored",len(b),"bytes in sleep memory")
print("encoded is ",len(b)," length")
alarm.sleep_memory[SLEEP_MEMORY_LOCATION+1:SLEEP_MEMORY_LOCATION+1+len(b)]=b

# Label for time along the bottom of the screen
timeFont = terminalio.FONT
time_label = label.Label(font=timeFont,text=format_datetime(time.localtime()),color=0x000000,scale=1,line_spacing=1.0)
time_label.anchored_position = (magtag.display.width/2, magtag.display.height)
time_label.anchor_point = (0.5, 1.0)
time_height = time_label.bounding_box[3]

# Label for battery voltage display.
batt_text = ""
# Uncomment this line if you want the battery voltage shown
#batt_text = "{:.3f} v".format(magtag.peripherals.battery)
if magtag.peripherals.battery < 3.4:
    batt_text += " Battery Low"

# Uncomment this next block if you want to verify what length sleep is being done
# if inside_working_hours(time.localtime()):
#     batt_text += " short sleep"
# else:
#     batt_text += " long sleep"

battery_label = label.Label(font=timeFont,text=batt_text,color=0x000000,scale=1,line_spacing=1.0)
battery_label.anchored_position = (0,0)
battery_label.anchor_point = (0,0)

# Loop through the fonts we've pre-compiled and listed.  Start with the biggest and if the text from theStatus fits
# display it on screen.  Otherwise move to the next size (smaller) and try again.  Keep trying until we run out of
# fonts and just use the smallest one.  Using native font sizes looks much better on the e-ink than using
# label scales.
for f in theFonts:
    print("Trying font",f)
    font = bitmap_font.load_font(f)

    status_label = label.Label(font=font, text="?" * 30, color=0x000000,scale=SCALE_TEXT,line_spacing=1.0)
    status_label.anchored_position = (magtag.display.width/2, (magtag.display.height-time_height)/2)
    status_label.anchor_point = (0.5, 0.5)

    WRAP_WIDTH = magtag.display.width/SCALE_TEXT
    print("Width is",magtag.display.width,"Height is",magtag.display.height, "Scale Width is",WRAP_WIDTH, "Available Height is",magtag.display.height-time_height)

    status_label.text = "\n".join(wrap_text_to_pixels(theStatus, WRAP_WIDTH,font))
    # How big was that label we just made?
    dims = status_label.bounding_box
    print("Box fits in Width ",dims[2]*SCALE_TEXT," Height ",dims[3]*SCALE_TEXT)
    # If this box actually fits on the screen, let's use it
    if dims[2]*SCALE_TEXT < magtag.display.width and dims[3]*SCALE_TEXT < magtag.display.height-time_height:
        break
print("Found Font that fits screen")

# Display all those things we just made
magtag.splash.append(status_label)
magtag.splash.append(time_label)
magtag.splash.append(battery_label)
magtag.display.refresh()

# Go into deep sleep.  When it wakes up the program will start from the beginning with alarm
# memory preserved.
print("Sleeping for",sleep_time_seconds,"seconds")
magtag.exit_and_deep_sleep(sleep_time_seconds)