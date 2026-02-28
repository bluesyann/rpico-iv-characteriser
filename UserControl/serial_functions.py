import serial
import asyncio
import numpy as np
from time import sleep

import logging
# ✓ ✗ ⚠ ℹ️ ⏳


STANDBY={
    'voffset': 0,
    'sampling': 1,
    'channels':[
        {'Name': 'a','control': 'v'},
        {'Name': 'b','control': 'v'},
        {'Name': 'c','control': 'v'}
    ]
}

SLOW_LOOP_TIME=1
FAST_LOOP_TIME=1e-3
WRITE_DELAY=1e-1


def setup_serial_link(device: str, baud: int, init: dict):
    try:
        ser= serial.Serial(device, baud, timeout=1)
        initialize_channels(init, ser)

        # Purge the serial buffer
        ser.reset_input_buffer()
        return ser
    except Exception as e:
        logging.error(f"Error while setting up serial connection: {e}")
        return None


def close_serial_link(ser: serial.Serial)-> None:
    if ser is not None:
        try:
            initialize_channels(None, ser)
            ser.close()
            logging.info("Serial port closed")
        except Exception as e:
            logging.error(f"Error closing serial port: {e}")


def get_current_config(ser: serial.Serial) -> dict:
    """
    Ask the pico the current state of its switches
    Argument:
        -ser : the serial connection
    Returns:
        -state: dictionnary with the switches state
    """
    logging.info("ℹ️ Asking for the board status...")
    safe_write(ser,"USER PANEL STATE")

    # Wait for an answer
    for _ in range(1,30):
        while ser.in_waiting > 0:
            line = ser.readline().decode('utf-8').strip()
            if line.startswith('STATE'):
                logging.debug(line)
                try:
                    line= line.split(' ')
                    return{
                        'AmmeterRange': line[1],
                        'a_PushPullConnected': line[2],
                        'b_PushPullConnected': line[3],
                        'c_PushPullConnected': line[4],
                        'Communicating': True
                    }
                except Exception as e:
                    logging.error(f"✗ Error parsing board state: {e}")
                    logging.error(f"✗ Line content: {line}")
        sleep(SLOW_LOOP_TIME)
    return{
        'Communicating': False
    }



def wait_until_panel_ready(ser: serial.Serial, init: dict) -> int:
    """
    This function ask the user to actuate panels switches until having
    the configuration required for the measurement
    
    Arguments:
        - serial connection to communicate with the board
        - dictionnary containing the measurement setup
    Returns:
        - Ammeter range switch state (0,1,2,3 or 4)
    """
    ready= False
    range_index= None
    while not ready:
        # Ask for the current switches state
        board_state= get_current_config(ser)
        logging.debug(f"Current board state: {board_state}")
        if not board_state['Communicating']:
            logging.info("ℹ️ Cannot get an answer from the board")
        else:
            try:
                ready= True
                # Check if the current panel switches matche the yaml requirements
                range_index= int(board_state['AmmeterRange']) # current range switch
                if range_index != int(init['range']):
                    logging.info(f"ℹ️ Please set the ammeter range to {init['range']}")
                    ready= False
                for ch in init['channels']:
                    required_state= ch['control']
                    current_state= board_state[f"{ch['Name']}_PushPullConnected"]
                    logging.debug(f"Required state for Ch{ch}: {required_state}")
                    if required_state == 'nc' and current_state == 'True':
                        logging.info(f"ℹ️ Please disable the push-pull output from {ch['Name']}")
                        ready= False
                    if required_state != 'nc' and current_state == 'False':
                        logging.info(f"ℹ️ Please enable the push-pull output on {ch['Name']}")
                        ready= False
            except Exception as e:
                logging.error(f"Error while checking the panel state: {e}")
                ready= False
        sleep(SLOW_LOOP_TIME)
    return range_index



def initialize_channels(init: dict, ser: serial.Serial) -> None:
    logging.info("ℹ️ Initializing channels and time settings...")

    if init is None:
        init= STANDBY

    #Initialize offsets and sampling
    for par in ['voffset','sampling']:
        safe_write(ser, f"set {par} {init[par]}")

    #Initialize channels
    for ch in init['channels']:
        # Send the regulation mode (voltage / current)
        safe_write(ser, f"{ch['Name']} {ch['control']}")
        
        # Send the initial setpoint value
        if 'initvalue' in ch.keys():
            safe_write(ser, f"{ch['Name']} {ch['initvalue']}")
        else:
            safe_write(ser, f"{ch['Name']} 0")
        
        # Send the power limit if available
        if 'max power' in ch.keys():
            safe_write(ser, f"{ch['Name']} {ch['max power']}w")
        else:
            safe_write(ser, f"{ch['Name']} 1w")



