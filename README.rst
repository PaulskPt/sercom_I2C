Introduction
============

This repo has been published because I wanted to share with you the examples contained in this repo.
The examples in this repo are created for the following reason: 


  1. I was doing a project using a 'Flipclock' running on an Adafruit PyPortal Titano (`<https://www.adafruit.com/product/4444>`). 
     However the script running on the Titano crashed because of Memory Errors. I decided that I needed to move certain tasks to another MCU;
  2. For this reason I needed a way for the Titano to send task request messages to the second MCU. 
     The second MCU needed to reply to the task request messages; execute the tasks and send back to the Titano the result of the task.


For the communication between the two MCU's I preferred a serial (UART) connection. I could not make use of the usual UART TX/RX pins because the Titano
has these pins not connected to the 'outside world'. However, both the Titano and the PROS3 have I2C ports.
At first I tried to use the CircuitPython I2CTarget class. I failed to get transmissions working on the I2C-bus.
Thanks to @deshipu on Discord > Adafruit > CircuitPython > #help-with-circuitpython, who hinted me towards 'SERCOM' using I2C,
After receiving this new information, I was able to start a 'Plan B': to let the devices communicate via a serial communication, 
using UART, (CircuitPython busio.UART class) while using the I2C SCL and SDA wires for the communication.
Below the code to create an instance of the UART class:

.. code-block:: python
uart = UART(board.SDA, board.SCL, baudrate=4800, timeout=0, receiver_buffer_size=rx_buffer_len)

As with the usual serial communication via UART, with serial communication via I2C wires it is necessary to have the I2C wires 'crossed':

.. code-block:: shell
SDA (device with role Main) ===> SCL (device with role Sensor)

SCL (device with role Main) ===> SDA (device with role Sensor)
 
To accomplish this, I used a small breadboard and I2C cables (type 4-pin Grove male connector to 4 wires with male MOLEX pins for the Titano), 
(type 4-pin STEMMA/Qwiic male connector to 4 wires with male MOLEX pins for the PROS3). See the image of the hardware setup in the docs folder.

In this example the device with the role 'Main' sends a request immediately after startup. It requests the device with the 
role 'Sensor' (in my case an Unexpected Maker PROS3) to send a datetime message. Next, the same type of request will be repeated at the preset interval time.

After startingup, the device performing the role 'Sensor', will continuously check if there are incoming requests from a device with the role 'Main'.
A request message contans 2 bytes: 
1) the address of the device with a Sensor role, that needs to handle the request;
2) the request code. In this example the code value is (int) 100 (= datetime)

Below a flowchart of the handling of a received request:

.. code-block:: shell
REQUEST (2-byte transmission) received?                           (FLOWCHART)
    > Yes
        > Addressed to me?
            > Yes
                > request code is valid? (exsists?)
                    Yes >
                        > copy request code to global var req_rcvd;
                        > send acknowledge to originator (device with Main role). Next send the requested message (e.g. datetime).
                    > No
                        > Do nothing
            > No
                > Do nothing
    > No
        > Do nothing

After receiving a request, the script of the device with the Sensor role will check: 
a) is the request for me? (address of the request == my address)?
b) is the request code valid?
After the request is parsed and accepted the loop() function with deal with the request.
In this example the loop() function will call function send_dt()
which takes care of the sending of a datetime string to the originator.
After the requested datetime message has been sent, inside the script of the device with the Sensor role,
the control returns back to the loop() function. In case the user interrupts the process with a Keyboard interrupt 
using (CTRL+C) the loop() function will 'signal' to the main() function that the user interrupted and main()
will end the execution of the script with calling 'sys.exit()'.

Meanwhile, in the script running in the device with the Main role, the looping proceeds inside the main() function.
At passing of an interval time, generally two actions will be executed:

.. code-block:: shell
a) call send_dt() to send a datetime request;
b) call ck_uart() to check incoming acknowlegements and incoming replies, in this example: a message containing a datetime.

Also in the script of the Main device the user is able to interrupt the process by typing the key-combination CTRL+C.
Then the execution of this script will be ended by calling 'sys.exit()'.

A word about Terminology
========================
It is maybe a bit weird to name a microcontroller device a 'Sensor'.
The reason is that I followed the recent changes in the CircuitPython documentation, 
see: `<https://docs.circuitpython.org/en/latest/docs/design_guide.html#terminology>`,
where the use of terms as 'Master' and and 'Slave' are labled as 'depricated'.

