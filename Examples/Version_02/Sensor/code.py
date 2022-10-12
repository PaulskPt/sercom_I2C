
# SPDX-FileCopyrightText: Copyright (c) 2022 Paulus Schulinck @PaulskPt
#
# SPDX-License-Identifier: MIT
#
# Serial communication via I2C (alias: 'Sercom I2C')
# This script is intendedc for the device with the 'Sensor' role,
# in my case an Unexpected Maker PROS3
# Version 2
#
import board
import time, gc, os
import sys
from busio import UART
from micropython import const
import pros3
from rtc import RTC
from digitalio import DigitalInOut
import ipaddress
import ssl
from adafruit_ntp import NTP_TO_UNIX_EPOCH, NTP
import socketpool
import time
import wifi
from collections import OrderedDict

sercom_I2C_version = 2.0

try:
    from secrets import secrets
except ImportError:
    print("WiFi secrets are kept in secrets.py, please add them there!")
    raise

_STX = const(0x02)  # Start-of-text ASCII code
_ACK = const(0x06)  # Acknowledge ASCII code

roles_dict = {
    0: 'Main',
    1: 'Sensor'
}

req_dict = {
   100: 'date_time',  # 100 dec = 64 hex
   101: 'unix_time',
   102: 'weather'
   }

# Buffers
rx_buffer_len = 2
rx_buffer = bytearray(rx_buffer_len * b'\x00')

""" Global flags """
# Global debug flag. Set it to true to receive more information to the REPL
my_debug = False
use_ntp = True
use_local_time = None

""" Pre-definitions of functions """
def dtstr_to_tpl():
    pass

# +-----------------------------------------------+
# | Create an instance of the UART object class   |
# +-----------------------------------------------+
# Important: the SDA and SCL wires have to be crossed:
# SDA (device with role Main) ===> SCL (device with role Sensor)
# SCL (device with role Main) ===> SDA (device with role Sensor)
# in other worde: cross-over type of connection
# equal to the RX/TX serial wiring.
uart = UART(board.SDA, board.SCL, baudrate=4800, timeout=0, receiver_buffer_size=rx_buffer_len)

""" Other global variables """
id = board.board_id
main_ads = 0x20
sensor_ads = 0x25
pool = None
ip = None
s_ip = '0.0.0.0'
ap_cnt = 0   # count of WiFi access points
ap_dict = {} # dictionary of WiFi access points
req_rcvd = 0
msg_nr = 0
rtc = None
rtc_is_set = False
default_tpl_dt = (2022,10,10,1,15,1,283,0,-1)  # type tuple
default_dt = time.struct_time((default_tpl_dt)) # type time.struct_time
default_s_dt = "2022-10-10 01:15:00"  # type str
epoch = None
clock = None
ntp = None
start = True
t_start = time.monotonic()
tz_offset = 0
tag_le_max = 25  # see tag_adj()

if not use_ntp:
    default_dt = time.struct_time((2022, 9, 17, 12, 0, 0, 5, 261, -1))
    default_s_dt = dtstr_to_tpl()

#time.sleep(5)

print()
my_WiFi_SSID = os.getenv("CIRCUITPY_WIFI_SSID")
if my_debug:
    print("my_env=", my_WiFi_SSID)

def do_scan():
    global ap_cnt, ap_dict
    TAG = tag_adj("do_scan(): ")
    for network in wifi.radio.start_scanning_networks():
        ap_dict[ap_cnt] = {"ap_nr": ap_cnt, "ssid": str(network.ssid, "utf-8"), "rssi": network.rssi, "channel": network.channel}
        ap_cnt += 1
    wifi.radio.stop_scanning_networks()
    if my_debug:
        print("ap_dict=", ap_dict)

