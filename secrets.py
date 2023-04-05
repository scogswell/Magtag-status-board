# SPDX-FileCopyrightText: 2020 Adafruit Industries
#
# SPDX-License-Identifier: Unlicense

# This file is where you keep secret settings, passwords, and tokens!
# If you put them in the code you risk committing that info or sharing it

# This works with the wifi_select.py functions.  You can put several wifi
# networks settings and wifi_select will pick the first one that's available.
# Nice if you have to move locations with your device.
secrets = []

secrets.append ({
    'ssid' : 'enterprise-wifi-1',
    'identity' : 'my-identity',
    'username' : 'my-username',
    'password' : 'my-password',
    'aio_username' : 'my-adafruit-io-username',
    'aio_key' : 'my-adafruit-iokey',
    'timezone' : "America/NewYork", # http://worldtimeapi.org/timezones
    })

secrets.append ({
    'ssid' : 'my-ssid',
    'password' : 'my-password',
    'aio_username' : 'my-adafruit-io-username',
    'aio_key' : 'my-adafruit-iokey',
    'timezone' : "America/NewYork", # http://worldtimeapi.org/timezones
    })

secrets.append ({
    'ssid' : 'my-ssid-2',
    'password' : 'my-password-2',
    'aio_username' : 'my-adafruit-io-username',
    'aio_key' : 'my-adafruit-iokey',
    'timezone' : "America/NewYork", # http://worldtimeapi.org/timezones
    })