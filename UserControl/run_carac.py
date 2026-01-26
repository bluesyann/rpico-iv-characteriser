from pathlib import Path
import yaml
import pandas as pd
import serial
import asyncio
from time import sleep
import matplotlib.pyplot as plt
from pathlib import Path

plt.ion()  # Enable interactive mode

"""Virtual environment peripheral settings

python3 -m venv venv
source venv/bin/activate
pip install pyserial pyyaml pandas
"""

PERIPHERAL= '/dev/ttyACM1'
PERIPHERAL_BAUDRATE = 115200
PLOT_INTERVAL = 1.0  # seconds

def read_yaml(filepath: Path):
    config = {}
    try:
        print(f"Parsing yaml file at: {filepath}")
        with open(filepath, 'r') as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                config = loaded
    except Exception as e:
        print(f"Error opening file: {e}")
    return config


def format_sweep_values(sweep: dict) -> None:
    if 'value_list' not in sweep:
        # if range and step provided, generate values
        if 'values' not in sweep:
            try:
                sweep['value_list'] = range_float(sweep['start'], sweep['stop'], sweep['step'])
            except Exception as e:
                print(f"Error generating sweep values: {e}")
        # if values is a string, convert to list
        else:
            try:
                sweep['value_list'] = sweep['values'].split(' ')  # assuming space-separated string
            except Exception as e:
                print(f"Error parsing sweep values: {e}")


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


standby={
    'init':{
        'ch1':
            {'v':0},
        'ch2':
            {'v':0},
        'ch3':
            {'v':0}
    },
    'setup':{
        'voffset': 0,
        'sampling': 1
    }
}


def initialize_channels(config: dict, ser: serial.Serial) -> None:
    print("Initializing channels and time settings...")
    if 'init' not in config:
        return
    for ch in config['init']:
        key= list(config['init'][ch].keys())[0]
        cmd=f"{ch} {key} {config['init'][ch][key]}"
        print(f"Initializing {cmd}")
        ser.write(f"{cmd}\n".encode('utf-8'))
        ser.flush()
        sleep(0.1)  # small delay to ensure command is processed
    for param in config['setup']:
        cmd=f"set {param} {config['setup'][param]}"
        print(f"{cmd}")
        ser.write(f"{cmd}\n".encode('utf-8'))
        ser.flush()
        sleep(0.1)  # small delay to ensure command is processed


async def run_sweep(config: dict, ser: serial.Serial) -> bool:
    if 'sweep' not in config:
        return False
    sweep=config['sweep']
    ch= sweep['channel']
    dt= sweep['timestep']
    print(f"Running {ch} sweep with config: {sweep}")
    
    # Convert range to list if needed
    format_sweep_values(sweep)
    print(f"Sweep values: {sweep['value_list']}")

    for sp in sweep['value_list']:
        print(f"Setting {ch} setpoint to: {sp}")
        
        # Prepare command to send to Pico
        key= list(ch.keys())[0]
        cmd=f"{key} {ch[key]} {sp}"
        ser.write(f"{cmd}\n".encode('utf-8'))
        ser.flush()

        await asyncio.sleep(dt)

        # Run another nested sweeps if defined
        if 'sweep' in sweep:
            await run_sweep(sweep, ser)
    print(f"Completed sweep for channel: {ch}")
    await asyncio.sleep(PLOT_INTERVAL) # wait a bit before finishing to update the plot
    return True



async def read_serial_values(ser: serial.Serial, rows: list) -> dict:
    """
    Docstring for get_values
    """
    # timestamp for the beggining of the reading
    start= asyncio.get_event_loop().time()
    while True:
        if ser.in_waiting > 0:
            line = ser.readline().decode('utf-8').strip()
            #print(f"Received from Pico: {line}")
            
            # Parse the line into a dataframe
            try:
                _, i1, v1, _, i2, v2, _, i3, v3 = line.split(' ')
                rows.append({
                    't': asyncio.get_event_loop().time() - start,
                    'i1': float(i1),
                    'v1': float(v1),
                    'i2': float(i2),
                    'v2': float(v2),
                    'i3': float(i3),
                    'v3': float(v3),
                })
                #print(f"Collected {len(rows)} rows")
            except Exception as e:
                print(f"Error parsing line: {e}")
                print(f"Line content: {line}")
        await asyncio.sleep(1e-3)


async def plot_values(rows: list, set: dict):
    _, ax = plt.subplots()
    print(f"Starting plot for {set}")
    while True:
        if len(rows) > 5:
            df = pd.DataFrame(rows)
            print(f"Plotting {len(df)} data points")
            
            ax.clear()  # Clear the axes
            ax.scatter(df[set['x']], df[set['y']], color='black')
            ax.set_xlabel(set['xlabel'])
            ax.set_ylabel(set['ylabel'])
            ax.set_title(set['name'])
            ax.grid()
            plt.draw()  # Update the plot
            plt.savefig(set['file']) # Save the figure to file
            plt.pause(0.01)  # Small pause to allow rendering
            
        await asyncio.sleep(PLOT_INTERVAL)


async def main():

    file= Path('/home/yann/Bureau/Electronique/Caracterieur_run/current_gen.yaml')
    dir= file.parents[0]
    config = read_yaml( Path(file).resolve() )

    # Execute required electical characterization based on configurations
    for c in config.keys():
        if 'carac' not in c.lower():
            continue
        print(f"Running electrical characterization: {c}")

        # Setting up the pico to the sampling rate and time step
        ser= serial.Serial(PERIPHERAL, PERIPHERAL_BAUDRATE)
        initialize_channels(config[c], ser)
        rows= []

        # Define async tasks for reading serial values and running sweeps
        task_list=[]
        task_list.append(asyncio.create_task(read_serial_values(ser, rows)))
        task_list.append(asyncio.create_task(run_sweep(config[c], ser)))

        # prepare the list of plots to generate
        for plot in config[c].keys():
            if 'plot' in plot.lower():
                task_list.append(asyncio.create_task(plot_values(rows, config[c][plot])))

        _, pending = await asyncio.wait(
            task_list,
            return_when=asyncio.FIRST_COMPLETED
        )

        print("First task completed. Cancelling others...")
        for task in pending:
            task.cancel()

        # Wait for cancellation to be processed
        try:
            await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            pass


        # Reset to standby after the sweep
        initialize_channels(standby, ser)


        data = pd.DataFrame(rows)
        outfile= dir / config[c]['datafile']
        data.to_csv(outfile, index=False)
        print(f"Results saved to {outfile}")

        input("Press any key to exit...") # allows to keep the graph open


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        print('Error occurred: ', e)
    except KeyboardInterrupt:
        print('Program Interrupted by the user')