def pr_scanned_ap(sort_order: int=0):
    TAG = tag_adj("pr_scanned_ap(): ")
    sort_dict = {0: 'ap_nr', 1: 'rssi', 2: 'channel'}
    le = len(sort_dict)
    n_max = le-1
    if sort_order >= 0 and sort_order <= n_max:
        sort_on = sort_dict[sort_order]
    else:
        s = "Value sort_order must be between 0 and {}".format(n_max)
        raise ValueError(s)
    print("\n"+TAG+"\nAvailable WiFi networks (sorted on: \'{}\')".format(sort_on))
    if len(ap_dict) > 0:
        if sort_on == 'ap_nr':
            od = OrderedDict(sorted(ap_dict.items(), key= lambda x: x[1]['ap_nr'], reverse=False))
            for k, v in od.items():
                s = "\tAP nr {:2d}\tSSID: {:30s}\tRSSI: {:d}\tChannel: {:2d}".format(v["ap_nr"], v["ssid"], v["rssi"], v["channel"])
                print(s)
        elif sort_on == 'rssi' or sort_on == 'channel':
            od = OrderedDict(sorted(ap_dict.items(), key= lambda x: x[1]['ap_nr'], reverse=False))  # results in TypeError: 'int' object is not iterable
            t_dict ={}
            for i in od.items():
                # print("od.item[i]=", i)
                if sort_on == 'rssi':
                    t_dict[i[0]] = str(i[1]['rssi'])
                elif sort_on == 'channel':
                    t_dict[i[0]] = "{:02d}".format(i[1]['channel'])
            if len(t_dict) > 0:
                # print("t_dict =", t_dict)
                od2 = OrderedDict(sorted(t_dict.items(), key= lambda x: x[1], reverse=False))
                for k, v in od2.items():
                    if sort_on == 'rssi':
                        s = "\tAP nr {:2d}\tSSID: {:30s}\tRSSI: {:s}\tChannel: {:2d}".format(k, ap_dict[k]["ssid"], v, ap_dict[k]["channel"])
                    elif sort_on == 'channel':
                        s = "\tAP nr {:2d}\tSSID: {:30s}\tRSSI: {:d}\tChannel: {:s}".format(k, ap_dict[k]["ssid"], ap_dict[k]["rssi"], v)
                    print(s)
        else:
            print("Sorting selection \'{}\' unknown".format(sort_on))
    else:
        print("Dictionary of scanned access points (ap_dict) is empty")

# Note: wifi.radio.hostname results in: 'UMPros3'
def do_connect():
    global ip, s_ip, start, pool
    TAG = tag_adj("do_connect(): ")
    print(TAG+"wifi.radio.enabled=", wifi.radio.enabled)
    cnt = 0
    timeout_cnt = 5
    dc_ip = None
    #s_ip = None

    if start:
        start = False
        if my_debug:
            do_scan()
            sort_order = 1  # <<<===  Choose here how you want to sort the received list of Available WiFi networks (range: 0 - 2)
            pr_scanned_ap(sort_order)
            gc.collect()

    # print(TAG+f"dc_ip= {dc_ip}. type(dc_ip)= {type(dc_ip)}")
    while dc_ip is None or dc_ip == '0.0.0.0':
        # print(TAG+f"cnt= {cnt}")
        try:
            wifi.radio.connect(secrets["ssid"], secrets["password"])
        except ConnectionError as e:
            if cnt == 0:
                print(TAG+"WiFi connection try: {:2d}. Error: \'{}\'\n\tTrying max {} times.".format(cnt+1, e, timeout_cnt))
        dc_ip = wifi.radio.ipv4_address
        pool = socketpool.SocketPool(wifi.radio)
        cnt += 1
        if cnt > timeout_cnt:
            print(TAG+"WiFi connection timed-out")
            break
        time.sleep(1)

    if dc_ip:
        ip = dc_ip
        s_ip = str(ip)

    if s_ip is not None and s_ip != '0.0.0.0':
        print(TAG+"s_ip= \'{}\'".format(s_ip))
        print(TAG+"connected to %s!"%secrets["ssid"])
        print(TAG+"IP address is", ip)

        addr_idx = 0
        addr_dict = {0:'LAN gateway', 1:'google.com'}

        info = pool.getaddrinfo(addr_dict[1], 80)
        addr = info[0][4][0]
        print(TAG+f"resolved {addr_dict[1][:-4]} as {addr}")
        ipv4 = ipaddress.ip_address(addr)

        for _ in range(10):
            result = wifi.radio.ping(ipv4)
            if result:
                print(TAG+f"Ping {addr}: {result*1000} ms")
                break
            else:
                print(TAG+"no response")
            time.sleep(0.5)
    elif s_ip == '0.0.0.0':
        print(TAG+f"s_ip= {s_ip}. Resetting this \'{wifi.radio.hostname}\' device...")
        time.sleep(2)  # wait a bit to show the user the message
        import microcontroller
        microcontroller.reset()

