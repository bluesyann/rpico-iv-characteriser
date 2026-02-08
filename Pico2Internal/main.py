import asyncio
import time
from device import *

# default sampling frequency
sampling_freq = 1

async def serial_write(channels:list):
    global sampling_freq
    while True:
        # Update all channel measurements
        for ch in channels:
            get_values(ch)
        
        # Get current time in seconds since the program started
        current_time = time.ticks_ms() / 1000

        # send the values of all channels over UART
        message=f"{current_time} "
        for ch in channels:
            message += f"{ch['Id']} {ch['I_Measured']} {ch['V_Measured']} "
        message+= '\n'

        uart1.write(message.encode('utf-8'))
        #print("Sending message over UART:", message.strip())
        await asyncio.sleep_ms(int(1000/sampling_freq))  # Send message every second


def adjust_channel(ch:dict, row:list) -> None:
    if row[1] == 'v':
        ch['V_SetPoint'] = float(row[2])
        ch['I_SetPoint'] = None  # Switch to voltage regulation mode
        print(f"Updated V_SetPoint to {ch['V_SetPoint']} V")
    elif row[1] == 'i':
        ch['I_SetPoint'] = float(row[2])
        ch['V_SetPoint'] = None  # Switch to current regulation mode
        print(f"Updated I_SetPoint to {ch['I_SetPoint']} mA")
    else:
        print("Invalid parameter for channel adjustment:", row[1])


async def serial_read(channels:list):
    global sampling_freq
    serial_buffer = ""
    while True:
        if uart1.any():
            data = uart1.read(uart1.any())
            if data is not None:
                # Append new data to buffer
                serial_buffer += data.decode('utf-8')
                
                # Process complete lines (ending with \n or \r)
                while '\n' in serial_buffer:
                    # Split on \n
                    if '\n' in serial_buffer:
                        line, serial_buffer = serial_buffer.split('\n', 1)
                        line = line.strip()
                        
                        # Skip empty lines
                        if not line:
                            break
                        
                        print("Received data over UART:", line)
                        # parse and update setpoints if needed
                        try:
                            row = line.split(' ')
                            if len(row) != 3:
                                print("Invalid command format: ", row)
                                break
                            if row[0] == 'ch1':
                                adjust_channel(channels[0], row)
                            #elif row[0] == 'ch2':
                            #    adjust_channel(channels[1], row)
                            #elif row[0] == 'ch3':
                            #    adjust_channel(channels[2], row)
                            #if row[1] == 'voffset':
                            #    set_voltage_offset(Ch1, Ch1, Ch1, float(row[2]))
                            elif row[1] == 'sampling':
                                sampling_freq = float(row[2])
                                print(f"Updated sampling frequency to {sampling_freq} Hz")
                            else:
                                print("Unknown command: ", line)

                        except Exception as e:
                            print("Error parsing command:", e)
                        break
        await asyncio.sleep_ms(10)  # Check for incoming data every x ms


async def regulator(ch:dict, pwm:PWM):
    se_old = 0
    dse_old = 0
    while True:
        id= ch['Id']
        i, v = poll_sensors(ch)

        # PWM Regulation Logic
        m, n, p= ch['mv'], ch['nv'], ch['pv']
        if ch['I_SetPoint'] is None:
            # Voltage Regulation Mode (Not implemented in this example)
            se= ch['V_SetPoint'] - v #error signal
        else:
            # Current Regulation Mode - We first need to estimate the impedance of the load to convert the voltage setpoint to a current setpoint, then we can use the same PID controller as for voltage regulation
            R= abs(v/i) if i != 0 else 1e-1 # current in mA so R in kiloohms
            # Keep R between 10 omhs and 1 Mohm to avoid instability and unrealistic values
            if R < 1e-3:
                R=1e-3
            if R > 1e3:
                R=1e3
            print(f"R={R}")
            se= R*( ch['I_SetPoint'] - i ) #error signal in volts (mA * kW)
            #m, n, p= ch['mi'], ch['ni'], ch['pi']
        # Derivative of error
        dse= se-se_old
        # Second derivative of error
        d2se= dse - dse_old
        ch['Duty'] -= int( ( m*se + n*dse + p*d2se ) * PWM_RESOLUTION)
        
        # Update old errors
        se_old=se
        dse_old=dse
        
        #print(f"{id} Duty: {ch['Duty']}")
        #ch['Duty']= 52000
        # Clamp duty cycle to valid range
        if ch['Duty'] < 0:
            ch['Duty'] = 0
        elif ch['Duty'] > PWM_RESOLUTION:
            ch['Duty'] = PWM_RESOLUTION
        pwm.duty_u16(ch['Duty'])
        
        if False:
            print(f"{id} i: {i} mA")
            print(f"{id} v: {v} V")
            print(f"{id} Duty: {ch['Duty']}/{PWM_RESOLUTION}")
            print("---------------------------")
        await asyncio.sleep_ms(REGULATOR_SLEEP_TIME)