Final words
===========
Some of you perhaps will ask me: why you need to use a second device to get you a datetime update while, in your case 
the PyPortal Titano itself is able to connect to internet and do a request for a datetime update, e.g.:
using the adafruit_ntp module, using the Adafruit IO Time Service or another NTP Server?

My answer to this question is: 'that is corect'. 
However I was trying to run on the Titano an Adafruit_CircuitPython_DisplayIO_FlipClock 
(`<https://github.com/adafruit/Adafruit_CircuitPython_DisplayIO_FlipClock>`). The flipclock uses bitmapped spritesheets
that consume a big part of the memory at runtime. Then, in my version of that example script, 
there are functions needed for connecting to internet, requesting and handling datetime synchronizations.
Together it appeared that all this consumed too much memory for the PyPortal Titano. Causing memory errors. 
I had to disable an important functionality, 'dynamic fading' (cedargrove_palettefader.py from: 
`<https://github.com/CedarGroveStudios/CircuitPython_PaletteFader>`), to prevent memory errors. 
@foamyguy, the author of the flipclock repo, in an attempt to help me resolve memory errors, created 
smaller bitmapped spritesheets. This helped, however, for my PyPortal Titano not enough.
Thinking about a solution, the idea was 'born' to move the 'overhead' of internet connection, datetime updates
from the Titano to a second device, in my case an Unexpected Maker PROS3, which also has WiFi capability.
The UM PROS3 also has lot more memory than the Titano.
On the other hand the PROS3 lacks a display which the Titano has. Together they could form a nice 'pair'.
This repo is only the first step to the idea of moving the work (and memory) load to a second device. 
It realizes my wish of using the I2C bus for serial communication. As you can read (and please try yourself).
This 'plan B': Sercom I2C, is now working. A logical next step will be adding the script for the device performing the 'Main role'
into the Adafruit_CircuitPython_DisplayIO_FlipClock example script.

Hardware requirements
=====================

- `Adafruit PyPortal Titano <https://www.adafruit.com/product/4444>`
- `Unexpected Maker PROS3 <https://www.adafruit.com/product/5401>`
- `Adafruit Grove to STEMMA QT / Qwiic / JST SH Cable - 100mm long. <https://www.adafruit.com/product/4528>`
- `Seeedstudio Grove - 4 pin Male Jumper to Grove 4 pin Conversion Cable (<https://www.amazon.com/Seeedstudio-Grove-Jumper-Conversion-Cable/dp/B01BYN9OMG>)`
- `Tiny Premium Breadboard. <https://www.adafruit.com/product/65>`
- `Grove Hub e.g.: M5Stack 1 to 3 HUB Expansion Unit. <https://shop.m5stack.com/products/mini-hub-module>`
   or `Grove I2C Hub. <https://www.seeedstudio.com/Grove-I2C-Hub.html>`

Measurement equipment I used:
=============================
- `a Digital Analyzer, e.g.: LA104, e.g.: <https://www.amazon.com/SainSmart-Handheld-4-Channel-Analyzer-Programmable/dp/B07FXDWMKN>`_

Dependencies
=============
This example depends on:

* `Adafruit CircuitPython <https://github.com/adafruit/circuitpython>`_

Examples 
========
The examples consist of two versions: 'Version_01' and 'Version_02'
'Version_01': This version contains the original version of the sercom_I2C scripts.
'Version_02': In this version 'sercom_I2C' forms an itegrated part of an 'Adafruit_DisplayIO_FlipClock' example.
Each of the two versions consist of two scripts:: one for the device performing the role of 'Main' device. 
The second for the device performing the role of 'Sensor' device. 
These two scripts are both in a separate subfolder ('Main' and 'Sensor') in each Version subfolder Examples.
The examples are tested on an Adafruit PyPortal Titano (in the Main role) 
and an Unexpected Maker PROS3 (in the Sensor role).

.. code-block:: shell
Examples:                           (Folder structure)
    > Version_01
        > Main
        
        > Sensor
    
    > Version_02
        > Main
        
        > Sensor
  

Documentation
=============
The documentation can be found in the subfolder 'docs' of this repo.

For information on building library documentation, please check out
`this guide <https://learn.adafruit.com/creating-and-sharing-a-circuitpython-library/sharing-our-docs-on-readthedocs#sphinx-5-1>`_.

Contributing
============

Contributions are welcome! Please read our `Code of Conduct
<https://github.com/adafruit/Adafruit_CircuitPython_DisplayIO_FlipClock/blob/HEAD/CODE_OF_CONDUCT.md>`_
before contributing to help this project stay welcoming.