def wifi_is_connected():
    return True if s_ip is not None and s_ip != '0.0.0.0' else False

def get_epoch():
    return time.time()

"""
    dtstru_to_str()

    param: None
    return: str

    This function takes global var default_dt (type: time.struct_time)
    and converts it in to a 6-element string (yyyy-mm-dd hh:mm:ss)
"""
def dtstru_to_str():
    global default_dt
    TAG=tag_adj("dtstru_to_str(): ")
    ret = ""
    if isinstance(default_dt, time.struct_time):
        t = default_dt
        ret = "{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(t[0], t[1], t[2], t[3], t[4], t[5])
    else:
        print(TAG+f"default_dt needs to be type time.struct_time. It is of type: {type(default_dt)}")
        raise TypeError
    return ret

"""
    dtstr_to_tpl()

    param: None
    return: tuple

    This function takes global var default_s_dt (type: str)
    and converts it in to a 9-element tuple of integers

"""
def dtstr_to_tpl():
    global default_s_dt
    TAG=tag_adj("dtstr_to_tpl(): ")
    ret = ()
    if isinstance(default_s_dt, str):
        s = default_s_dt
        le = len(s)
        if le > 0 and le <= 19:
            try:
                # string in form 'yyyy-mm-dd hh:mm:ss'
                #ret= (yy,         mo,          dd,           hh,            mi,            ss,         wd, yd, isdst)
                ret = (int(s[:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]), int(s[17:]), 0, 0, -1 )
            except ValueError as e:
                print(TAG+f"Error = {e}")
                raise
    else:
        print(TAG+f"default_s_dt needs to be type str. It is of type: {type(default_s_dt)}")
        raise TypeError
    return ret  # tuple

"""
    Function set_dt_globls()

    :param  time.struct_time
    :return None

    This function uses the parameter dt to set the global datetime formats
    by setting global variables:
       - default_dt      directly by: default_dt = dt
       - default_s_dt    by calling dtstru_to_str()
       - default_tpl_dt  by calling dtstr_to_tpl()

    If the type of parameter dt is not of type time.struct_time
    this function raises a TypeError
"""
def set_dt_globls(dt):
    global default_dt, default_s_dt, default_tpl_dt
    TAG=tag_adj("set_dt_globls(): ")
    if my_debug:
        print(TAG+f"param dt, type(dt)= {type(dt)}")
    if isinstance(dt, time.struct_time):
        default_dt = dt
        default_s_dt = dtstru_to_str() # convert to type str
        default_tpl_dt = dtstr_to_tpl()  # convert to type tuple
        if my_debug:
            print(TAG+f"default_dt    ={default_dt}, type(default_dt)= {type(default_dt)}")
            print(TAG+f"default_s_dt  = \'{default_s_dt}\',type(default_s_dt)= {type(default_s_dt)}")
            print(TAG+f"default_tpl_dt= \'{default_tpl_dt}\',type(default_tpl_dt)= {type(default_tpl_dt)}")
    else:
        print(TAG+f"parameter dt needs to be type time.struct_time. It is of type: {type(dt)}")
        raise TypeError

"""
    Function ck_secs()

    :param  None
    :return str

    This function uses the global variable default_s_dt,
    with the assumption that default_s_dt just has been set
    (from withing get_NTP() ). It extracts the seconds value
    and returns the seconds value.
"""
def ck_secs(dts):
    TAG=tag_adj("ck_secs(): ")
    if dts is None:
        dts2 = default_s_dt
    else:
        print(TAG+f"param value= {dts}")
        dts2 = dts  # we use the parameter

    secs = int(dts2[-2:])   # ord(dts2[-2])
    #print(TAG+f"secs = \'{secs}\'")
    return secs

