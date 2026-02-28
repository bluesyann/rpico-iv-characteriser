from pathlib import Path
import pandas as pd
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.stats import linregress

import logging
# ✓ ✗ ⚠ ℹ️ ⏳


OFFSETS_I_FILENAME= 'offsets_i_noload_range'
COEFFS_I_FILENAME= 'coeffs_i'

def load_calibration_files(r: int, channels: list, dir: Path):
    """Load calibration files for ammeter range r (0-4)"""
    
    file= dir / f"{OFFSETS_I_FILENAME}{r}.dat"
    logging.info(f"ℹ️ Trying to read offset file {file}...")
    df=pd.DataFrame
    try:
        df = pd.read_csv(file)
        logging.info(f"✓ Loaded {len(df)} calibration points")
    except Exception as e:
        logging.warning(f"⚠ No calibration available for range {r}: {e}")
    
    # Process channels if data loaded
    if not df.empty:
        cols= df.columns.to_list()
        logging.debug(f"dataframe columns: {cols}")
        for ch in channels:
            n= ch['Name']
            i, v = f"i{n}", f"v{n}"
            if v in cols and i in cols:
                logging.info(f"ℹ️ Loading current offsets for channel {n}")
                cal = df[[i, v]]
                cal = cal.sort_values(v).reset_index(drop=True)
                ch['ioffset'] = resample_xy(cal, v, i, 300, 3)\
                            .rename(columns={v: 'v', i: 'i'})
            else:
                logging.warning(f"Column {v} or {i} are missing from I offsets table")


    logging.info(f"ℹ️ Getting Ammeters coeficients for range {r}...")
    try:
        #Get the apropriate file
        for f in dir.iterdir():
            if f.name.startswith(COEFFS_I_FILENAME) \
                and f.name.endswith(f"range{r}.dat"):
                # Get the resistor value from the filename _R1k_range
                R= f.name.split('_')[2][1:-1]
                logging.info(f"✓ Found a file for R={R} kOmhs ({f.name})")

                df= pd.DataFrame
                df = pd.read_csv(f)
                logging.debug(f"✓ Loaded {len(df)} calibration points")
                if not df.empty:
                    calculate_ammeter_coefs(df, float(R), channels, 'va')
    except Exception as e:
        logging.warning(f"⚠ Cannot set a current coefficient for range {r}: {e}")

def calculate_ammeter_coefs(df: pd.DataFrame, R: float, channels: list, chvref: str):
    """
    This fuction performs a linear fit of the I(V) charateristics measured
    with a reference resistir R. It returns a scaling factor for each channel
    to match Ohm's law expectations
    
    Arguments:
        - df: Dataframe containing the calibration data
        - R: the resistor used with this dataset
        - The list of channels tuple
        - The channel connected to the reference resistor
    Returns:
        - List of 3 floats (scaling factor for each channel)
    """
    for ch in channels:
        try:
            n= ch['Name']
            if chvref in df.columns and f"i{n}" in df.columns:
                result = linregress(df[chvref], df[f"i{n}"])
                logging.debug(f"Channel {n}: y = {result.slope:.4f}x + {result.intercept:.4f} (R² = {result.rvalue**2:.4f})")
                ch['icoef']= float(1/(R*result.slope))
            else:
                logging.warning(f"Column {chvref} or i{n} are missing from I coefficients table")
        except Exception as e:
            logging.warning(f"⚠ Error calculating coefficient for channel {n}: {e}")
            ch['icoef']= 1



def resample_xy(df: pd.DataFrame, x: str, y: str, n: int, sigma: int):
    """
    This function resamples a two-columns dataframe over a given number of points n
    Arguments:
        - input dataframe
        - x and y column names
        - number of points required in the final df
        - gaussian filter width
    Returns:
        - Resampled df
    """
    df= df[[x,y]] #Ensure the df has only two columns
    df = df.sort_values(x).drop_duplicates(x)
    df[y] = gaussian_filter1d(df[y].values, sigma=sigma)
    
    # Define new regular x grid (100 points over your range of interest)
    xmin, xmax = df[x].min(), df[x].max()
    x_new = np.linspace(xmin, xmax, n)

    # Interpolate y onto the regular grid
    y_new = np.interp(x_new, df[x].values, df[y].values)

    return pd.DataFrame({x: x_new, y: y_new})