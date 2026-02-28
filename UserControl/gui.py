import tkinter as tk
from tkinter import ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import time
from pathlib import Path
import serial_functions as serfn
import calib_functions as calfn
import asyncio

import logging
level = logging.INFO
logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(message)s')


class RealTimeGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Multi-Channel Current Source PID Monitor")
        self.root.geometry("1400x930")
        
        # Serial connection
        self.ser = None
        self.device_var = None
        self.connection_status = None

        # Board state
        self.range= None
        self.loaded_calib= None

        # Data buffers
        self.channels = ['a', 'b', 'c']
        self.channel_colors = {'a': "#1014ff", 'b': "#e01616", 'c': "#006100"}
        self.bg_channel_colors = {'a': "#b8b8ce", 'b': "#bba3a3", 'c': "#ABBEAB"}
        self.setpoints = {ch: 0.0 for ch in self.channels}
        self.units = {ch: 'V' for ch in self.channels}
        self.max_power = {ch: 1.0 for ch in self.channels}
        self.voltage_data = {ch: [] for ch in self.channels}
        self.current_data = {ch: [] for ch in self.channels}
        self.time_data = []
        self.rows= [] # Buffer to store serial data
        self.events= [] # Buffer to store events coming from the board
        self.sampling_freq= 10
        self.graph_duration= 30
        
        # GUI ELEMENTS
        self.setpoint_entry = {}
        self.max_power_entry = {}
        self.instant_ivp= {} # shows instant intensity - voltage - power
        self.status_label = {}
        self.unit_buttons = {}
        
        self.running = False
        
        self.setup_layout()

        
    def setup_layout(self):
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
            self.voltage_lines[ch], = self.ax_voltage.plot([], [], color=self.channel_colors[ch], label=f'Ch {ch}', lw=2)
        self.ax_voltage.set_ylabel('Voltage (V)')
        self.ax_voltage.grid(True)
        self.ax_voltage.legend()
        self.ax_voltage.tick_params(axis='x', bottom=False, labelbottom=False)
        
        self.ax_current = self.fig.add_subplot(2, 1, 2, sharex=self.ax_voltage)
        self.current_lines = {}
        for ch in self.channels:
            self.current_lines[ch], = self.ax_current.plot([], [], color=self.channel_colors[ch], label=f'Ch {ch}', lw=2)
        self.ax_current.set_xlabel('Time (s)')
        self.ax_current.set_ylabel('Current (mA)')
        self.ax_current.grid(True)
        self.ax_current.legend()
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        

    def create_channel_section(self, parent, channel):
        ch_frame = tk.LabelFrame(parent, text=f"Channel {channel}", 
                            font=("Arial", 12, "bold"), fg=self.channel_colors[channel],
                            bg=self.bg_channel_colors[channel],
                            padx=8, pady=5)
        ch_frame.pack(fill=tk.X, padx=8, pady=5)

        # Line 1: Power monitor
        self.instant_ivp[channel] = tk.Label(ch_frame, text="nd mA @ nd V  [ nd W ]", 
                                            font=("Arial", 11, "bold"),
                                            fg=self.channel_colors[channel],
                                            bg=self.bg_channel_colors[channel])
        self.instant_ivp[channel].pack(fill=tk.X, pady=(5, 0))


        # Line 2: Setpoint | V mA toggles → GRID pour alignement parfait
        row1 = tk.Frame(ch_frame, bg=self.bg_channel_colors[channel])
        row1.pack(fill=tk.X, pady=(5, 2))
        row1.grid_columnconfigure(0, weight=1)  # Colonne gauche (setpoint)
        row1.grid_columnconfigure(1, weight=1)  # Colonne droite (toggles)
        
        # GAUCHE: Setpoint box
        setpoint_frame = tk.Frame(row1, bg=self.bg_channel_colors[channel])
        setpoint_frame.grid(row=0, column=0, sticky="w", padx=(5, 5))
        
        self.setpoint_entry[channel] = tk.Entry(setpoint_frame, font=("Arial", 12), width=10, justify=tk.CENTER)
        self.setpoint_entry[channel].insert(0, "0.0")
        self.setpoint_entry[channel].pack(anchor=tk.W, pady=(0, 5))
        
        # DROITE: V/mA toggles
        toggle_frame = tk.Frame(row1, bg=self.bg_channel_colors[channel])
        toggle_frame.grid(row=0, column=1, sticky="e", padx=(5, 5))
        
        self.unit_buttons[channel] = {'V': None, 'mA': None}
        self.unit_buttons[channel]['V'] = tk.Button(toggle_frame, text="V", width=6, fg="White",
                                                font=("Arial", 10, "bold"),
                                                command=lambda c=channel: self.toggle_unit(c, 'V'))
        self.unit_buttons[channel]['V'].config(bg=self.channel_colors[channel], relief=tk.RAISED)
        self.unit_buttons[channel]['V'].pack(side=tk.LEFT, padx=(0, 3))
        
        self.unit_buttons[channel]['mA'] = tk.Button(toggle_frame, text="mA", width=6, fg="White",
                                                font=("Arial", 10, "bold"),
                                                command=lambda c=channel: self.toggle_unit(c, 'mA'))
        self.unit_buttons[channel]['mA'].config(bg="darkgray", relief=tk.SUNKEN)
        self.unit_buttons[channel]['mA'].pack(side=tk.LEFT)
        
        # Line 3: Max power
        row2 = tk.Frame(ch_frame, bg=self.bg_channel_colors[channel])
        row2.pack(fill=tk.X, pady=(5, 2))
        row2.grid_columnconfigure(0, weight=1)
        row2.grid_columnconfigure(1, weight=1)
        
        # Max power label (left)
        power_frame = tk.Frame(row2, bg=self.bg_channel_colors[channel])
        power_frame.grid(row=0, column=0, sticky="w", padx=(5, 5))
        tk.Label(power_frame, text="Max Power:",bg=self.bg_channel_colors[channel], font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=(5, 2))
        
        # Max power text box (right)
        entry_frame = tk.Frame(row2, bg=self.bg_channel_colors[channel])
        entry_frame.grid(row=0, column=1, sticky="e", padx=(5, 5))
        self.max_power_entry[channel] = tk.Entry(entry_frame, font=("Arial", 12), width=8, justify=tk.CENTER)
        self.max_power_entry[channel].insert(0, "1.0")
        self.max_power_entry[channel].pack(side=tk.LEFT, padx=(0, 3))
        tk.Label(entry_frame, text="W", bg=self.bg_channel_colors[channel], font=("Arial", 11)).pack(side=tk.LEFT)
        
        # Update button (conter)
        update_btn = tk.Button(ch_frame, text="Update", command=lambda c=channel: self.update_channel(c),
                            bg="#e0e0e0", fg="Black", font=("Arial", 10, "bold"), width=8)
        update_btn.pack(fill=tk.X, pady=(5, 0))

        # Status textbox
        self.status_label[channel] = tk.Label(ch_frame, 
                                    text="Undefined", 
                                    font=("Arial", 12, "bold"), 
                                    fg="gray",
                                    bg="lightgray",
                                    relief=tk.RIDGE,
                                    padx=10, pady=3)
        self.status_label[channel].pack(fill=tk.X, pady=(2, 5))

        
    def toggle_unit(self, channel, unit):
        self.units[channel] = unit
        for u, btn in self.unit_buttons[channel].items():
            if u == unit:
                btn.config(bg=self.channel_colors[channel], relief=tk.RAISED)
            else:
                btn.config(bg="darkgray", relief=tk.SUNKEN)


    def update_channel(self, channel):
        try:
            self.setpoints[channel] = float(self.setpoint_entry[channel].get())
            self.max_power[channel] = float(self.max_power_entry[channel].get())
            logging.info(f"Channel {channel} updated: {self.setpoints[channel]} {self.units[channel]}, Max Power: {self.max_power[channel]} W")
            
            # Update the regulation mode (current or voltage)
            regulation= 'v'
            if self.units[channel]== 'mA':
                regulation= 'i'
            cmd= f"{channel} {regulation}"
            serfn.safe_write(self.ser, cmd)

            # Update the setpoint
            cmd= f"{channel} {self.setpoints[channel]}"
            serfn.safe_write(self.ser, cmd)

            # Update the maximum power
            cmd= f"{channel} {self.max_power[channel]}w"
            serfn.safe_write(self.ser, cmd)
            
        except ValueError:
            print(f"Invalid values for Channel {channel}")


    def update_data(self):
        t = time.time()
        #logging.info(f"Updating data lists, time {t}...")
        for row in self.rows:
            logging.debug(f"Appending new row to the graph data {row}")
            self.time_data.append(t)
            # each row is a dict with keys such as ia, va, ib, vb..
            try:
                for param in row.keys():
                    if param[0]=='t':
                        continue
                    if len(param)==2:
                        if param[0]=='i':
                            self.current_data[param[1]].append(row[param])
                        elif param[0]=='v':
                            self.voltage_data[param[1]].append(row[param])
                        else:
                            print(f"Unknown key while reading serial data: {param}")
                    else:
                        print(f"Unknown key while reading serial data: {param}")
            except Exception as e:
                print(f"Cannot parse {row}: {e}")
        self.rows.clear()
        
        self.root.after(int(1000/self.sampling_freq), self.update_data)
                        

    def update_events(self):
        """
        This function watches the content of the event_list and
        eventually update GUI textboxes or trigger relays in case of overload
        """
        for event in self.events:
            logging.info(f"Event recieved: {event}")
            ep= event.split(' ')
            if 'PushPullConnected' in event and len(ep)==4:
                try:
                    ch= ep[1]
                    if ep[3]=='True':
                        self.root.after(0, self.status_label[ch].config(text=f"Push-pull output connected", fg="green"))
                    else:
                        self.root.after(0, self.status_label[ch].config(text=f"Push-pull output disconnected", fg="gray"))
                except Exception as e:
                    logging.error(f"Error parsing switch state: {e}")
            elif 'Range' in event and len(ep)==3:
                try:
                    self.range= int(ep[1])
                except Exception as e:
                    logging.error(f"Error parsing range: {e}")
            elif 'State' in event and len(ep)>=3:
                try:
                   ch= ep[1]
                   message= ' '.join(ep[2:])
                   color= "green"
                   if 'Saturation' in message:
                       color= "red"
                   self.root.after(0, self.status_label[ch].config(text=message, fg=color))
                except Exception as e:
                    logging.error(f"Error parsing state: {e}")
            elif 'Alert ' in event:
                try:
                    ch= ep[1]
                    message= ' '.join(ep[3:])
                    self.root.after(0, self.status_label[ch].config(text=message, fg="red"))
                except Exception as e:
                    logging.error(f"Error parsing alert: {e}")


        self.events.clear()
        self.root.after(100, self.update_events)


    def update_plot(self):
        # Update the sampling frequency if is it has been changed
        f= float(self.sampling_var.get())
        if f != self.sampling_freq:
            if f >= 1 and f <= 100:
                print(f"Updating sampling frequency from {self.sampling_freq} to {f} Hz")
                serfn.safe_write(self.ser, f"set sampling {f}")
                self.sampling_freq= f
        
        # Update the graph duration if it has been changed
        d= float(self.time_var.get())
        if d != self.graph_duration:
            if d >= 5 and d <= 1000:
                print(f"Updating graph duration from {self.graph_duration} to {d} s")
                self.graph_duration= d
        
        # Remove oldest points from the dataset
        max_points= int(self.graph_duration*self.sampling_freq)
        logging.debug(f"Current points {len(self.time_data)} - Max points {max_points}")
        if len(self.time_data) > max_points:
            logging.debug("Removing oldest points")
            self.time_data= self.time_data[-max_points:]
            for ch in self.channels:
                self.voltage_data[ch]= self.voltage_data[ch][-max_points:]
                self.current_data[ch]= self.current_data[ch][-max_points:]
        
        # Update the plots
        if self.time_data:
            # Prepare x axis to have 0 on the right and negative relative time on the left
            relative_time = [x - self.time_data[-1] for x in self.time_data]
            for ch in self.channels:
                self.voltage_lines[ch].set_data(relative_time, self.voltage_data[ch])
            self.ax_voltage.relim()
            self.ax_voltage.autoscale_view()
            self.ax_voltage.set_xlim(-self.graph_duration, 0)
            
            for ch in self.channels:
                self.current_lines[ch].set_data(relative_time, self.current_data[ch])
            self.ax_current.relim()
            self.ax_current.autoscale_view()
            self.ax_current.set_xlim(-self.graph_duration, 0)
            
        self.canvas.draw()
        self.root.after(int(1000/self.sampling_freq), self.update_plot)


    def read_serial(self):
        if self.ser is not None:
            asyncio.run(serfn.read_serial_values(self.ser, self.rows, self.events, serfn.channels, loop_mode=False))
        self.root.after(1, self.read_serial)


    def get_user_panel(self):
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
                    calfn.load_calibration_files(self.range, self.channels, Path('/media/Bureau/Electronique/iv_calibrations'))
                except Exception as e:
                    print(f"Error getting the calibration for range {self.range}: {e}")
                for ch in self.channels:
                    logging.debug(f"Checking channel {ch} state: switch on {config[f"{ch}_PushPullConnected"]}")
                    if config[f"{ch}_PushPullConnected"]=='True':
                        self.root.after(0, self.status_label[ch].config(text=f"Regulating", fg="green"))
                    else:
                        self.root.after(0, self.status_label[ch].config(text=f"Push-pull output disconnected", fg="gray"))


    def update_ivp_monitor(self):
        for ch in self.channels:
            i, v= None, None
            if len(self.voltage_data[ch])>0:
                v= self.voltage_data[ch][-1]
            if len(self.current_data[ch])>0:
                i= self.current_data[ch][-1]
            if i is not None and v is not None:
                punit='mW'
                p=i*v # milliwatts since I is in mA
                if p > 100:
                    punit='W'
                    p*=1e-3
                self.instant_ivp[ch].config(text=f"{i:.3f} mA @ {v:.2f} V  [ {p:.3f} {punit} ]")
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
        self.device_ports = [p for p in glob.glob('/dev/ttyACM0*') 
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
                print(f"Connected to {port} @ {baud}")

                # Set the sampling frequency to 10 Hz
                serfn.safe_write(self.ser, 'set sampling 10')
            
        except Exception as e:
            self.connection_status.config(text=f"Connection failed: {str(e)}", fg="red")
            print(f"Connection error: {e}")
            self.ser= None


    def run(self):
        self.read_serial()
        self.update_data()
        self.update_events()
        self.update_ivp_monitor()
        self.update_plot()
        self.root.mainloop()

if __name__ == "__main__":
    app = RealTimeGUI()
    app.run()