"""
    Function get_NTP()

    :param  None
    :return None

    This function fetches ntp.datetime.
    If not set yet, this function will set the built-in RTC
    The result is put in the global variable default_dt
"""
def get_NTP():
    global pool, ntp, rtc_is_set, default_dt, default_s_dt, default_tpl_dt
    TAG=tag_adj("get_NTP(): ")
    dt = None
    #default_dt = time.struct_time((2022, 9, 17, 12, 0, 0, 5, 261, -1))

    if use_ntp:
        if wifi_is_connected:
            try:
                if not ntp:
                    pool = socketpool.SocketPool(wifi.radio)
                    # NOTE: tz_offset, integer, number of hours offset: 1, 2, 3, -5 etc.
                    ntp = NTP(pool, tz_offset=tz_offset)
                    if ntp and my_debug:
                        print(TAG+"ntp object created")
                # print(TAG+f"type(ntp)= {ntp}")
                if ntp:
                    if my_debug:
                        # Note ntp._tz_offset returns the offset from UTC in seconds
                        print(TAG+f"ntp._tz_offset= {ntp._tz_offset}")
                    dt = ntp.datetime  # type(dt) = time.struct_time
                    set_dt_globls(dt) # set the global default_dt, default_s_dt and default_tpl_dt
                    print(TAG+f"time from NTP= \'{default_s_dt}\'")
                    print(TAG+f"timezone= \'{location}\'. Offset from UTC= {tz_offset} Hr(s)")
                    if my_debug:
                        print(TAG+f"ntp.datetime()={dt}, type(ntp.datetime())={type(dt)}")
                    rtc_is_set = False
                    if not rtc_is_set:
                        if isinstance(default_tpl_dt, tuple):
                            #----------------------------------------
                            rtc.datetime = default_tpl_dt # set the built-in RTC from a datetime tuple
                            #----------------------------------------
                            rtc_is_set = True
                            print(TAG+f"built-in RTC is synchronized from NTP")
                            if my_debug:
                                print(TAG+f"\n\t{dt}")
                        else:
                            print(TAG+f"expected type tuple. received type {type(dt)}")
                            raise TypeError
            except OSError:
                pass
            # Get the current time in seconds since Jan 1, 1970 and correct it for local timezone
            # Note: the if global flag 'use_local_time' is False then we use UTC time. Then the tz_offset will be 0.
            # (defined in secrets.h)
            # Convert the current time in seconds since Jan 1, 1970 to a struct_time
            dt = time.localtime(time.time())  # default_dt type = time.struct_time
            set_dt_globls(dt) # update global default_dt, default_s_dt and default_tpl_dt from the built-in RTC
            if my_debug:
                print(TAG+f"datetime is updated from NTP")
        else:
            print("No internet. Setting default time")
    else:
        if not rtc_is_set:
            rtc.datetime = default_tpl_dt # Set the built-in rtc to a fixed fictive datetime
            print("built-in RTC set with default time")
            rtc_is_set = True

