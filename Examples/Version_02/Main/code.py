 # SPDX-FileCopyrightText: Copyright (c) 2022 Tim Cocks for Adafruit Industries
# (c) 2022 Paulus Schulinck for modifications done and for the sercom_I2C part.
#
# SPDX-License-Identifier: MIT
#
# Original filename: 'displayio_flipclock_ntp_test2_PaulskPt.py'
# Modified to incorporate 'sercom_I2C' serial communication via I2C wires.
# Version 2
#
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

my_debug = False
use_ntp = True
use_local_time = None
use_flipclock = True
use_dynamic_fading = False

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

max_bytes = 2**5
rx_buffer_len = max_bytes
rx_buffer = bytearray(rx_buffer_len * b'\x00')

id = board.board_id

my_ads = 0x20
master_ads = 0x20
target_ads = 0x25
msg_nr = 0
default_dt = '2022-10-06 01:15:00'
last_req_sent = 0
ACK_rcvd = False
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

uart = UART(board.SDA, board.SCL, baudrate=4800, timeout=0, receiver_buffer_size=rx_buffer_len)

def setup():
    global rtc, tz_offset, use_local_time, location
    TAG=tag_adj("setup(): ")

    if not uart:
        so = 'UART'
    rtc = RTC()  # create the built-in rtc object
    if not rtc:
        so = 'RTC'
    if not uart or not rtc:
        print(TAG+f"failed to create an instance of the {so} object")
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

def find_c(c):
    global rx_buffer
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
        le = len(rx_buffer_s)
        if le > 0:
            ret = rx_buffer_s.count(c2)
            for i in range(le):
                if rx_buffer_s[i] == c2:
                    f_dict[o_cnt] = i
                    o_cnt += 1
    return f_dict

def ck_uart():
    global rx_buffer, msg_nr, my_debug, last_req_sent, my_ads, default_s_dt, unix_dt, ACK_rcvd
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


    try:
        empty_buffer()  # clear the rx_buffer
        while True:
            u_now = time.monotonic()
            if u_now > u_end:
                print(TAG+f"timed-out. u_now= {u_now}, u_end= {u_end}")
                return 0  # timeout
            rx_buffer = uart.read(rx_buffer_len)
            if rx_buffer is None:
                time.sleep(0.2)
                continue  # Go around
            nr_bytes = len(rx_buffer)
            if nr_bytes is None:
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
                #-------------------------------------------------------
                uart.reset_input_buffer()  # Clear the uart buffer
                #-------------------------------------------------------
                if nr_bytes == 2 and not ACK_rcvd:
                    f_dict = find_c(_ACK) # find occurrence of ACK
                    if isinstance(f_dict, dict):
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
                f_dict = find_c(_STX)
                if isinstance(f_dict, dict):
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
                    # the length sent with the msg (le_msg) can be different from the length
                    # calculated here (le), in case the UART missed one or more characters!
                    le = len(t_buf)
                    if le != le_msg:
                        print(TAG+"received message is invalid:")
                        print(TAG+f"received msg length: {le_msg}. Actual measured msg length= {le}")
                        continue  # go around
                    for i in range(le):
                        msg += chr(t_buf[i])
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
    return nr_bytes

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
            b = bytearray(2)
            b[0] = target_ads  # Address of 'destination'
            b[1] = c # request code
            n = uart.write(b)
            if n is None:
                print(TAG+f"failed to send request: {c}")
            elif n > 0:
                last_req_sent = c  # remember last request code sent
                s = TAG+"request for {} sent".format(req_dict[c])
                print(s)  # Always inform user with send result
    except KeyboardInterrupt:
        n = -1
    return n

def empty_buffer():
    global rx_buffer, rx_buffer_len
    rx_buffer = bytearray(rx_buffer_len * b'\x00')

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
        if my_debug:
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

def dt_adjust():
    global default_dt, unix_dt
    if rtc_is_set:
        default_dt = time.localtime(time.time())
        unix_dt = time.time()

def upd_tm(show_t: bool = False):
    global clock, default_dt, default_s_dt, hour_old, min_old
    TAG=tag_adj("upd_tm(): ")
    wait = 1
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

        p_time = False
        le = len(default_s_dt)
        if le < 16:
            print(TAG+f"datetime {default_s_dt} invalid.")
            return 0
        hh = int(float(default_s_dt[11:13]))
        mm = int(float(default_s_dt[14:16]))
        if hh != hour_old:
           hour_old = hh
           p_time = True
        if mm != min_old:
            min_old = mm
            p_time = True
        if p_time:
            if use_flipclock:

                try:
                    fp = "{:02d}".format(hh)
                    clock.first_pair = fp
                    fp2 = clock.first_pair
                    time.sleep(wait)
                    sp = "{:02d}".format(mm)
                    clock.second_pair = sp
                    sp2  = clock.second_pair
                    time.sleep(wait)
                    print(TAG+"Time = {}:{}".format(fp2, sp2))
                except ValueError as e:
                    print(TAG)
                    raise
                #time.sleep(0.2)
    except KeyboardInterrupt:
        ret = -1
    return ret

def dtstr_to_stru():
    global default_dt
    ret = None
    if isinstance(default_s_dt, str):
        s = default_s_dt
        le = len(s)
        if le > 0:
            # string in form 'yyyy-mm-dd hh:mm:ss'
            #ret= (yy,         mo,          dd,           hh,            mi,            ss,         wd, yd, isdst)
            ret = (int(s[:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]), int(s[17:]), 0, 0, -1 )
    return ret

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

def main():
    global t_start, rtc, rtc_is_set
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
    t_elapsed = 0
    t_curr = time.monotonic()
    t_interval = 30 # in the future set to 600 (10 minutes)
    res = 0
    start = True
    t_shown = False
    t_elap_old = 0
    stop = False

    try:
        while True:
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
                    stop = True
                    break
            if start or (t_elapsed > 0 and t_elapsed % t_interval == 0):
                t_start = t_curr
                t_shown = False
                rtc_is_set = False  # sync buitl-in RTC from NTC)
                req = req_rev_dict['date_time']
                print(TAG+f"going to send request for {req_dict[req]} to device with role: {roles_dict[1]}")
                res = send_req(req)
                if res == -1:
                    stop = True
                    break
                nr_bytes = ck_uart()  # Check and handle incoming requests and control codes
                if nr_bytes == -1:
                    stop = True
                    break
                gc.collect()
                print(TAG+f"mem_free= {gc.mem_free()}")
                if isinstance(default_s_dt, str):
                    if len(default_s_dt) > 0:
                        if not rtc_is_set:
                            dts = time.struct_time(dtstr_to_stru())
                            rtc.datetime = dts
                            rtc_is_set = True
                            t_check = time.localtime(time.time())
                            print(TAG+f"Built-in RTC is synchronized from NTP pool")
                        if start:
                            res = upd_tm(True)
                        else:
                            res = upd_tm(False)
                        if res == -1:
                            stop = True
                            break

                start=False
                gc.collect()
            time.sleep(0.75)
        if stop:
            print(TAG+"we're going to stop...")
            raise KeyboardInterrupt
    except KeyboardInterrupt:
        print("Keyboard interrupt. Exiting...")
        sys.exit()
    except ValueError as e:
        print("ValueError", e)
        raise

if __name__ == '__main__':
    main()