async def do_nothing():
    """
    Simple async function that does nothing, used to keep the event loop running when there are no other tasks.
    It's supposet to improve the accuracy of the timing of the other tasks by yielding control back to the event loop more frequently.
    """
    while True:
        await asyncio.sleep_ms(0)


def poll_sensors(ch:dict) -> tuple:
    try:
        lci = 1e3*ch['lowI']['device'].current(ch['lowI']['ch'])
        hci = 1e3*ch['highI']['device'].current(ch['highI']['ch'])
        v = ch['V']['device'].bus_voltage(ch['V']['ch'])

        # Correct the readings based on calibration factors
        lci*= ch.get('Rlow_correction', 1)
        hci*= ch.get('Rhigh_correction', 1)

        # Select which current measurement to use based on the setpoint
        i= lci
        if i > ch.get('Iswitch', 100):
            i= hci
        return (i, v)
    except Exception as e:
        print(f"Error polling sensors on {ch['Id']}: ", e)
        return (None, None, None)


def get_values(ch:dict):
    try:
        i, v = poll_sensors(ch)
        
        # update the channel dictionary
        ch['I_Measured'] = i
        # add a logic later to choose between highI and lowI based on the value
        ch['V_Measured'] = v
        return True
    except Exception as e:
        print(f"Error getting values on {ch['Id']}: ", e)
        return False


async def main():
    print("Starting the program...")

    # Define fisrt channel parameters
    Ch1={
        'V_SetPoint': 0,  # Target voltage in volts
        'I_SetPoint': None,  # Target current in milliamps (none since we are regulating voltage
        'V_Measured': None,
        'I_Measured': None,
        'Rlow_correction': 1,
        'Rhigh_correction': 1,
        'Iswitch': 50,
        'Duty': 0,
        'mv': 2e-3, # integral gain for voltage regulation
        'nv': 2e-2, # proportional gain for voltage regulation
        'pv': 1e-1, # derivative gain for voltage regulation
        'mi': 1e-5, # integral gain for current regulation
        'ni': 1e-4, # proportional gain for current regulation
        'pi': 1e-3, # derivative gain for voltage regulation
        'Id': 'Ch1',
        'SamplingFreq': 1, # in Hz
        'Info': 'VoltageRegulation',
        # low-current measurement channel
        'lowI': {
            'device': inaA,
            'ch': 2
        },
        # high-current measurement channel
        'highI': {
            'device': inaA,
            'ch': 1
        },
        # voltage measurement channel (taken after the two shunt resistors)
        'V': {
            'device': inaA,
            'ch': 1
        }
    }

    # Start voltage regulation task for Channel 1
    asyncio.create_task(regulator(Ch1, pwm1))

    # Start serial communication task
    channels = [Ch1,Ch1,Ch1]  # List of all channels
    asyncio.create_task(serial_write(channels))
    asyncio.create_task(serial_read(channels))

    # Start do_nothing task to keep the event loop running
    asyncio.create_task(do_nothing())



# Create an Event Loop
loop = asyncio.get_event_loop()
# Create a task to run the main function
loop.create_task(main())

try:
    # Run the event loop indefinitely
    loop.run_forever()
except Exception as e:
    print('Error occurred: ', e)
except KeyboardInterrupt:
    print('Program Interrupted by the user')