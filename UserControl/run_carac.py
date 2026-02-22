from pathlib import Path
import yaml
from jsonschema import validate, ValidationError
import pandas as pd
import asyncio

import matplotlib.pyplot as plt
plt.ion()  # Enable interactive mode

import os
def is_valid_file(parser, arg):
    if not os.path.isfile(arg):
        parser.error(f"The file {arg} does not exist!")
    else:
        return Path(arg)


import argparse
parser = argparse.ArgumentParser(description='Run voltage sweeps or monitor the multichannel Voltage/Current sensing inteface.')
parser.add_argument('file', type=lambda x: is_valid_file(parser, x), help='YAML file describing the process.')
parser.add_argument('-device', type=str, default='/dev/ttyACM0', help='Path to the Raspberry Pico device.')
parser.add_argument('-baud', type=int, default=115200, help='Baud rate for serial communication.')
parser.add_argument('-d', '--debug', action='store_true', help='Activate debug logging.')
args = parser.parse_args()

import logging
level = logging.DEBUG if args.debug else logging.INFO
logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(message)s')
# ✓ ✗ ⚠ ℹ️ ⏳ 
#\033[91m✗\033[0m
#\033[92m✓\033[0m
#\t→
#\033[93m●

import serial_functions as serfn
import calib_functions as calfn


"""Virtual environment peripheral settings

python3 -m venv venv
source venv/bin/activate
pip install pyserial pyyaml pandas
"""

"""
Decouple plotting: Move plotting out of the asyncio loop (separate process) so matplotlib I/O and rendering cannot interfere with sampling. The main loop should only provide data copies.
Graceful shutdown: Handle signals (SIGINT, SIGTERM) to stop tasks/processes cleanly, flush data to CSV, and join worker processes.
provide a requirements.txt for reproducible venvs.
Unit tests & CI: Add tests for parsing, range_float, resample_xy, and calibration coefficient calculations. Run tests in CI to catch regressions.
Code quality: Add type hints, small docstrings, move reusable logic into modules, and run flake8/black for consistency. Replace magic numbers (sleep intervals) with named constants.
"""

PLOT_INTERVAL = 1.0  # seconds


def read_yaml(filepath: Path):
    config = {}
    try:
        logging.info(f"ℹ️ Parsing yaml file at: {filepath}")
        with open(filepath, 'r') as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                config = loaded
    except Exception as e:
        logging.error(f"✗ Error opening file: {e}")
    return config


def validate_yaml(data_file: Path, schema_file: Path) -> bool:
    # Load YAML files
    with open(data_file) as f:
        data = yaml.safe_load(f)
    with open(schema_file) as f:
        schema = yaml.safe_load(f)
    
    try:
        validate(instance=data, schema=schema)
        logging.info("✓ Valid YAML!")
        return True
    except ValidationError as e:
        logging.error(f"✗ Validation failed: {e.message}")
        return False


async def static_run(static: dict) -> None:
    duration= static['duration']
    logging.info(f"⏳ getting data for {duration} seconds...")
    await asyncio.sleep(duration)
    logging.info("✓ Static run completed.")


async def plot_values(rows: list, par: dict, dir: Path):
    _, ax = plt.subplots()
    logging.info(f"ℹ️ Starting plot for {par}")
    while True:
        if len(rows) > 5:
            df = pd.DataFrame(rows)
            #logging.debug(f"Plotting {len(df)} data points")
            
            ax.clear()  # Clear the axes
            for y in par['y']:
                ax.scatter(df[par['x']], df[y], label=y)
            ax.set_xlabel(par['xlabel'])
            ax.set_ylabel(par['ylabel'])
            ax.set_title(par['name'])
            ax.grid()
            plt.draw()  # Update the plot
            if 'file' in par:
                plt.savefig(dir / par['file']) # Save the figure to file
            plt.pause(0.01)  # Small pause to allow rendering
            
        await asyncio.sleep(PLOT_INTERVAL)


async def main():

    file= args.file
    dir= file.parents[0]

    # Validate YAML against schema
    schema= Path('schema.yaml')
    if not validate_yaml(file, schema):
        return
    
    # Load configuration using helper that opens the file
    config = read_yaml(file)

    # Execute required electical characterization based on configurations
    for c in config['caracs']:
        logging.info(f"ℹ️ Running electrical characterization: {c.get('name')}")

        # Setting up the pico to the sampling rate and time step
        ser= serfn.setup_serial_link(args.device, args.baud, c['init'])

        # Make sure panel switches are at their right position
        range= serfn.wait_until_panel_ready(ser, c['init'])

        # Load the calibration files
        if 'calibration folder' in config:
            calfn.load_calibration_files(range, serfn.channels, Path(config['calibration folder']))

        # Define async tasks for reading serial values and running sweeps
        rows= []
        task_list=[]
        task_list.append(asyncio.create_task(serfn.read_serial_values(ser, rows, serfn.channels)))
        if 'sweep' in c:
            task_list.append(asyncio.create_task(serfn.run_sweep(c['sweep'], ser)))
        elif 'static' in c:
            # if no sweep defined, just wait for the specified duration while reading values
            task_list.append(asyncio.create_task(static_run(c['static'])))
        else:
            logging.error("✗ No sweep or static defined in the configuration. Exiting.")
            serfn.initialize_channels(None, ser)
            continue

        # prepare the list of plots to generate
        if 'plots' in c:
            for p in c['plots']:
                task_list.append(asyncio.create_task(plot_values(rows, p, dir)))

        _, pending = await asyncio.wait(
            task_list,
            return_when=asyncio.FIRST_COMPLETED
        )

        logging.info("✓ First task completed. Cancelling others...")
        for task in pending:
            task.cancel()

        # Wait for cancellation to be processed
        try:
            await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            pass

        # Reset to standby after the sweep
        serfn.initialize_channels(None, ser)

        if 'datafile' in c:
            data = pd.DataFrame(rows)
            outfile= dir / c['datafile']
            data.to_csv(outfile, index=False)
            logging.info(f"✓ Results saved to {outfile}")

        input("Press any key to end this characterization") # allows to keep the graph open


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error('✗ Error occurred: ', e)
    except KeyboardInterrupt:
        logging.error('✗ Program Interrupted by the user')