"""
    Function ck_uart()

    :param  None
    :return int    nr_bytes received

    This function checks for incoming characters. If received incoming characters,
    the funtions first checks for reception of a transmission of 2 bytes,
    containing:
    a) the address of the Sensor device that the originator (device with Main role)
    wants to address this request;
    b) one byte containing a request code.

    REQUEST (2-byte transmission) received?                           (FLOWCHART)
    > Yes
        > Addressed to me?
            > Yes
                > request code is valid? (exsists?)
                    Yes >
                        > copy request code to global var req_rcvd;
                        > send acknowledge to originator (device with Main role)
                    > No
                        > Do nothing
            > No
                > Do nothing
    > No
        > Do nothing

    In words:
    When this function receives a request, the following steps are executed:
    1) determine if the request is addressed to this device (with Sensor role);
    2) if so:
        a) check the validity of the request code;
        b) if the request code is valid, copy the received request code into
        the global variable 'req_rcvd';
    3) send an an acknowledge code (_ACK) to the device from which the Sensor
        device received the request. The acknowledge contains the address of
        the sender device (Main role).add()
    The calling function (loop()) will 'handle' the received request.

    This function also 'fills' the global rx_buffer with characters received.
    In case of a KeyboardInterrupt during the execution of this function, the function
    will return a value of -1, 'signalling' the calling function (loop())
    that a KeyboardInterrupt has occurred.

"""
def ck_uart():
    global rx_buffer, msg_nr, loop_time, my_debug, req_rcvd, sensor_ads
    TAG = tag_adj('ck_uart(): ')
    nr_bytes = 0
    delay_ms = 0.2
    empty_buffer()  # clean the rx_buffer
    u_start = time.monotonic()
    u_end = u_start + 60
    if my_debug:
        print(TAG+"Entering...")
        print(TAG+f"u_start= {u_start}")
    try:
        while True:
            u_now = time.monotonic()
            if u_now > u_end:
                #print(TAG+f"timed-out. u_now= {u_now}, u_end= {u_end}")
                print(TAG+f"timed-out")
                return 0  # timeout
            #--------------------------------------------------------------
            rx_buffer = uart.read(rx_buffer_len)
            #--------------------------------------------------------------
            if rx_buffer is None:
                time.sleep(0.2)
                continue
            nr_bytes = len(rx_buffer)
            if my_debug:
                print(TAG+"nr of bytes= ", nr_bytes)
                print(TAG+"type(rx_buffer)=", type(rx_buffer))
                print(TAG+"rcvd data: {}".format(rx_buffer),end="\n")
            loop_time = time.monotonic()
            if nr_bytes is None:
                if my_debug:
                    print(TAG+"nr_bytes received is None")
                time.sleep(delay_ms)
                continue
            if not nr_bytes:
                if my_debug:
                    print(TAG+f"nr_bytes received={nr_bytes}")
                time.sleep(delay_ms)
                continue
            elif nr_bytes == 2:
                b = rx_buffer[:2]
                ads = b[0]  # Address of the 'destination' device
                req = b[1]  # Code representing the request type
                if req in req_dict.keys():
                    req_txt = req_dict[req]
                else:
                    req_txt = ''
                s_ads = "0x{:x}".format(ads)
                print(TAG+f"received address: {s_ads}")
                print(TAG+f"received request: {req} = {req_txt}")
                if ads == sensor_ads:  # is this device addressed ?
                    if req in req_dict.keys():
                        tx_failed = None
                        if my_debug:
                            print(TAG+f"request {req} found in list of request keys: {req_dict.keys()}")
                        req_rcvd = req
                        b = bytearray(2)
                        b[0] = main_ads  # add the address of 'destination'
                        b[1] = _ACK      # add the ACK ASCII value
                        n = uart.write(b)  # send acknowledgement
                        if n is not None:
                            if n > 0:
                                if my_debug:
                                    print(TAG+f"acknowledge on request sent: {b}. Number of characters sent: {n}")
                                else:
                                    print(TAG+"acknowledge on request sent")
                                time.sleep(1)  # Create a time space between sending ACK and next sending datetime\
                            else:
                                tx_failed = True
                        else:
                            tx_failed = True
                        if tx_failed:
                            print(TAG+"sending an acknowledge failed")
                        break  # leave loop
            else:
                empty_buffer()  # create a new instance of the rx_buffer (bytearrray)
                time.sleep(delay_ms)
                continue  # go around
    except KeyboardInterrupt:
        nr_bytes = -1
    if my_debug:
        print(TAG+"Exiting...")
    return  nr_bytes

