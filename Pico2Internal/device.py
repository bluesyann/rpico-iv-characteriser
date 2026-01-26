"""
Initialize the hardware components: I2C, ADC, PWM, and SPI.
"""

from machine import I2C, Pin, PWM, UART
from ina3221 import INA3221
from config import *

# Fisrt INA3221

i2cA = I2C(1,
          scl=Pin(INA_A_SCL_PIN),
          sda=Pin(INA_A_SDA_PIN),
          freq=F)

inaA = INA3221(i2cA, i2c_addr=0x40, shunt_resistor=SR_A)

for channel in range(1, 4): # Enable all 3 channels
    inaA.enable_channel(channel)


# PWM Initialization

pwm1 = PWM(
        Pin(PWM_PIN_1),
        freq=PWM_FREQ,
        duty_u16=0
    )

# Serial Initialization

uart1 = UART(1, baudrate=115200, tx=Pin(4), rx=Pin(5))
uart1.init(115200)