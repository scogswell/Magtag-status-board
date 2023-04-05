import wifi

WIFI_SELECT_DEBUG=True

def enterprise_wifi_available():
    """
    Tests if (unreleased) Circuitpython flag to enable enterprise wifi is present in circuitpython
    otherwise just trying to access wifi.radio.enterprise will throw an exception.
    """
    avail = True
    try:
        # If your build of circuitpython does not have the enterprise flag, this will
        # throw an exception and be caught.
        x = wifi.radio.enterprise
    except AttributeError:
        avail = False
    return avail

def select_wifi_network(secrets_data):
    """
    from a list of secrets, look for an available wifi network in radio range and connect to it
    """
    wifi_networks = []
    if WIFI_SELECT_DEBUG:
        print("Wifi Networks Available:")
    for network in wifi.radio.start_scanning_networks():
        if WIFI_SELECT_DEBUG:
            print("\t%s\t\tRSSI: %d\tChannel: %d" % (str(network.ssid, "utf-8"),
                    network.rssi, network.channel))
        wifi_networks.append(network.ssid)
    wifi.radio.stop_scanning_networks()

    if WIFI_SELECT_DEBUG:
        print("\nFinding connection to use...")
    if isinstance(secrets_data, list):
        if WIFI_SELECT_DEBUG:
            print("Secrets is a list, searching list")
        secrets = None
        for n in secrets_data:
            if WIFI_SELECT_DEBUG:
                print("Checking",n['ssid'])
            if n['ssid'] in wifi_networks:
                if 'username' in n:
                    if enterprise_wifi_available():
                        if WIFI_SELECT_DEBUG:
                            print("Connecting to Enterprise",n['ssid'])
                        secrets = n
                        break
                    else:
                        if WIFI_SELECT_DEBUG:
                            print(n['ssid'],"is available but this version of Circuitpython does not support enterprise connections")
                else:
                    if WIFI_SELECT_DEBUG:
                        print("Connecting to",n['ssid'])
                    secrets = n
                    break
        if secrets is None:
            print("Could not find a WiFi network to connect to")
            raise ConnectionError
    else:
        if WIFI_SELECT_DEBUG:
            print("Secrets is not a list")
        if secrets_data['ssid'] in wifi_networks:
            if WIFI_SELECT_DEBUG:
                print("Connecting to",secrets_data['ssid'])
            return secrets_data

    return secrets
