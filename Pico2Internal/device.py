"""
Initialize the hardware components: I2C, ADC, PWM, and SPI.
"""

from machine import I2C, Pin, PWM, UART
from ina3221 import INA3221
from config import *


# High-current INA3221
i2cA = I2C(I2CA_ID,
          scl=Pin(INA_A_SCL_PIN),
          sda=Pin(INA_A_SDA_PIN),
          freq=F)
inaA = INA3221(i2cA, i2c_addr=0x40)

# Low-current INA3221
i2cB = I2C(I2CB_ID,
          scl=Pin(INA_B_SCL_PIN),
          sda=Pin(INA_B_SDA_PIN),
          freq=F)
inaB = INA3221(i2cB, i2c_addr=0x40)

for channel in range(1, 4): # Enable all 3 channels
    inaA.enable_channel(channel)
    inaB.enable_channel(channel)


# PWM Initialization

pwma = PWM(
        Pin(PWM_PIN_CHA),
        freq=PWM_FREQ,
        duty_u16=PWM_RESOLUTION # Start with 100% duty cycle, meaning 0 after the inverter
    )

pwmb = PWM(
        Pin(PWM_PIN_CHB),
        freq=PWM_FREQ,
        duty_u16=PWM_RESOLUTION # Start with 100% duty cycle, meaning 0 after the inverter
    )

pwmc = PWM(
        Pin(PWM_PIN_CHC),
        freq=PWM_FREQ,
        duty_u16=PWM_RESOLUTION # Start with 100% duty cycle, meaning 0 after the inverter
    )


# Serial Initialization

uart1 = UART(1, baudrate=115200, tx=Pin(4), rx=Pin(5))
uart1.init(115200)

# Range selector pins initialization
# Set to input with pull-up resistors, assuming the shunt resistor selection is done by connecting the corresponding pin to gnd
range_selector_pins = [Pin(pin_num, Pin.IN, Pin.PULL_UP) for pin_num in RANGE_SELECTOR_PINS]


# PushPull switches lookup pins
ppswitcha= Pin(PP_SWITCH_CHA, Pin.IN, Pin.PULL_UP)
ppswitchb= Pin(PP_SWITCH_CHB, Pin.IN, Pin.PULL_UP)
ppswitchc= Pin(PP_SWITCH_CHC, Pin.IN, Pin.PULL_UP)

# Safetey relays pins
sra= Pin(SR_PIN_CHA, Pin.OUT)
srb= Pin(SR_PIN_CHB, Pin.OUT)
src= Pin(SR_PIN_CHC, Pin.OUT)

# Safety relays reactivation button
sractivate= Pin(SR_ACTIVATE_PIN, Pin.IN, Pin.PULL_UP)