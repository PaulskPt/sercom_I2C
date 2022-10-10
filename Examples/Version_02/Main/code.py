 # SPDX-FileCopyrightText: Copyright (c) 2022 Tim Cocks for Adafruit Industries
# (c) 2022 Paulus Schulinck for modifications done and for the sercom_I2C part.
#
# SPDX-License-Identifier: MIT
#
# Original filename: 'displayio_flipclock_ntp_test2_PaulskPt.py'
# Modified to incorporate 'sercom_I2C' serial communication via I2C wires.
# Version 2
#
"""
    Advanced example that shows how you can use the
    FlipClock displayio object along with the adafruit_ntp library
    to show and update the current time with a FlipClock on a display.

    In this example the device performing the role of 'Main' sends datetime requests
    to another CircuitPython device performing the role of 'Sensor'. The 'Sensor'
    sends to the 'Main' device a message containing a datetime string after being requested to.

    The reason for 'moving' certain tasks to another MCU is to prevent memory memory errors.
    The bitmapped spritesheets used in this script consume a large part of the memory available
    in the PyPortal Titano.
"""

import time
import gc
import sys
import board
from rtc import RTC
from busio import UART
from micropython import const
from displayio import Group
import adafruit_imageload
from adafruit_displayio_flipclock.flip_clock import FlipClock


""" Global flags """
my_debug = False
use_ntp = True
use_local_time = True
use_flipclock = True
use_dynamic_fading = False

""" sercom_I2C global variables """
_STX = const(0x02)  # Start-of-text ASCII code
_ACK = const(0x06)  # Acknowledge ASCII code
_NAK = const(0x15)  # Not acknowledged ASCII code . Not used yet but can be implemented

roles_dict = {
    0: 'Main',
    1: 'Sensor'
}

req_dict = {
   100: 'date_time',  # 100 dec = 64 hex
   101: 'unix_time',
   102: 'weather'
   }

req_rev_dict = {
   'date_time': 100,  # 100 dec = 64 hex
   'unix_time': 101,
   'weather': 102
    }

acknak_dict = {
    _ACK: 'ACK',
    _NAK: 'NAK'
}

# Buffers
max_bytes = 2**5 # buffer length mus be a power of 2   (2, 4, 8, 16, 32, 64, ...) 2**5=64
rx_buffer_len = max_bytes
rx_buffer = bytearray(rx_buffer_len * b'\x00')

id = board.board_id

my_ads = 0x20
master_ads = 0x20
target_ads = 0x25
msg_nr = 0
default_dt = '2022-10-06 01:15:00' # For the sake of the test a default datetime string
last_req_sent = 0
ACK_rcvd = False

""" Other global variables """
rtc = None
rtc_is_set = False
location = None
default_dt = None
default_s_dt = ''
unix_dt = None
main_group = None
clock = None
display = board.DISPLAY
t_start = time.monotonic()
tz_offset = 0
hour_old = 0
min_old = 0
tag_le_max = 20  # see tag_adj()

# +-----------------------------------------------+
# | Create an instance of the UART object class   |
# +-----------------------------------------------+
# Important: the SDA and SCL wires have to be crossed:
# SDA (device with role Main) ===> SCL (device with role Sensor)
# SCL (device with role Main) ===> SDA (device with role Sensor)
# in other worde: cross-over type of connection
# equal to the RX/TX serial wiring.
uart = UART(board.SDA, board.SCL, baudrate=4800, timeout=0, receiver_buffer_size=rx_buffer_len)


def setup():
    global rtc, esp, tz_offset, use_local_time, aio_username, aio_key, location
    TAG=tag_adj("setup(): ")

    if not uart:
        print(TAG+"failed to create an instance of the UART object")

    rtc = RTC()  # create the built-in rtc object
    if not rtc:
        print(TAG+"failed to create an instance of the RTC object")

    try:
        from secrets import secrets
    except ImportError:
        print("WiFi secrets are kept in secrets.py, please add them there!")
        raise

    lt = secrets.get("LOCAL_TIME_FLAG", None)
    if lt is None:
        use_local_time = False
    else:
        lt2 = int(lt)
        if my_debug:
            print("lt2=", lt2)
        use_local_time = True if lt2 == 1 else False

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
    else:
        location = 'Etc/GMT'
        tz_offset = 0

    make_clock()