def safe_write(ser: serial.Serial, cmd: str) -> None:
    if ser is not None:
        try:
            logging.info(f"ℹ️ Sending to serial {cmd}")
            ser.write(f"{cmd}\n".encode('utf-8'))
            ser.flush()
        except Exception as e:
            logging.error(f"Error while sending data to serial: {e}")
    else:
        logging.error(f"Cant send data to serial, port is not ready")
    sleep(WRITE_DELAY)


async def run_sweep(sweep: dict, ser: serial.Serial) -> bool:
    ch= sweep['channel']
    dt= sweep['timestep']
    logging.info(f"ℹ️ Running channel {ch} sweep with config: {sweep}")
    
    # Convert range to list if needed
    format_sweep_values(sweep)
    logging.debug(f"Sweep values: {sweep['value_list']}")

    for sp in sweep['value_list']:
        logging.info(f"ℹ️ Setting channel {ch} setpoint to: {sp}")
        
        # Prepare command to send to Pico
        safe_write(ser,f"{ch} {sp}")

        await asyncio.sleep(dt)

        # Run another nested sweeps if defined
        if 'sweep' in sweep:
            await run_sweep(sweep['sweep'], ser)
    logging.info(f"✓ Completed sweep for channel {ch}")
    return True


def read_serial_values(ser: serial.Serial, events: list, channels: list)-> None:
    """
    This function reads serial port incoming messages
    If the message contains a row with datapoints, it parses and appends it to each channel data buffers
    If a calib file is available, it will apply the corrections
    If the message contains something else than datapoints, it appends it to the events list

    Arguments:
        - Serial port connection
        - Event list that to be updated
        - List of channels dictionnaries
    """
    if ser.in_waiting > 0:
        line = ser.readline().decode('utf-8').strip()
        logging.debug(f"Received from Pico: {line}")
        
        # Parse the line into a dataframe
        try:
            parts = line.split(' ')
            expected_tokens = 3 * len(channels) + 1
            # If a line don't have the expected number of elements, then it's an event
            if len(parts) != expected_tokens:
                logging.debug(f"Recieved event {line}")
                events.append(line)
            
            else:
                # Get  the raspberry pico time from the first chunk
                t= float(parts[0])

                # Then, parse the channels
                for n, ch in enumerate(channels):
                    logging.debug(f"Parsing channel {ch['Name']}")
                    try:
                        i = parts[3*n + 2]
                        if i != 'None':
                            i= float(i)
                        else: # This happens when switching range
                            i = float('nan')
                    except Exception as e:
                        logging.error(f"Error parsing current for channel {ch['Name']}: {e}")
                        i = float('nan')
                    try:
                        v = parts[3*n + 3]
                        if v != 'None':
                            v= float(v)
                        else: # not supposed to happen
                            v = float('nan')
                    except Exception as e:
                        logging.error(f"Error parsing voltage for channel {ch['Name']}: {e}")
                        v = float('nan')

                    # Apply current offset corrections
                    try:
                        if ch.get('ioffset') is not None:
                            df = ch['ioffset']
                            i_interp = np.interp(v, df['v'].values, df['i'].values, left=0, right=0)
                            i -= i_interp
                            i *= ch.get('icoef', 1)
                    except Exception as e:
                        logging.error(f"✗ Error while correcting current values: {e}")

                    ch['IData'].append(i)
                    ch['VData'].append(v)
                    ch['TData'].append(t)

        except Exception as e:
            logging.error(f"✗ Error parsing line: {e}")
            logging.error(f"✗ Line content: {line}")
                   

async def read_serial_loop(ser: serial.Serial, events: list, channels: list) -> None:
    """
    This function runs read_serial_values() function whtin an async loop
    """
    while True:
        if ser is not None:
            read_serial_values(ser, events, channels)
        await asyncio.sleep(FAST_LOOP_TIME)


def format_sweep_values(sweep: dict) -> None:
    if 'value_list' not in sweep:
        # if range and step provided, generate values
        if 'values' not in sweep:
            try:
                sweep['value_list'] = range_float(sweep['start'], sweep['stop'], sweep['step'])
            except Exception as e:
                logging.error(f"✗ Error generating sweep values: {e}")
        # if values is a string, convert to list
        else:
            try:
                sweep['value_list'] = sweep['values'].split(' ')  # assuming space-separated string
            except Exception as e:
                logging.error(f"✗ Error parsing sweep values: {e}")


def range_float(start, stop, step):
    step=abs(step)  # ensure step is positive

    reversed= False
    if start > stop: # handle decreasing ranges
        buf= start
        start= stop
        stop= buf
        reversed= True

    current = start
    values = []
    while current < stop+0.001:  # Adding a small tolerance to include stop value
        values.append(current)
        current += step
    if reversed:
        values= values[::-1]
    return [round(v, 2) for v in values]