loop_nr = 1
"""
    Function loop()

    :param  None
    :return int, characters received, or
                 in case of a Keyboard Interrupt occurred
                 inside this function,
                 the function will return a value of -1
                 to 'signal' to the calling function (main())
                 that a Keyboard Interrupt took place.

    This function checks incoming request codes.
    Only the 'date_time' request is implemented yet.
    The two other 'unix_datetime' or 'weather'
    are not implemented.
"""
def loop():
    global loop_nr, rx_buffer, req_rcvd
    TAG = tag_adj("loop(): ")
    gts = "going to send "
    while True:
        try:
            print("=" * 37)
            print(TAG+"loop nr: {:3d}".format(loop_nr))
            print("=" * 37)
            chrs_rcvd = ck_uart()  # Check and handle incoming requests and control codes
            if chrs_rcvd == -1:  # did a Keyboard Interrupt took place?
                return chrs_rcvd # if so, 'signal' this to the calling function (main())
            if chrs_rcvd > 0:
                #-------------------------------------------------------
                uart.reset_input_buffer()  # Clear the uart buffer
                #-------------------------------------------------------
                if req_rcvd is not None:
                    if req_rcvd in req_dict.keys():
                        s = req_dict[req_rcvd]
                        print(TAG+f"the device with role: {roles_dict[0]} requested to send: {s}")
                        print(TAG+gts+req_dict[req_rcvd])
                        if req_rcvd == 100:
                            get_NTP()
                            send_dt()
                        elif req_rcvd == 101:
                            send_ux()
                        elif req_rcvd == 102:
                            send_wx()
                    else:
                        # req not found
                        print(TAG+f"Unknown request \'{req_rcvd}\' received")
            loop_nr += 1
            if loop_nr > 1000:
                loop_nr = 1
        except KeyboardInterrupt:
            print(TAG+"KeyboardInterrupt. Exiting loop()")
            lStop = True
            break
        except OSError as e:
            lStop = True
            raise
    if lStop:
        return -1
    else:
        return 1

"""
   Function send_dt()

   :param  str s
   :return None

   This function sends:
   If param s is presented, it sends s to the device that sent the request
   If s is not present, a datetime string is sent to the device that sent the request.
   In this moment, for the sake of this test, only a fixed (static) datetime string
   is programmed in this script. In future versions one could combine the functionality
   of this script into a script in which the device connects to Internet and then
   requests, e.g. using the adafruit_ntp module, for an NTP datetime synchronization.
   After receiving this updated time, send that datetime string to the device that
   requested for the datetime.
"""
def send_dt(s_epoch: str=''):
    global default_s_dt
    TAG=tag_adj("send_dt(): ")
    msg = None
    le = None
    n = None
    s_dt = ''
    option = 0

    if option == 0 and isinstance(s_epoch, str):
        le = len(s_epoch)
        if le > 0:
            msg = bytearray(le+3)
            msg = bytearray(le+3)
            msg[0] = main_ads
            msg[1] = le
            msg[2] = _STX  # Start of message marker
            for i in range(le):
                msg[3+i] = ord(s_epoch[i])
            le2 = len(msg)
                #--------------------------------------------------
            n =uart.write(msg)
            #--------------------------------------------------
            if n is None:
                print(TAG+"failed to send unix time")
            elif n > 0:
                print(TAG+f"{req_dict[req_rcvd]} \'{s_epoch}\' sent. Nr of characters: {le2}")
                print(TAG+f"contents of the msg= {msg}") # bytearray(b' \x..\x......ToDo......')
                #                                                             /\
                #
            return

    if isinstance(default_s_dt, str):
        option = 1
        s_dt = default_s_dt
        if my_debug:
            print(TAG+f"to do: sending default_s_dt= \'{default_s_dt}\'")

    le = len(s_dt)
    if le > 0:
        # b = bytes(default_dt, 'utf-8')
        msg = bytearray(le+3)
        msg[0] = main_ads
        msg[1] = le
        msg[2] = _STX  # Start of message marker
        for i in range(le):
            msg[3+i] = ord(s_dt[i])
        le2 = len(msg)
        #--------------------------------------------------
        n =uart.write(msg)
        #--------------------------------------------------
        if n is None:
            print(TAG+"failed to send datetime")
        elif n > 0:
            print(TAG+f"datetime message sent. Nr of characters: {le2}")
            if my_debug:
                print(TAG+f"contents of the message= {msg}")
            """
             bytearray(b' \x13\x022022-10-06 01:15:00')
                        /\
                        byte0 = ' ' = 0x20 = 32 decimal (ascii value for space character)
                                It is the address of the device with role 'Main',
                                the device the sent the request for datetime.
                            /\
                            byte1 = \x13 = length of the datetime string following the STX code
                                /\
                                byte2 = \x02 = STX ASCII code (indicates start of datetime)
            """

"""
   Function send_us()

   :param  None
   :return None

   This function sends a unix epoch value as a type str
"""
def send_ux():
    global epoch
    epoch = get_epoch()
    send_dt(str(epoch))