"""
   Function find_c()

   :param string (c)
   :return type: dict (f_dict)

   This function scans the receive buffer (rx_buffer) for all occurrances
   of a character with the value of parameter c.
   If found then the index to rx_buffer when the charecter was found
   will be added to the dictionary (f_dict).

"""
def find_c(c):
    global rx_buffer
    TAG = tag_adj("find_c():   ")
    f_dict = {}
    c2 = ''
    o_cnt = 0
    if c is None:
        return 0
    if type(c) is int:
        c2 = chr(c)
    elif type(c) is str:
        c2 = c
    rx_buffer_s = rx_buffer.decode()
    if c == _ACK or c == _STX:
        n = rx_buffer_s.find(c2)
        if n >= 0:
            f_dict[o_cnt] = n
        else:
            if my_debug:
                if c == _ACK:
                    print(TAG+f"{acknak_dict[c]} not found in rx_buffer")
                elif c == _STX:
                    print(TAG+"STX code not found in rx_buffer")
    else:
        if my_debug:
            print(TAG+f"rx_buffer= {rx_buffer}")
        le = len(rx_buffer_s)
        if le > 0:
            ret = rx_buffer_s.count(c2)
            if my_debug:
                print(TAG+f"nr occurences of \'{c2}\'= {ret}")
            for i in range(le):
                if rx_buffer_s[i] == c2:
                    f_dict[o_cnt] = i
                    o_cnt += 1
    return f_dict

"""
   Function ck_uart()

   :param None
   Return type: int, nr_bytes received

   This function 'fills' the global rx_buffer with characters received.
   It checks for reception of an ACK ASCII code, being the 'acknowledge' by the device
   with the 'Sensor' role. If an ACK code is received this function will check for the
   reception of a messag from the device with the Sensor role.
   When a datetime message is received this function checks it's validity. If OK then
   it sets the global variable default_s_dt. When a message containing a unix epoch value is
   received, this function will set the global variable unix_dt.
   In case of a KeyboardInterrupt during the execution of this function, this function
   will return a value of -1, herewith 'signalling' the called function (main())
   that a KeyboardInterrupt has occurred.

"""
def ck_uart():
    global rx_buffer, msg_nr, loop_time, my_debug, last_req_sent, my_ads, default_s_dt, unix_dt, ACK_rcvd
    TAG = tag_adj('ck_uart():  ')
    nr_bytes = 0
    delay_ms = 0.2
    u_start = time.monotonic()
    msg = ''
    s_req = ''
    le_msg = 0
    u_end = u_start + 20
    f_dict = None
    ACK_rcvd = False
    STX_rcvd = False
    STX_idx = -1
    msg_is_for_us = False
    t_buf = None
    if my_debug:
        print(TAG+"Entering...")
        print(TAG+f"u_start= {u_start}")
    while True:
        empty_buffer()  # clear the rx_buffer
        try:
            u_now = time.monotonic()
            if u_now > u_end:
                print(TAG+f"timed-out. u_now= {u_now}, u_end= {u_end}")
                return 0  # timeout
            rx_buffer = uart.read(rx_buffer_len)
            if rx_buffer is None:
                time.sleep(0.2)
                continue  # Go around
            nr_bytes = len(rx_buffer)
            loop_time = time.monotonic()
            if nr_bytes is None:
                if not my_debug:
                    print(TAG+"nr_bytes received is None")
                time.sleep(delay_ms)
                continue  # Go around
            if not nr_bytes:
                if not my_debug:
                    print(TAG+f"nr_bytes received={nr_bytes}")
                time.sleep(delay_ms)
                continue  # Go around
            if not my_debug:
                print(TAG+f"nr of bytes received= {nr_bytes}")
                print(TAG+f"type(rx_buffer)={type(rx_buffer)}")
                rd = "{}".format(rx_buffer)
                print(TAG+f"rcvd data= {rd}" ,end="\n")
            if nr_bytes >0:
                if nr_bytes == 2 and not ACK_rcvd:
                    """
                        Search rx_buffer for an ACK (Acknowledge) ASCII
                        The ACK code is used as an acknowledge of good reception,
                        in this case, of a request code sent to the device with the
                        Sensor role.
                    """
                    f_dict = find_c(_ACK) # find occurrence of ACK
                    if isinstance(f_dict, dict):
                        if my_debug:
                            print(TAG+f"f_dict after search for _ACK= {f_dict}")
                        le = len(f_dict)
                        if le == 1 and f_dict[0] == 1:
                            ACK_rcvd = True
                        elif le > 1:
                            print(TAG+f"found {le} ACK codes in rx_buffer. Expected only one. Skipping 2 and more")
                        else:
                            # no ACK received. Go around
                            pass
                        if ACK_rcvd:
                            print(TAG+f"ACK code received from {roles_dict[1]}")
                            print(TAG+"waiting for reception of the message...")
                        time.sleep(delay_ms)
                        continue  # loop to receive the message
                """
                    Search rx_buffer for an STX (Start-of-text) ASCII
                    The STX code is used as a 'marker' of the start of the message data,
                    in this example, the start of the datetime string
                """
                f_dict = find_c(_STX)
                if isinstance(f_dict, dict):
                    if my_debug:
                        print(TAG+f"f_dict after search for _STX= {f_dict}")
                    le = len(f_dict)
                    if le == 1 and f_dict[0] == 2:
                        STX_idx = f_dict[0]
                        STX_rcvd = True
                    elif le > 1:
                        print(TAG+f"found {le} STX codes in rx_buffer. Expected only one. Skipping 2 and more")
                    else:
                        # No STX code found in rx_buffer.
                        time.sleep(delay_ms)
                        continue  # go around
                    if STX_rcvd:
                        print(TAG+f"STX code received from {roles_dict[1]}")
                if last_req_sent == req_rev_dict['date_time']:
                    ads = rx_buffer[0]
                    if ads == my_ads:
                        msg_is_for_us = True
                    s = "" if msg_is_for_us else " not"
                    print(TAG+f"the received message is{s} addressed to device with role: \'{roles_dict[0]}\'")
                    s_ads = "0x{:x}".format(ads)
                    print(TAG+f"received address: {s_ads}")
                    le_msg = rx_buffer[STX_idx -1]
                    print(TAG+f"received value for msg length= {le_msg}")
                    msg = ''
                    t_buf = rx_buffer[STX_idx+1:STX_idx+1+le_msg]
                    # get the actual length (the sent length can be wrong if we miss one or more characters
                    le = len(t_buf)
                    if le != le_msg:
                        print(TAG+"received message is invalid:")
                        print(TAG+f"received msg length: {le_msg}. Actual measured msg length= {le}")
                        continue  # go around
                    if my_debug:
                        print(TAG+f"rx_buffer sliced-off from STX+1 until STX+1+msg length= {t_buf}")
                    for i in range(le):
                        msg += chr(t_buf[i])
                    if my_debug:
                        print(TAG+f"msg received= \'{msg}\', length: {le_msg}")
                    if last_req_sent in req_dict.keys():
                        s_req = req_dict[last_req_sent]
                        if s_req == 'date_time':
                            #-------------------------------------------------
                            default_s_dt = msg    # Global datetime var set
                            #-------------------------------------------------
                            vrf = default_s_dt  # vrf stands for variable received from
                            s_vrf = 'default_s_dt'
                        elif s_req == 'unix_time':
                            unix_dt = msg
                            vrf = unix_dt
                            s_vrf = 'unix_dt'
                        drf = s_req+" received from "
                        if my_debug:
                            print(TAG+drf+f"{roles_dict[1]} = \'{vrf}\', type({s_vrf})= {type(vrf)}")
                            print(TAG+f"length of datetime= {le_msg}")
                        else:
                            print(TAG+drf+f"{roles_dict[1]} = \'{vrf}\'")
                    else:
                        print(TAG+f"value last_req_sent: \'{last_req_sent}\' not in req_dict.keys(). Go around")
                        continue # go around
                    break
            else:
                empty_buffer()  # create a new instance of the rx_buffer (bytearray)
                time.sleep(delay_ms)
                continue  # go around
        except KeyboardInterrupt:
            nr_bytes = -1
    if my_debug:
        print(TAG+"Exiting...")
    return nr_bytes

