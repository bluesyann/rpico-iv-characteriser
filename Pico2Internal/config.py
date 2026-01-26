"""
Constants and Pin definitions
"""

REGULATOR_SLEEP_TIME = 0.0001  # Time in seconds between regulator updates

# Fisrt INA3221 wiring
INA_A_SDA_PIN = 2
INA_A_SCL_PIN = 3
# Shunt resistors for channels 1, 2, and 3 in ohms
SR_A = (0.1, 0.5, 0.1)  

# I2C Frequency
F = 400000

# PWM definitions
PWM_FREQ = 100000  # PWM frequency in Hz
PWM_RESOLUTION = 65535  # PWM resolution (e.g., 16-bit resolution)

PWM_PIN_1 = 15  # PWM output for the first channel