""" ToDo """
def send_wx():
    pass

"""
   Function empty_buffer()

   :param  None
   :return None

   Function creates a new instance of the rx_buffer bytearray
"""
def empty_buffer():
    global rx_buffer, rx_buffer_len
    rx_buffer = bytearray(rx_buffer_len * b'\x00')

"""
    Function setup()

    :param  None
    :return None

    This function creates instances of the UART and RTC objects.
    It also sets various global variables which some of them it reads from the file secrets.py
"""
def setup():
    global rtc, ntp, default_dt, tz_offset, use_local_time, aio_username, aio_key, location, secs_synced  # , pool
    TAG=tag_adj("setup(): ")

    wifi.AuthMode.WPA2   # set only once

    if not uart:
        print(TAG+"failed to create an instance of the UART object")

    rtc = RTC()  # create the built-in rtc object
    if not rtc:
        print(TAG+"failed to create an instance of the RTC object")
    secs_synced = False  # see get_NTP()

    lt = secrets.get("LOCAL_TIME_FLAG", None)
    if lt is None:
        use_local_time = False
    else:
        lt2 = int(lt)
        if my_debug:
            print("lt2=", lt2)
        use_local_time = True if lt2 == 1 else False
        if not my_debug:
            print(TAG+f"using local time= {use_local_time}")

    if use_local_time:
        location = secrets.get("timezone", None)
        if location is None:
            location = 'Not set'
            tz_offset = 0
        else:
            tz_offset0 = secrets.get("tz_offset", None)
            if tz_offset0 is None:
                tz_offset = 0
            else:
                tz_offset = int(tz_offset0)
                if my_debug:
                    print(TAG+f"tz_offset= {tz_offset}")
    else:
        location = 'UTC'
        tz_offset = 0

"""
    Function tag_adj()

    :param  str
    :return str

    This function fills param t with trailing spaces up to the value of global variable tag_le_max
"""
def tag_adj(t):
    global tag_le_max
    le = 0
    spc = 0
    ret = t
    if isinstance(t, str):
        le = len(t)
    if le >0:
        spc = tag_le_max - le
        #print(f"spc= {spc}")
        ret = ""+t+"{0:>{1:d}s}".format("",spc)
        #print(f"s=\'{s}\'")
    return ret

"""
    Function main()

    :param  None
    :return None

    This function contains the main loop of this script.
    It prints introduction texts to the REPL.
    Next it calls the loop() function in which the script
    will go around until the user interrupts the process
    with a (CTRL+C) Keyboard Interrupt.
"""
def main():
    global my_debug, ctrl_c_flag, rtc_is_set, t_start
    TAG=tag_adj("main(): ")
    lResult = True
    cnt = 0
    f = ''
    if id.find('pros3') >= 0:
        f = roles_dict[1]
    elif id.find('titano') >= 0:
        f = roles_dict[0]
    time.sleep(5) # Give user time to set up a terminal window or so
    print('=' * 36)
    print("SERCOM VIA I2C TEST")
    print(f"Version {sercom_I2C_version}")
    print(f"Running on an {id.upper()}")
    print(f"in the role of {f}")
    print('=' * 36)
    setup()
    t_elapsed = 0
    t_curr = time.monotonic()
    t_interval = 120  # every 2 minutes. In future increase to 10 minutes (600)
    while True:
        try:
            t_elapsed = t_curr - t_start
            if t_elapsed > 0 and t_elapsed % t_interval == 0:
                t_start = t_curr
                rtc_is_set = False  # sync buitl-in RTC from NTC)
            if not wifi_is_connected():
                print("\n"+TAG+"trying to connect WiFi...")
                do_connect()
            #time.sleep(2)
            if cnt == 0:
                cnt += 1
                lResult = loop()
                if lResult == -1: # A Keyboard Interrupt occurred?
                    raise KeyboardInterrupt # Yes, raise it
        except KeyboardInterrupt:
            print(TAG+"KeyboardInterrupt- Exiting...") # Handle the Keyboard Interrupt
            sys.exit()

if __name__ == '__main__':
    main()