"""
   Function send_req()

   :param integer 'c'
   :return type: int, number of characters sent
"""
def send_req(c):
    global last_req_sent
    TAG = tag_adj("send_req(): ")
    n = 0
    try:
        if isinstance(c, int):
            if c in req_dict.keys():
                c_txt = req_dict[c]
            else:
                c_txt = 'unknown'
                return n  # Exit. Cannot send non existing request code.
            if my_debug:
                print(TAG+f"going to send request code {c} = {c_txt}")
            b = bytearray(2)
            b[0] = target_ads  # Address of 'destination'
            b[1] = c # request code
            n = uart.write(b)
            if n is None:
                print(TAG+f"failed to send request: {c}")
            elif n > 0:
                last_req_sent = c  # remember last request code sent
                s = TAG+"request for {} sent".format(req_dict[c])
                if my_debug:
                    print(s+" Nr of characters sent: {n}")
                else:
                    print(s)  # Always inform user with send result
    except KeyboardInterrupt:
        n = -1
    return n

"""
   Function empty_buffer()

   :param None
   :return None

   Function creates a new instance of the rx_buffer bytearray
"""
def empty_buffer():
    global rx_buffer, rx_buffer_len
    rx_buffer = bytearray(rx_buffer_len * b'\x00')

"""
   Function make_clock()

   :param None
   :return None

   Function creates the flipclock, if global variable 'use_flipclock' is set.
"""
def make_clock():
    global clock
    TAG=tag_adj("make_clock(): ")

    if use_flipclock:
        TRANSPARENT_INDEXES = range(11)
        static_ss, static_palette = adafruit_imageload.load("static_s.bmp")
        static_palette.make_transparent(0)

        gc.collect()
        top_anim_ss, top_anim_palette = adafruit_imageload.load(
            "top_anim_s_5f.bmp"
        )
        gc.collect()
        btm_anim_ss, btm_anim_palette = adafruit_imageload.load(
            "btm_anim_s_5f.bmp"
        )
        for _ in TRANSPARENT_INDEXES:
            top_anim_palette.make_transparent(_)
            btm_anim_palette.make_transparent(_)
        gc.collect()
        print(TAG+f"mem_free= {gc.mem_free()}")
        try:
            clock = FlipClock(
                    static_ss,
                    static_palette,
                    top_anim_ss,
                    top_anim_palette,
                    btm_anim_ss,
                    btm_anim_palette,
                    static_ss.width // 3,
                    (static_ss.height // 4) // 2,
                    anim_frame_count=5,
                    anim_delay=0.02,
                    colon_color=0x00FF00,
                    dynamic_fading=use_dynamic_fading,
                    brighter_level=0.99,
                    darker_level=0.5,
                    medium_level=0.9,
                    h_pos=48,
                    v_pos=54)
            main_group = Group()
            main_group.append(clock)
            main_group.scale = 2  # don't go higher than 2. Then the 'flipping' will be very slow
            board.DISPLAY.show(main_group)
        except MemoryError as e:
            print(TAG+f"Error: {e}")

"""
    Function dt_adjust()

    :param None
    :return None

    Function set global variable default_dt and unix_dt
"""
def dt_adjust():
    global default_dt, unix_dt
    TAG=tag_adj("dt_adjust(): ")
    if my_debug:
        print(TAG+"use_local_time= {}".format("True" if use_local_time else "False"))
        print("             tz_offset=", tz_offset)
        print("             location=", location)

    if rtc_is_set:
        default_dt = time.localtime(time.time())
        unix_dt = time.time()

"""
   Function upd_tm()

   :param None
   :return None

   Function calls dt_adjust, then creates and sets the clock.first_pair and clock.second_pair
"""
def upd_tm(show_t: bool = False):
    global clock, default_dt, default_s_dt, hour_old, min_old
    TAG=tag_adj("upd_tm(): ")
    ret = 1

    if show_t and not rtc_is_set:
        print(TAG+"built-in RTC is not (yet) set")
        return 0
    if default_s_dt is None:
        return -1
    if clock is None:
        return -1

    try:
        tm_hour = 3
        tm_min = 4
        tm_sec = 5

        dt_adjust()

        if my_debug:
            print(TAG+"default_s_dt=", default_s_dt)
        p_time = False
        """
        hh = default_dt[tm_hour]
        mm = default_dt[tm_min]
        """
        le = len(default_s_dt)
        if le < 16:
            print(TAG+f"datetime {default_s_dt} invalid.")
            return 0

        if my_debug:
            print(TAG+f"hh= {default_s_dt[11:13]}")
            print(TAG+f"mm= {default_s_dt[14:16]}")

        hh = int(float(default_s_dt[11:13]))
        mm = int(float(default_s_dt[14:16]))
        if hh != hour_old:
           hour_old = hh
           p_time = True
        if mm != min_old:
            min_old = mm
            p_time = True
        if p_time:
            if my_debug:
                print(TAG+"default_dt[{}]={:02d} , default_dt[{}]={:02d}".format(tm_hour, default_dt[tm_hour], tm_min, default_dt[tm_min]))
            if use_flipclock:
                wait = 1
                try:
                    fp = "{:02d}".format(hh)
                    if my_debug:
                        print(TAG+"setting clock.first_pair:", fp)
                    clock.first_pair = fp
                    fp2 = clock.first_pair
                    time.sleep(wait)
                    if my_debug:
                        print(TAG+"clock.first_pair=", fp2)
                    sp = "{:02d}".format(mm)
                    if my_debug:
                        print(TAG+"setting clock.second_pair:", sp)
                    clock.second_pair = sp
                    sp2  = clock.second_pair
                    time.sleep(wait)
                    if my_debug:
                        print(TAG+"clock.second_pair=", sp2)
                    print(TAG+"Time = {}:{}".format(fp2, sp2))
                except ValueError as e:
                    print(TAG)
                    raise
                #time.sleep(0.2)
    except KeyboardInterrupt:
        ret = -1
    # print(TAG+f"returning with: {ret}")
    return ret

def dtstr_to_stru():  # was (s: str=''):
    global default_dt
    TAG=tag_adj("dtstr_to_stru(): ")
    ret = None
    if my_debug:
        print(TAG+f"default_dt= {default_dt}")
        print(TAG+f"default_s_dt= {default_s_dt}")
    if isinstance(default_s_dt, str):
        s = default_s_dt
        le = len(s)
        if le > 0:
            # string in form 'yyyy-mm-dd hh:mm:ss'
            yy = int(s[:4])
            mo = int(s[5:7])
            dd = int(s[8:10])
            hh = int(s[11:13])
            mi = int(s[14:16])
            ss = int(s[17:])
            wd = 0
            yd = 0
            isdst = -1
            ret = (yy, mo, dd, hh, mi, ss, wd, yd, isdst)
    return ret
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

   :param None
   :return None

   This function is the main loop of this script.
   It calls send_req() at the set interval times
"""
def main():
    global t_start, rtc_is_set
    TAG=tag_adj("main(): ")
    dt = None
    gc.collect()
    if id.find('pros3') >= 0:
            f = roles_dict[1]
    elif id.find('titano') >= 0:
        f = roles_dict[0]
    time.sleep(5) # Give user time to set up a terminal window or so
    print()
    print('=' * 43)
    print("DISPLAYIO.FLIPCLOCK")
    print("USING SERCOM VIA I2C TEST FOR TIME UPDATES")
    print(f"Running on an {id.upper()}")
    print(f"in the role of {f}")
    print('=' * 43)
    setup()

    if my_debug:
        print("        use_flipclock      =", "True" if use_flipclock else "False")
        print("        use_dynamic_fading =", "True" if use_dynamic_fading else "False")
        print("        use_ntp            =", "True" if use_ntp else "False")
        print("        use_local_time     =", "True" if use_local_time else "False")
        print("        location           =", location)
    t_elapsed = 0
    t_curr = time.monotonic()
    t_interval = 30 # in the future set to 600 (10 minutes)
    res = 0
    start = True
    t_shown = False
    t_elap_old = 0

    while True:
        try:
            t_curr = time.monotonic()
            t_elapsed = int(float(t_curr - t_start))
            if t_elapsed > 0 and t_elapsed % 10 == 0:
                if t_elap_old != t_elapsed:
                    t_elap_old = t_elapsed
                    print(TAG+f"Time elapsed: {t_elapsed}")
            if start or (t_elapsed > 0 and t_elapsed % 60 == 0):
                # At minute interval update the flipclock display
                res = upd_tm(False)
                if res == -1:
                    raise KeyboardInterrupt
            if start or (t_elapsed > 0 and t_elapsed % t_interval == 0):
                t_start = t_curr
                t_shown = False
                rtc_is_set = False  # sync buitl-in RTC from NTC)
                #if 'date_time' in req_rev_dict.keys():
                req = req_rev_dict['date_time']
                print(TAG+f"going to send request for {req_dict[req]} to device with role: {roles_dict[1]}")
                sr = send_req(req)
                if sr == -1:
                    raise KeyboardInterrupt
                nr_bytes = ck_uart()  # Check and handle incoming requests and control codes
                if nr_bytes == -1:
                    raise KeyboardInterrupt
                gc.collect()
                print(TAG+f"mem_free= {gc.mem_free()}")
                if isinstance(default_s_dt, str):
                    if len(default_s_dt) > 0:
                        if my_debug:
                            print(TAG+f"default_s_dt= {default_s_dt}")
                        if not rtc_is_set:
                            dts = time.struct_time(dtstr_to_stru())
                            if my_debug:
                                print(TAG+f"dts= {dts}")
                            rtc.datetime = dts
                            rtc_is_set = True
                            t_check = time.localtime(time.time())
                            if my_debug:
                                print(TAG+f"t_check= {t_check}")
                            print(TAG+f"Built-in RTC is synchronized from NTP pool")
                            if my_debug:
                                print(TAG+f"\n\t{dt}")
                        if start:
                            res = upd_tm(True)
                        else:
                            res = upd_tm(False)
                        if res == -1:
                            raise KeyboardInterrupt
                start=False
                gc.collect()
            upd_tm()
            gc.collect()
            time.sleep(0.75)
            pass
        except ValueError as e:
            print("ValueError", e)
            raise
        except KeyboardInterrupt:
            print("Keyboard interrupt. Exiting...")
            sys.exit()

if __name__ == '__main__':
    main()
