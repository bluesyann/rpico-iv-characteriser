import asyncio
import time
from device import *

# default sampling frequency
sampling_freq = 1

# Current range switch
range_switch= None


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
            message += f"{ch['Name']} {ch['I_Measured']} {ch['V_Measured']} "
        write_serial(message)
        #print("Sending message over UART:", message.strip())
        await asyncio.sleep_ms(int(1000/sampling_freq))  # Send message every second


async def adjust_channel(ch:dict, row:list) -> None:
    try:
        # Case when the user yaml ask for a mesurement with push pull output disconnected
        if row[1] == 'nc':
            print(f"Push pull output not to be used on channel {ch['Name']}")

        # Set the channel to votage regulation
        elif row[1] == 'v':
            if ch['V_SetPoint'] is None: #ignore if already in the right mode
                ch['V_SetPoint'] = 0
                ch['I_SetPoint'] = None
                print(f"Channel {ch['Name']} set to voltage regulation mode")
        
        # Set the channel to current regulation
        elif row[1] == 'i':
            if ch['I_SetPoint'] is None: #ignore if already in the right mode
                ch['V_SetPoint'] = None
                ch['I_SetPoint'] = 0
                print(f"Channel {ch['Name']} set to current regulation mode")

        # Set the setpoint value
        elif is_numeric(row[1]):
            if ch['V_SetPoint'] is not None:
                ch['V_SetPoint']= float(row[1])
                print(f"Channel {ch['Name']}: V_Setpoint set to {float(row[1])}")
            else:
                ch['I_SetPoint']= float(row[1])
                print(f"Channel {ch['Name']}: I_Setpoint set to {float(row[1])}")
        
        # Set the max power value
        elif row[1][-1]=='w':
            mp= row[1][0:-1]
            if float(mp):
                ch['MaxPower']= float(mp)*1000 # Set the power in mW internally
                print(f"Channel {ch['Name']}: Max_Power set to {float(mp)}")
            else:
                print("Cannot parse MaxPower value {mp}")
        else:
            print("Invalid parameter for channel adjustment:", row[1])
    except Exception as e:
        print("Error adjusting channel parameters:", e)


def is_numeric(string):
    try:
        float(string)
        return True
    except ValueError:
        return False


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
                            processed= False
                            row = line.split(' ')
                            if len(row) == 3:
                                if row[1] == 'sampling':
                                    sampling_freq = float(row[2])
                                    print(f"Updated sampling frequency to {sampling_freq} Hz")
                                    processed= True
                                elif row[2] == 'STATE':
                                    send_user_panel_state(channels)
                                    processed= True
                                elif row[1] == 'voffset':
                                    print("Voffset must be implemented")
                                    processed= True
                                #    set_voltage_offset(Ch1, Ch1, Ch1, float(row[2]))
                            elif len(row) == 2:
                                for ch in channels:
                                    if ch['Name']==row[0]:
                                        await adjust_channel(ch, row)
                                        processed= True
                                        break

                            if not processed:
                                print("Unknown command: ", line)

                        except Exception as e:
                            print("Error parsing command:", e)
                        break
        await asyncio.sleep_ms(10)  # Check for incoming data every x ms


def send_user_panel_state(channels: list) -> None:
    """
    Send by serial the position of the range selector switch
    and for each channel the position of the push pull switch
    
    Argument: list of channels
    """
    global range_switch
    message= f"STATE {range_switch}"
    for ch in channels:
        message+=  f" {ch['PushPullConnected']}"
        # If regulation is active, reset the State variable 
        # so that send_channels_state() function will update it
        if ch['PushPullConnected']:
            ch['State']=''
    write_serial(message)


def write_serial(message: str) -> None:
    """
    This function writes the provided message on the serial connection uart1
    """
    message+= '\n'
    uart1.write(message.encode('utf-8'))


