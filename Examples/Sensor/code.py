
# SPDX-FileCopyrightText: Copyright (c) 2022 Paulus Schulinck @PaulskPt
#
# SPDX-License-Identifier: MIT
# 
# Serial communication via I2C (alias: 'Sercom I2C')
# This script is intendedc for the device with the 'Sensor' role, in my case an Unexpected Maker PROS3
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

acknak_dict = {
    _ACK: 'ACK',
    _NAK: 'NAK'
}

# Buffers
rx_buffer_len = 2
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
main_ads = 0x20
sensor_ads = 0x25
req_rcvd = 0
msg_nr = 0
default_dt = '2022-10-06 01:15:00'  # For the sake of the test a default datetime string

#time.sleep(5)
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
    TAG = 'ck_uart(): '
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
    TAG = "loop(): "
    gts = "going to send "
    while True:
        try:
            print(TAG+f"loop nr: {loop_nr}")
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

   :param  None
   :return None
   
   This function sends a datetime string to the device that sent the request. 
   In this moment, for the sake of this test, only a fixed (static) datetime string
   is programmed in this script. In future versions one could combine the functionality
   of this script into a script in which the device connects to Internet and then 
   requests, e.g. using the adafruit_ntp module, for an NTP datetime synchronization.
   After receiving this updated time, send that datetime string to the device that
   requested for the datetime.
"""
def send_dt():
    global default_dt
    TAG = "send_dt(): "
    if isinstance(default_dt, str):
        le = len(default_dt)
        if le > 0:
            # b = bytes(default_dt, 'utf-8')
            msg = bytearray(le+3)
            msg[0] = main_ads
            msg[1] = le
            msg[2] = _STX  # Start of message marker
            for i in range(le):
                msg[3+i] = ord(default_dt[i])
            #--------------------------------------------------
            n =uart.write(msg)
            #--------------------------------------------------
            if n is None:
                print(TAG+"failed to send datetime")
            elif n > 0:
                print(TAG+f"datetime \'{default_dt}\' sent. Nr of characters: {le}")
                print(TAG+f"contents of the msg= {msg}") # bytearray(b' \x13\x022022-10-06 01:15:00')
                #                                                             /\
                #                                                            \x02 = STX ASCII code (indicates start of datetime)
""" ToDo """
def send_ux():
    pass

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
    global my_debug, ctrl_c_flag
    TAG = "main(): "
    lResult = True
    cnt = 0
    f = ''
    if id.find('pros3') >= 0:
        f = roles_dict[1]
    elif id.find('titano') >= 0:
        f = roles_dict[0]
    time.sleep(5) # Give user time to set up a terminal window or so
    print()
    print('=' * 36)
    print("SERCOM VIA I2C TEST")
    print(f"Running on an {id.upper()}")
    print(f"in the role of {f}")
    print('=' * 36)
    while True:
        try:
            time.sleep(2)
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
