import tkinter as tk
from tkinter import ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from pathlib import Path
import serial_functions as serfn
import calib_functions as calfn

import logging
level = logging.INFO
logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(message)s')

import yaml

def read_yaml(filepath: Path)-> dict:
    try:
        logging.info(f"ℹ️ Parsing yaml file at: {filepath}")
        with open(filepath, 'r') as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                config = loaded
                return config
            else:
                return None
    except Exception as e:
        logging.error(f"✗ Error opening file: {e}")
        return None

# Load configuration file
yamlpath= Path('pispos_config.yaml')
config= None


class RealTimeGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(config['gui']['name'])
        self.root.geometry(f"{config['gui']['sizex']}x{config['gui']['sizey']}")
        
        # Serial connection
        self.ser = None
        self.device_var = None
        self.connection_status = None

        # Board state
        self.events= [] # Buffer to store events coming from the board
        self.range= None
        self.sampling_freq= config['gui']['sampling frequency']
        self.graph_duration= config['gui']['chart duration']

        # Channel definitions
        self.calibpath= Path(config['setup']['calibration folder'])
        self.channel_names = config['setup']['channels']
        fg_channel_colors = config['gui']['foreground channels colors']
        bg_channel_colors = config['gui']['background channels colors']
        self.channels=[]
        for name in self.channel_names:
            ch={
                'Name': name,
                'VData': [], # Array to store voltage serie 
                'IData': [], # Array to store current serie
                'TData': [], # Array to store time serie
                'SetPoint': config['setup']['setpoint'], # Setpoint of the channel
                'Unit': config['setup']['unit'], # Unit of this setpoint (V or I for voltage or current regulation)
                'MaxPower': config['setup']['max power'], # Maximum power before disconnecting the channel

                'ioffset': None,
                'icoef': 1,
                
                # GUI elements
                'FgColor': fg_channel_colors[name], # Foreground color 
                'BgColor': bg_channel_colors[name], # Background color
                'SetpointEntry': None, # textbox for typing the setpoint
                'UnitButtons': None, # Buttons for switching regulation type (current or voltage)
                'MaxPowerEntry': None, # textbox for typing the maximum power
                'IVPmonitor': None, # Textbox for showing instant volgate, current and power
                'StatusBox': None # Textbox for showing current status (saturating, regulation...)
            }
            self.channels.append(ch)
        
        self.setup_layout()
        # Running flag used to stop recurring callbacks on shutdown
        self._running = True
        # Bind window close (top-right cross) to graceful shutdown handler
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        
    def setup_layout(self)-> None:
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # GAUCHE: Colonne verticale simple
        left_column = tk.Frame(main_frame, width=340)
        left_column.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_column.pack_propagate(False)  # ← UNIQUEMENT ICI
        
        # Connection EN HAUT
        connection_panel = tk.LabelFrame(left_column, text="Connection")
        connection_panel.pack(fill=tk.X, pady=(10, 5))
        self.create_connection_section(connection_panel)
        
        # Channels EN DESSOUS  
        control_panel = tk.LabelFrame(left_column, text="Channel Controls")
        control_panel.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        for ch in self.channels:
            self.create_channel_section(control_panel, ch)
        
        
        # RIGHT: PLOTS
        plot_frame = tk.Frame(main_frame)
        plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.fig = Figure(figsize=(10, 8))
        self.fig.subplots_adjust(left=0.08, right=0.98, top=0.95, bottom=0.08, hspace=0.05)
        
        self.ax_voltage = self.fig.add_subplot(2, 1, 1)
        self.voltage_lines = {}
        for ch in self.channels:
            self.voltage_lines[ch['Name']], = self.ax_voltage.plot([], [], color=ch['FgColor'], label=f'Ch {ch['Name']}', lw=2)
        self.ax_voltage.set_ylabel('Voltage (V)')
        self.ax_voltage.grid(True)
        self.ax_voltage.legend()
        self.ax_voltage.tick_params(axis='x', bottom=False, labelbottom=False)
        
        self.ax_current = self.fig.add_subplot(2, 1, 2, sharex=self.ax_voltage)
        self.current_lines = {}
        for ch in self.channels:
            self.current_lines[ch['Name']], = self.ax_current.plot([], [], color=ch['FgColor'], label=f'Ch {ch['Name']}', lw=2)
        self.ax_current.set_xlabel('Time (s)')
        self.ax_current.set_ylabel('Current (mA)')
        self.ax_current.grid(True)
        self.ax_current.legend()
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        

    def create_channel_section(self, parent: tk.Frame, ch: dict)-> None:
        # Line 1 : channel title
        ch_frame = tk.LabelFrame(parent, text=f"Channel {ch['Name']}", 
                            font=("Arial", 12, "bold"), fg=ch['FgColor'],
                            bg=ch['BgColor'],
                            padx=8, pady=5)
        ch_frame.pack(fill=tk.X, padx=8, pady=5)

        # Line 2: Volgate-Current-Power monitor
        ch['IVPmonitor'] = tk.Label(ch_frame, text="nd mA @ nd V  [ nd W ]", 
                                            font=("Arial", 11, "bold"),
                                            fg=ch['FgColor'],
                                            bg=ch['BgColor'])
        ch['IVPmonitor'].pack(fill=tk.X, pady=(5, 0))


        # Line 3: Setpoint | V mA toggles
        row1 = tk.Frame(ch_frame, bg=ch['BgColor'])
        row1.pack(fill=tk.X, pady=(5, 2))
        row1.grid_columnconfigure(0, weight=1)  # Colonne gauche (setpoint)
        row1.grid_columnconfigure(1, weight=1)  # Colonne droite (toggles)
        
        # left: Setpoint box
        setpoint_frame = tk.Frame(row1, bg=ch['BgColor'])
        setpoint_frame.grid(row=0, column=0, sticky="w", padx=(5, 5))
        
        ch['SetpointEntry']= tk.Entry(setpoint_frame, font=("Arial", 12), width=10, justify=tk.CENTER)
        ch['SetpointEntry'].insert(0, "0.0")
        ch['SetpointEntry'].pack(anchor=tk.W, pady=(0, 5))
        
        # right: V/mA toggles
        toggle_frame = tk.Frame(row1, bg=ch['BgColor'])
        toggle_frame.grid(row=0, column=1, sticky="e", padx=(5, 5))
        
        ch['UnitButtons'] = {'V': None, 'mA': None}
        ch['UnitButtons']['V'] = tk.Button(toggle_frame, text="V", width=6, fg="White",
                                                font=("Arial", 10, "bold"),
                                                command=lambda c=ch: self.toggle_unit(c, 'V'))
        ch['UnitButtons']['V'].config(bg=ch['FgColor'], relief=tk.RAISED)
        ch['UnitButtons']['V'].pack(side=tk.LEFT, padx=(0, 3))
        
        ch['UnitButtons']['mA'] = tk.Button(toggle_frame, text="mA", width=6, fg="White",
                                                font=("Arial", 10, "bold"),
                                                command=lambda c=ch: self.toggle_unit(c, 'mA'))
        ch['UnitButtons']['mA'].config(bg="darkgray", relief=tk.SUNKEN)
        ch['UnitButtons']['mA'].pack(side=tk.LEFT)
        
        # Line 3: Max power
        row2 = tk.Frame(ch_frame, bg=ch['BgColor'])
        row2.pack(fill=tk.X, pady=(5, 2))
        row2.grid_columnconfigure(0, weight=1)
        row2.grid_columnconfigure(1, weight=1)
        
        # Max power label (left)
        power_frame = tk.Frame(row2, bg=ch['BgColor'])
        power_frame.grid(row=0, column=0, sticky="w", padx=(5, 5))
        tk.Label(power_frame, text="Max Power:",bg=ch['BgColor'], font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=(5, 2))
        
        # Max power text box (right)
        entry_frame = tk.Frame(row2, bg=ch['BgColor'])
        entry_frame.grid(row=0, column=1, sticky="e", padx=(5, 5))
        ch['MaxPowerEntry'] = tk.Entry(entry_frame, font=("Arial", 12), width=8, justify=tk.CENTER)
        ch['MaxPowerEntry'].insert(0, "1.0")
        ch['MaxPowerEntry'].pack(side=tk.LEFT, padx=(0, 3))
        tk.Label(entry_frame, text="W", bg=ch['BgColor'], font=("Arial", 11)).pack(side=tk.LEFT)
        
        # Update button (center)
        update_btn = tk.Button(ch_frame, text="Update", command=lambda c=ch: self.update_channel(c),
                            bg="#e0e0e0", fg="Black", font=("Arial", 10, "bold"), width=8)
        update_btn.pack(fill=tk.X, pady=(5, 0))

        # Status textbox
        ch['StatusBox'] = tk.Label(ch_frame, 
                                    text="Undefined", 
                                    font=("Arial", 12, "bold"), 
                                    fg="gray",
                                    bg="lightgray",
                                    relief=tk.RIDGE,
                                    padx=10, pady=3)
        ch['StatusBox'].pack(fill=tk.X, pady=(2, 5))

        
    def toggle_unit(self, ch:dict, unit: str)->None:
        ch['Unit'] = unit
        for u, btn in ch['UnitButtons'].items():
            if u == unit:
                btn.config(bg=ch['FgColor'], relief=tk.RAISED)
            else:
                btn.config(bg="darkgray", relief=tk.SUNKEN)


    def update_channel(self, ch:dict)-> None:
        try:
            ch['SetPoint'] = float(ch['SetpointEntry'].get())
            ch['MaxPower'] = float(ch['MaxPowerEntry'].get())
            logging.info(f"Channel {ch['Name']} updated: {ch['SetPoint']} {ch['Unit']}, Max Power: {ch['MaxPower']} W")
            
            # Update the regulation mode (current or voltage)
            regulation= 'v'
            if ch['Unit']== 'mA':
                regulation= 'i'
            cmd= f"{ch['Name']} {regulation}"
            serfn.safe_write(self.ser, cmd)

            # Update the setpoint
            cmd= f"{ch['Name']} {ch['SetPoint']}"
            serfn.safe_write(self.ser, cmd)

            # Update the maximum power
            cmd= f"{ch['Name']} {ch['MaxPower']}w"
            serfn.safe_write(self.ser, cmd)
            
        except ValueError:
            logging.error(f"Invalid values for Channel {ch['Name']}")


    def update_events(self)-> None:
        """
        This function watches the content of the event_list and
        eventually update GUI textboxes or trigger relays in case of overload
        """
        for event in self.events:
            logging.info(f"Event recieved: {event}")
            ep= event.split(' ')
            if 'PushPullConnected' in event and len(ep)==4:
                try:
                    n= self.channel_names.index(ep[1])
                    if ep[3]=='True':
                        self.root.after(0, self.channels[n]['StatusBox'].config(text=f"Push-pull output connected", fg="green"))
                    else:
                        self.root.after(0, self.channels[n]['StatusBox'].config(text=f"Push-pull output disconnected", fg="gray"))
                except Exception as e:
                    logging.error(f"Error parsing switch state: {e}")
            elif 'Range' in event and len(ep)==3:
                try:
                    self.range= int(ep[1])
                    # Update the calibrations for the new range
                    try:
                        calfn.load_calibration_files(self.range, self.channels, self.calibpath)
                    except Exception as e:
                        logging.error(f"Error getting the calibration for range {self.range}: {e}")
                except Exception as e:
                    logging.error(f"Error parsing range: {e}")
            elif 'State' in event and len(ep)>=3:
                try:
                   n= self.channel_names.index(ep[1])
                   message= ' '.join(ep[2:])
                   color= "green"
                   if 'Saturation' in message:
                       color= "red"
                   self.root.after(0, self.channels[n]['StatusBox'].config(text=message, fg=color))
                except Exception as e:
                    logging.error(f"Error parsing state: {e}")
            elif 'Alert ' in event:
                try:
                    n= self.channel_names.index(ep[1])
                    message= ' '.join(ep[3:])
                    self.root.after(0, self.channels[n]['StatusBox'].config(text=message, fg="red"))
                except Exception as e:
                    logging.error(f"Error parsing alert: {e}")


        self.events.clear()
        if self._running:
            self.root.after(100, self.update_events)


    def update_plot(self)-> None:
        try:
            # Update the sampling frequency from the GUI if is it has changed
            f= float(self.sampling_var.get())
            if f != self.sampling_freq:
                if f >= 1 and f <= 20:
                    logging.info(f"Updating sampling frequency from {self.sampling_freq} to {f} Hz")
                    serfn.safe_write(self.ser, f"set sampling {f}")
                    self.sampling_freq= f
            
            # Update the graph duration from the GUI if it has changed
            d= float(self.time_var.get())
            if d != self.graph_duration:
                if d >= 5 and d <= 1000:
                    logging.info(f"Updating graph duration from {self.graph_duration} to {d} s")
                    self.graph_duration= d
            
            # Remove oldest points from the dataset
            max_points= int(self.graph_duration*self.sampling_freq)
            logging.debug("Removing oldest points")
            for ch in self.channels:
                if len(ch['VData']) > max_points:
                    ch['VData']= ch['VData'][-max_points:]
                if len(ch['IData']) > max_points:
                    ch['IData']= ch['IData'][-max_points:]
                if len(ch['TData']) > max_points:
                    ch['TData']= ch['TData'][-max_points:]
            
            # Update the plots
            for ch in self.channels:
                # Prepare x axis to have 0 on the right and negative relative time on the left
                if len(ch['TData']) > 0:
                    t_relative = [x - ch['TData'][-1] for x in ch['TData']]
                    self.voltage_lines[ch['Name']].set_data(t_relative, ch['VData'])
                    self.current_lines[ch['Name']].set_data(t_relative, ch['IData'])
            
            # Set voltage plot style
            self.ax_voltage.relim()
            self.ax_voltage.autoscale_view()
            self.ax_voltage.set_xlim(-self.graph_duration, 0)
            
            # Set current plot style
            self.ax_current.relim()
            self.ax_current.autoscale_view()
            self.ax_current.set_xlim(-self.graph_duration, 0)
                
            self.canvas.draw()
        except Exception as e:
            logging.error(f"Error while updating the charts: {e}")
        
        if self._running:
            self.root.after(int(1000/self.sampling_freq), self.update_plot)


    def read_serial(self):
        if not self._running:
            return
        if self.ser is None:
            logging.debug("Serial connection not set")
            if self._running:
                self.root.after(1000, self.read_serial)
        else:
            try:
                serfn.read_serial_values(self.ser, self.events, self.channels)
            except Exception as e:
                logging.error(f"Error while reading serial: {e}")
            if self._running:
                self.root.after(1, self.read_serial)


    def on_close(self) -> None:
        """Gracefully stop recurring callbacks, close serial port and destroy the Tk window."""
        logging.info("Shutting down GUI gracefully...")
        # Prevent further callbacks
        self._running = False
        # Try to close serial port if open
        try:
            serfn.close_serial_link(self.ser)
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


    def get_user_panel(self)-> None:
        """
        To run once on startup to get switches states
        Subsequent events will be parsed by update_events function
        """
        if self.ser is not None:
            config= serfn.get_current_config(self.ser)
            if not config['Communicating']:
                # Close the connection of no answer from the pico
                self.ser= None
            else:
                # Set the ammeter range and load the calibration
                self.range= int(config['AmmeterRange'])
                try:
                    calfn.load_calibration_files(self.range, self.channels, self.calibpath)
                except Exception as e:
                    logging.error(f"Error getting the calibration for range {self.range}: {e}")
                for ch in self.channels:
                    logging.debug(f"Checking channel {ch['Name']} state: switch on {config[f"{ch['Name']}_PushPullConnected"]}")
                    if config[f"{ch['Name']}_PushPullConnected"]=='True':
                        self.root.after(0, ch['StatusBox'].config(text=f"Regulating", fg="green"))
                    else:
                        self.root.after(0, ch['StatusBox'].config(text=f"Push-pull output disconnected", fg="gray"))


    def update_ivp_monitor(self)-> None:
        for ch in self.channels:
            i, v= None, None
            if len(ch['VData'])>0:
                v= ch['VData'][-1]
            if len(ch['IData'])>0:
                i= ch['IData'][-1]
            if i is not None and v is not None:
                punit='mW'
                p=i*v # milliwatts since I is in mA
                if p > 100:
                    punit='W'
                    p*=1e-3
                ch['IVPmonitor'].config(text=f"{i:.3f} mA @ {v:.2f} V  [ {p:.3f} {punit} ]")
        self.root.after(50, self.update_ivp_monitor)


    def create_connection_section(self, parent):
        # Ligne 1: Device (gauche) | Baudrate (droite) - HORIZONTAUX
        main_row = tk.Frame(parent)
        main_row.pack(fill=tk.X, pady=(10, 8))
        main_row.grid_columnconfigure(0, weight=1)
        main_row.grid_columnconfigure(1, weight=1)
        
        # GAUCHE: Device + Dropdown
        device_frame = tk.Frame(main_row)
        device_frame.grid(row=0, column=0, sticky="w", padx=(10, 5), pady=2)
        
        tk.Label(device_frame, text="Device:", font=("Arial", 11, "bold")).pack(anchor=tk.W)
        import glob
        self.device_ports = [p for p in glob.glob(config['setup']['device']) 
                            if 'Bluetooth' not in p]
        self.device_ports = self.device_ports or ["No device found"]
        
        self.device_var = tk.StringVar(value=self.device_ports[0])
        self.device_dropdown = ttk.Combobox(device_frame, textvariable=self.device_var,
                                        values=self.device_ports, width=18, state="readonly")
        self.device_dropdown.pack(anchor=tk.W, pady=(0, 3))
        
        # DROITE: Baudrate + Textbox
        baud_frame = tk.Frame(main_row)
        baud_frame.grid(row=0, column=1, sticky="e", padx=(5, 10), pady=2)
        
        tk.Label(baud_frame, text="Baudrate:", font=("Arial", 11, "bold")).pack(anchor=tk.E)
        self.baud_var = tk.StringVar(value="115200")
        baud_entry = tk.Entry(baud_frame, textvariable=self.baud_var, font=("Arial", 12), width=12, justify=tk.CENTER)
        baud_entry.pack(anchor=tk.E, pady=(0, 3))
        
        # Ligne 2: Connect button pleine largeur
        connect_btn = tk.Button(parent, text="Connect", command=self.connect_pico,
                            bg="#2196F3", fg="white", font=("Arial", 12, "bold"),
                            height=1, relief=tk.RAISED)
        connect_btn.pack(fill=tk.X, padx=10, pady=(0, 8))
        
        # Line 3: Status connection
        self.connection_status = tk.Label(parent, text="Disconnected", 
                                        font=("Arial", 11, "bold"), fg="red",
                                        bg="#f8f9fa", relief=tk.RIDGE, pady=5, height=1)
        self.connection_status.pack(fill=tk.X, padx=10, pady=(0, 5))

        # Line 4: Time window and sampling frequency
        row4 = tk.Frame(parent)
        row4.pack(fill=tk.X, pady=(10, 8))
        row4.grid_columnconfigure(0, weight=1)
        row4.grid_columnconfigure(1, weight=1)
        
        # Left: Sampling frequency
        sampling_frame = tk.Frame(row4)
        sampling_frame.grid(row=0, column=0, sticky="w", padx=(10, 5), pady=2)
        tk.Label(sampling_frame, text="Sampling (Hz):", font=("Arial", 11, "bold")).pack(anchor=tk.W)
        self.sampling_var = tk.StringVar(value=self.sampling_freq)
        sampling_entry = tk.Entry(sampling_frame, textvariable=self.sampling_var, font=("Arial", 12), width=12, justify=tk.CENTER)
        sampling_entry.pack(anchor=tk.W, pady=(0, 3))
        
        # Right: Time window
        time_frame = tk.Frame(row4)
        time_frame.grid(row=0, column=1, sticky="e", padx=(5, 10), pady=2)
        tk.Label(time_frame, text="Time window (s):", font=("Arial", 11, "bold")).pack(anchor=tk.W)
        self.time_var = tk.StringVar(value=self.graph_duration)
        time_entry = tk.Entry(time_frame, textvariable=self.time_var, font=("Arial", 12), width=12, justify=tk.CENTER)
        time_entry.pack(anchor=tk.W, pady=(0, 3))


    def connect_pico(self):
        try:
            port = self.device_var.get()
            baud = int(self.baud_var.get())
            
            self.ser = serfn.setup_serial_link(port, baud, None)
            self.get_user_panel()
            if self.ser is None:
                self.connection_status.config(text=f"No reply from {port}", fg="red")
            else:
                self.connection_status.config(text=f"Connected: {port} @ {baud}", fg="green")
                logging.info(f"Connected to {port} @ {baud}")

                # Set the sampling frequency to 10 Hz
                serfn.safe_write(self.ser, f"set sampling {self.sampling_freq}")
            
        except Exception as e:
            self.connection_status.config(text=f"Connection failed: {str(e)}", fg="red")
            logging.error(f"Connection error: {e}")
            self.ser= None


    def run(self):
        self.read_serial()
        self.update_events()
        self.update_ivp_monitor()
        self.update_plot()
        self.root.mainloop()

if __name__ == "__main__":
    try:
        config = read_yaml(yamlpath)
        if config is not None:
            app = RealTimeGUI()
            app.run()
        else:
            logging.error(f"Cant open configuration yaml file {yamlpath}")
    except Exception as e:
        logging.error(f"Error while opening {yamlpath}: {e}")