async def watch_user_panel_state(channels:list):
    """
    This function check the state of the panel switches
    it updates the shunt resistor values
    Five shunts resistors are available: 0.1, 1, 10, 100 and 1k ohms
    This allows to mesure current in the 1µA - 10A range (with good accuracy?)
    It also check for the push-pull outputs switches state
    """
    print("Starting range selector monitoring...")
    global range_switch
    while True:
        # Read the state of the five GPIO pins of the range selector
        n=0
        selected= None
        for i, _ in enumerate(RANGE_SELECTOR_PINS):
            val= range_selector_pins[i].value()
            n+= val
            if val==0:
                selected= i
        if n==4 and selected is not None:
            if range_switch is None or selected != range_switch:
                print(f"Selected shunt resistor: {selected}")
                for ch in channels:
                    ch['Range']= selected
                    ch['Rshunt'] = SHUNTS[selected]
                range_switch= selected
                write_serial(f"Range {range_switch} selected")
        else:
            print("Invalid shunt resistor selection: ", [pin.value() for pin in range_selector_pins])
            for ch in channels:
                ch['Rshunt'] = None
        
        # Read the state of the push-pull switches
        for ch in channels:
            swstate= bool(ch['SwitchPin'].value())
            if swstate != ch['PushPullConnected']:
                print(f"Push-pull switch set to {swstate} on channel {ch['Name']}")
                ch['PushPullConnected']= swstate
                write_serial(f"CH {ch['Name']} PushPullConnected {swstate}")
        await asyncio.sleep_ms(50)


async def send_channels_state(channels:list):
    while True:
        for ch in channels:
            if ch['SafetyRelayOn'] and ch['PushPullConnected']:
                # Clamp duty cycle to valid range when saturation occurs
                if ch['Duty'] == 0:
                    if ch['State'] != 'Saturation High':
                        print(f"Ch {ch['Name']} running on saturation High")
                        ch['State']= 'Saturation High'
                        write_serial(f"State {ch['Name']} Saturation High")
                elif ch['Duty'] == PWM_RESOLUTION:
                    if ch['State'] != 'Saturation Low':
                        print(f"Ch {ch['Name']} running on saturation Low")
                        ch['State']= 'Saturation Low'
                        write_serial(f"State {ch['Name']} Saturation Low")
                else:
                    if ch['State'] != 'PID Regulation':
                        # Add some hysteresis before getting back to the regulating state
                        if ch['Duty'] < 0.95*PWM_RESOLUTION and ch['Duty'] > 0.05*PWM_RESOLUTION:
                            print(f"Ch {ch['Name']} regulating")
                            ch['State']= 'PID Regulation'
                            write_serial(f"State {ch['Name']} PID Regulation")
        await asyncio.sleep_ms(500)


async def regulator(ch:dict):
    se_old = 0 # Stores the error signal for the derivative calculation
    ise = 0 # Integral of the error signal
    while True:
        try:
            i, v = poll_sensors(ch)
        except Exception as e:
            print(f"Error getting i and v on channel {ch['Name']}: ", e)
            i, v = None, None
    
        # Skip regulation if sensors return None values
        if v is None or i is None:
            await asyncio.sleep_ms(PID_DT)
            continue

        ch['I_Measured'] = i
        ch['V_Measured'] = v

        Ki= 1e-4 # integral gain for voltage regulation
        Kp= 5e-3 # proportional gain for voltage regulation
        Kd= 5e-1 # derivative gain for voltage regulation

        se= 0 #error signal
        if ch['I_SetPoint'] is None and ch['V_SetPoint'] is not None: #Voltage regulation
            se= ch['V_SetPoint']-ch['V_Measured']
        elif ch['V_SetPoint'] is None and ch['I_SetPoint'] is not None: #Current regulation
            """
            Voltage regulation if fairly easy, but it's another story
            for current regulation because the load can vary over six decades...
            The best solution I found is to use an error signal weighted by the current setpoint
            """
            if ch['I_SetPoint'] < 1e-6: #avoid the case of I_SetPoint=0
                ch['I_SetPoint']= 1e-6
            se= 1-ch['I_Measured']/ch['I_SetPoint']

        else:
            print("Error: Cant tell wether voltage or current must be regulated.")
            await asyncio.sleep_ms(PID_DT)
            continue
        
        # PWM Regulation Logic
        ise= se*PID_DT
        dse= (se-se_old)/PID_DT # Derivative of error
        increment= (Kp*se + Kd*dse + Ki*ise)*PWM_RESOLUTION # Required voltage variation for this iteration

        # Apply the rising time limit
        if abs(increment) > MAX_PWM_INCREMENT:
            increment = MAX_PWM_INCREMENT if increment > 0 else -MAX_PWM_INCREMENT
        
        ch['Duty']-= int(increment)
        # Clamp duty cycle to valid range when saturation occurs
        if ch['Duty'] < 0:
            ch['Duty'] = 0
            ise=0 #Reset the integrator
        elif ch['Duty'] > PWM_RESOLUTION:
            ch['Duty'] = PWM_RESOLUTION
            ise=0 #Reset the integrator
        ch['pwm'].duty_u16(ch['Duty'])
    
        # Update old error and damp the integrator
        se_old=se
        ise*=0.99

        await asyncio.sleep_ms(PID_DT)


