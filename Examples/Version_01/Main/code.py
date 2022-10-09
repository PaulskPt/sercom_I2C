## SPDX-FileCopyrightText: Copyright (c) 2022 Paulus Schulinck @PaulskPt
#
# SPDX-License-Identifier: MIT
#
# Serial communication via I2C (alias: 'Sercom I2C')
# This script is intendedc for the device with the 'Main' role, in my case an Adafruit PyPortal Titano
import board
import time
import sys
from busio import UART
from micropython import const

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

# Global debug flag. Set it to true to receive more information to the REPL
my_debug = False

# +-----------------------------------------------+
# | Create an instance of the UART object class   |
# +-----------------------------------------------+
# Important: the SDA and SCL wires have to be crossed:
# SDA (device with role Main) ===> SCL (device with role Sensor)
# SCL (device with role Main) ===> SDA (device with role Sensor)
# in other worde: cross-over type of connection
# equal to the RX/TX serial wiring.
uart = UART(board.SDA, board.SCL, baudrate=4800, timeout=0, receiver_buffer_size=rx_buffer_len)

id = board.board_id

my_ads = 0x20
master_ads = 0x20
target_ads = 0x25
req_rcvd = 0
msg_nr = 0
default_dt = '2022-10-06 01:15:00' # For the sake of the test a default datetime string
last_req_sent = 0
ACK_rcvd = False

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
    TAG = "find_c():   "
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
   It also checks for reception of an ACK ASCII code, being the 'acknowledge' by the device
   with the 'Sensor' role. If an ACK code is received.
   In case of a KeyboardInterrupt during the execution of this function, thre function
   will return a value of -1, herewith 'signalling' the called function (main())
   that a KeyboardInterrupt has occurred.

"""
def ck_uart():
    global rx_buffer, msg_nr, loop_time, my_debug, req_rcvd, my_ads, default_dt, ACK_rcvd
    TAG = 'ck_uart():  '
    nr_bytes = 0
    delay_ms = 0.2
    u_start = time.monotonic()
    msg = ''
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
                    default_dt = msg
                    drf = "datetime received from "
                    if my_debug:
                        print(TAG+drf+f"{roles_dict[1]} = \'{default_dt}\', type(default_dt)= {type(default_dt)}")
                        print(TAG+f"length of datetime= {le_msg}")
                    else:
                        print(TAG+drf+f"{roles_dict[1]} = \'{default_dt}\'")
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
    TAG = "send_req(): "
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
    Function main()

    :param None
    Return type: None

    This function contains the main loop of this script.
    At 10 seconds intervals the value of 'elapsed' time will be printed to the REPL.
    At 'start' and next an interval determined by local variable 't_interval' (in this moment 120 or
    three minutes) the function ck_uart will be called to watch for characters and/or codes
    received via the I2C Sercom). In a 'normal' use/production environment one probably
    would set the datetime refresh interval to once in ten minutes (t_interval = 600).
"""
def main():
    global my_debug, ctrl_c_flag
    TAG = "main():     "
    lResult = True
    time.sleep(5)  # <<<==== DELAY === to give user time to setup a terminal window (if needed)
    f = ''
    if id.find('pros3') >= 0:
        f = roles_dict[1]
    elif id.find('titano') >= 0:
        f = roles_dict[0]
    print()
    print('=' * 30)
    print("SERCOM VIA I2C TEST")
    print(f"running on an {id.upper()}")
    print(f"in the role of {f}")
    print('=' * 30)
    t_start = time.monotonic()
    t_interval = 120  # 2 minutes
    t_curr = None
    t_elapsed = None
    lStart = True
    t_shown = False
    req = None
    sr = None
    nr_bytes = None
    t_elapsed_old = None
    print(TAG+f"interval set for: {t_interval//60} Minutes")
    while True:
        try:
            t_curr = time.monotonic()
            t_elapsed = int(float((t_curr - t_start)))
            if t_elapsed > 0 and t_elapsed % 10 == 0:
                if t_elapsed_old != t_elapsed:
                    t_elapsed_old = t_elapsed
                    print(TAG+"time elapsed= {:3d} Secs".format(t_elapsed))
            if lStart or (t_elapsed > 0 and t_elapsed % t_interval == 0):
                # At start or at interval of 2 minutes
                # request for update of date and time
                t_start = t_curr # update
                lStart = False
                t_shown = False
                if 'date_time' in req_rev_dict.keys():
                    req = req_rev_dict['date_time']
                    print(TAG+f"going to send request for {req_dict[req]} to device with role: {roles_dict[1]}")
                    sr = send_req(req)
                    if sr == -1:
                        raise KeyboardInterrupt
                    nr_bytes = ck_uart()  # Check and handle incoming requests and control codes
                    if nr_bytes == -1:
                        raise KeyboardInterrupt
        except KeyboardInterrupt:
            print(TAG+"KeyboardInterrupt- Exiting...")
            sys.exit()

if __name__ == '__main__':
    main()
