"""
Constants and Pin definitions
"""

PID_DT = 5  # Time in milliseconds between regulator updates


# INA3221 high-current wiring
I2CA_ID = 1
INA_A_SDA_PIN = 2
INA_A_SCL_PIN = 3

# INA3221 low-current wiring
I2CB_ID = 0
INA_B_SDA_PIN = 8
INA_B_SCL_PIN = 9

# I2C Frequency
F = 400000

# PWM definitions
PWM_FREQ = 100000  # PWM frequency in Hz
PWM_RESOLUTION = 65535  # PWM resolution (e.g., 16-bit resolution)

PWM_PIN_CHA = 16  # PWM output for the first channel
PWM_PIN_CHB = 17  # PWM output for the second channel
PWM_PIN_CHC = 18  # PWM output for the third channel

# Regulation parameters
MAX_PWM_INCREMENT= 1000 # Set a limit to the power output rising time

# Range selector pins
RANGE_SELECTOR_PINS = [10,11,12,13,14]  # for 0.1, 1, 10, 100, 1k ohm shunt resistors respectively

# Gross shunt resistor values, common for all channels
SHUNTS= {
    0: 0.1,
    1: 1,
    2: 10,
    3: 100,
    4: 1000
}

# Max current per ammeter range in milliamps
MAX_CURRENTS={
    0: 1e3,
    1: 1e2,
    2: 1e0,
    3: 1e-1,
    4: 1e-2
}

# Max votage before switching a safety relay
MAX_VOLTAGE= 8

# Push-pull output switches status input
PP_SWITCH_CHA= 19
PP_SWITCH_CHB= 20
PP_SWITCH_CHC= 21

# Safety relays control pins
SR_PIN_CHA= 26
SR_PIN_CHB= 27
SR_PIN_CHC= 28

# Safety relays reactivation button
SR_ACTIVATE_PIN= 22