def update_load(ch: dict) -> float:
    """
    This function calculate the load on the channel by calculating v/i
    To avoid instability, the load is averaged over several iterations
    Iterations are stored in the array 'Load'
    Argument: channel dictionnary
    Returns: average load
    """
    if ch['I_Measured'] != 0:
        R= 1e3*ch['V_Measured'] / ch['I_Measured'] # i is in mA so we need x1e3
    else:
        R=1e6 #If no current, assume a load of 1 Mohm
    
    if len(ch['Load']) > 10: # Remove the oldest value from the array
        ch['Load'].pop(0)
    
    # Update the array with the current load
    ch['Load'].append(R)

    return sum(ch['Load']) / len(ch['Load'])


async def do_nothing():
    """
    Simple async function that does nothing, used to keep the event loop running when there are no other tasks.
    It's supposet to improve the accuracy of the timing of the other tasks by yielding control back to the event loop more frequently.
    """
    while True:
        await asyncio.sleep_ms(0)


def poll_sensors(ch:dict) -> tuple:
    try:
        # Get the data from the High Current device (range=0)
        if ch['Range']==0:
            v = ch['HigIDevice'].bus_voltage(ch['BusId'])
            i = 1e3*ch['HigIDevice'].current(ch['BusId'])* 0.1 # current() function assumes a shunt resistor of 0.1 ohm, so we need to multiply by 10 to get the correct current for our shunt resistors
            #print(f"High-I sensor values: {v}, {i}")
        # Or get it from the low Current device (range>0)
        else:
            v = ch['LowIDevice'].bus_voltage(ch['BusId'])
            i = 1e3*ch['LowIDevice'].current(ch['BusId'])* 0.1
            #print(f"Low-I sensor values: {v}, {i}")


        # Wait for the shunt resistor to have a value
        if ch['Rshunt'] is None:
            print(f"Shunt undefined for channel {ch['Name']}")
            return (None, v)
        
        # Correct the current regarding the shunt resistor value
        i/= ch['Rshunt'] # correct the current regarding the shunt resistor value
        #print("Polled values on ch",ch['Name'], i, v)
        #time.sleep(0.5)
        return (i, v)
    
    except Exception as e:
        print(f"Error polling sensors on channel {ch['Name']}: ", e)
        # Disconnect the safety relay since we lost communication with sensors
        ch['SafetyRelayOn']= False
        ch['SafetyRelayPin'].value(1)
        return (None, None)



def get_values(ch:dict):
    try:
        i, v = poll_sensors(ch)
        
        # update the channel dictionary
        ch['I_Measured'] = i
        # add a logic later to choose between highI and lowI based on the value
        ch['V_Measured'] = v
        return True
    except Exception as e:
        print(f"Error getting i and v on channel {ch['Name']}: ", e)
        return False



async def test_pwm_output():
    """
    This function simply sweep the pwm duty cycle from 0 to max
    and measure to voltage after the push pull to verify if the conversion from duty cycle to voltage is correct.
    """
    for duty in range(0, PWM_RESOLUTION+1, 1000):
        pwma.duty_u16(duty)
        #print(f"Set duty cycle to {duty}/{PWM_RESOLUTION}")
        pwma.duty_u16(duty)
        await asyncio.sleep(0.5)
        # get the voltage after the push pull
        v = inaA.bus_voltage(1)  # Assuming channel 1 is connected to the push-pull output
        #print(f"Measured voltage: {v} V")
        print(f"{duty}\t{v}")


async def safety_relays_control(channels:list)-> None:
    """
    This function monitors current, voltage and power on each channel
    It checkes for
        - the voltage and current limits givent in congif.py (board protection)
        - user-defined MaxPower variable set for each channel (measured device protection)
    A the safety relay is triggered if a value is exceeded
    Then the user has to press a button to reactivate the output
    """
    # On startup, activate all the realys
    for ch in channels:
        ch['SafetyRelayPin'].value(0)
    # Then we get in the monitoring loop
    while True:
        await asyncio.sleep_ms(100)
        for ch in channels:
            currently_on= ch['SafetyRelayOn']
            v= ch['V_Measured']
            i= ch['I_Measured']
            message=""
            # Voltage limit
            if v is not None and v > MAX_VOLTAGE:
                ch['SafetyRelayOn']= False
                message="Max voltage reached"
            # Current limit
            if ch['Range'] is not None and i is not None:
                if i > MAX_CURRENTS[ch['Range']]:
                    ch['SafetyRelayOn']= False
                    message="Max current reached"
            # Power limit
            if ch['MaxPower'] is not None and v is not None and i is not None:
                if i*v > ch['MaxPower']:
                    ch['SafetyRelayOn']= False
                    message="Max power reached"
            # Actuate the relay is a change was detected
            if ch['SafetyRelayOn'] != currently_on:
                ch['SafetyRelayPin'].value(1)
                print(f"Ch {ch['Name']}: SafetyRelayOn Going from {currently_on} to {ch['SafetyRelayOn']}")
                ch['State']='Alert'
                write_serial(f"CH {ch['Name']} Alert {message}")
        
        # Check if the user is holding the reactivation button
        buttonstate= not bool(sractivate.value())
        if buttonstate:
            print("User-button pressed, reactivating all safety switches...")
            for ch in channels:
                ch['SafetyRelayOn']= True
                ch['SafetyRelayPin'].value(0)
                # Update the push-pull switch state to refresh the textbox showing the board status
                write_serial(f"CH {ch['Name']} PushPullConnected {ch['PushPullConnected']}")



async def main():
    print("Starting the program...")

    # Define channels parameters
    channels = [
        {'Name': 'a',
        'V_SetPoint': 0,  # Target voltage in volts
        'I_SetPoint': None,  # Target current in milliamps
        'MaxPower': None,
        'V_Measured': None,
        'I_Measured': None,
        'Range': None,
        'Rshunt': None,
        'Load': [],
        'Duty': 0,
        'PushPullConnected': True,
        'State': '',
        'SafetyRelayPin': sra,
        'SafetyRelayOn': True,
        'SwitchPin': ppswitcha,
        'pwm': pwma,
        'HigIDevice': inaA,
        'LowIDevice': inaB,
        'BusId': 1},
        
        {'Name': 'b',
        'V_SetPoint': 0,  # Target voltage in volts
        'I_SetPoint': None,  # Target current in milliamps
        'MaxPower': None,
        'V_Measured': None,
        'I_Measured': None,
        'Range': None,
        'Rshunt': None,
        'Load': [],
        'Duty': 0,
        'PushPullConnected': False,
        'State': '',
        'SafetyRelayPin': srb,
        'SafetyRelayOn': True,
        'SwitchPin': ppswitchb,
        'pwm': pwmb,
        'HigIDevice': inaA,
        'LowIDevice': inaB,
        'BusId': 2},

        {'Name': 'c',
        'V_SetPoint': 0,  # Target voltage in volts
        'I_SetPoint': None,  # Target current in milliamps
        'MaxPower': None,
        'V_Measured': None,
        'I_Measured': None,
        'Range': None,
        'Rshunt': None,
        'Load': [],
        'Duty': 0,
        'PushPullConnected': False,
        'State': '',
        'SafetyRelayPin': src,
        'SafetyRelayOn': True,
        'SwitchPin': ppswitchc,
        'pwm': pwmc,
        'HigIDevice': inaA,
        'LowIDevice': inaB,
        'BusId': 3}
    ]

    # Start range selector monitoring task
    asyncio.create_task(watch_user_panel_state(channels))

    # Start serial communication task
    asyncio.create_task(serial_write(channels))
    asyncio.create_task(serial_read(channels))
    asyncio.create_task(send_channels_state(channels))

    # Start the regulation tasks
    for ch in channels:
        asyncio.create_task(regulator(ch))

    # Safety relays task
    asyncio.create_task(safety_relays_control(channels))
    
    # Start do_nothing task to keep the event loop running
    asyncio.create_task(do_nothing())



# Create an Event Loop
loop = asyncio.get_event_loop()
# Create a task to run the main function
loop.create_task(main())
#loop.create_task(test_pwm_output())

try:
    # Run the event loop indefinitely
    loop.run_forever()
except Exception as e:
    print('Error occurred: ', e)
except KeyboardInterrupt:
    print('Program Interrupted by the user')