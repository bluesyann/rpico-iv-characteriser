import tkinter as tk
from tkinter import ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
import time
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
        self.root.geometry("1400x870")
        
        # Serial connection
        self.ser = None
        self.device_var = None
        self.connection_status = None

        # Data buffers
        self.channels = ['a', 'b', 'c']
        self.channel_colors = {'a': "#1014ff", 'b': "#e01616", 'c': "#006100"}
        self.setpoints = {ch: 0.0 for ch in self.channels}
        self.units = {ch: 'V' for ch in self.channels}
        self.max_power = {ch: 1.0 for ch in self.channels}
        self.time_data = []
        self.voltage_data = {ch: [] for ch in self.channels}
        self.current_data = {ch: [] for ch in self.channels}
        self.max_points = 1000
        self.rows= [] # Buffer to store serial data
        
        # GUI ELEMENTS
        self.setpoint_entry = {}
        self.max_power_entry = {}
        self.status_label = {}
        self.unit_buttons = {}
        
        self.running = False
        self.data_thread = None
        
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
                            padx=8, pady=5)
        ch_frame.pack(fill=tk.X, padx=8, pady=5)

        # Power monitor
        self.status_label[channel] = tk.Label(ch_frame, text="0.00 mA @ 0.00 V  [ 0.00 W ]", 
                                            font=("Arial", 11, "bold"), fg=self.channel_colors[channel])
        self.status_label[channel].pack(fill=tk.X, pady=(5, 0))


        # LIGNE 1: Setpoint | V mA toggles → GRID pour alignement parfait
        row1 = tk.Frame(ch_frame)
        row1.pack(fill=tk.X, pady=(5, 2))
        row1.grid_columnconfigure(0, weight=1)  # Colonne gauche (setpoint)
        row1.grid_columnconfigure(1, weight=1)  # Colonne droite (toggles)
        
        # GAUCHE: Setpoint box
        setpoint_frame = tk.Frame(row1)
        setpoint_frame.grid(row=0, column=0, sticky="w", padx=(5, 5))
        
        self.setpoint_entry[channel] = tk.Entry(setpoint_frame, font=("Arial", 12), width=10, justify=tk.CENTER)
        self.setpoint_entry[channel].insert(0, "0.0")
        self.setpoint_entry[channel].pack(anchor=tk.W, pady=(0, 5))
        
        # DROITE: V/mA toggles
        toggle_frame = tk.Frame(row1)
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
        
        # Line 2: Max power
        row2 = tk.Frame(ch_frame)
        row2.pack(fill=tk.X, pady=(5, 2))
        row2.grid_columnconfigure(0, weight=1)
        row2.grid_columnconfigure(1, weight=1)
        
        # Max power label (left)
        power_frame = tk.Frame(row2)
        power_frame.grid(row=0, column=0, sticky="w", padx=(5, 5))
        tk.Label(power_frame, text="Max Power:", font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=(5, 2))
        
        # Max power text box (right)
        entry_frame = tk.Frame(row2)
        entry_frame.grid(row=0, column=1, sticky="e", padx=(5, 5))
        self.max_power_entry[channel] = tk.Entry(entry_frame, font=("Arial", 12), width=8, justify=tk.CENTER)
        self.max_power_entry[channel].insert(0, "1.0")
        self.max_power_entry[channel].pack(side=tk.LEFT, padx=(0, 3))
        tk.Label(entry_frame, text="W", font=("Arial", 11)).pack(side=tk.LEFT)
        
        # Update button (conter)
        update_btn = tk.Button(ch_frame, text="Update", command=lambda c=channel: self.update_channel(c),
                            bg="#e0e0e0", fg="Black", font=("Arial", 10, "bold"), width=8)
        update_btn.pack(fill=tk.X, pady=(5, 0))

        # Status textbox
        self.status_label[channel] = tk.Label(ch_frame, 
                                    text="Idle", 
                                    font=("Arial", 12, "bold"), 
                                    fg="orange",
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
            print(f"Channel {channel} updated: {self.setpoints[channel]} {self.units[channel]}, "
                  f"Max Power: {self.max_power[channel]} W")
        except ValueError:
            print(f"Invalid values for Channel {channel}")
            
    def get_setpoint(self, channel):
        return self.setpoints[channel]
        
    def get_max_power(self, channel):
        return self.max_power[channel]
    """
    def start_data(self):
        if not self.running:
            self.running = True
            self.time_data = []
            for ch in self.channels:
                self.voltage_data[ch] = []
                self.current_data[ch] = []
            self.data_thread = threading.Thread(target=self.update_data, daemon=True)
            self.data_thread.start()
            self.status_label_global.config(text="Running", fg="green")
            
    def stop_data(self):
        self.running = False
        self.status_label_global.config(text="Stopped", fg="red")
   """     
    def update_data(self):
        t0 = time.time()
        while self.running:
            time.sleep(0.05)
            t = time.time() - t0
            
            if len(self.rows)==0: #skipping of no new data
                continue
            
            for row in self.rows:
                logging.info(f"Appending new row to the graph data {row}")
                self.time_data.append(t)
                # each row is a dict with keys such as ia, va, ib, vb..
                try:
                    for param in row.keys():
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


            """
            for ch in self.channels:
                setpoint = self.get_setpoint(ch)
                voltage = setpoint * (1 + 0.1 * np.sin(t * 2 + ord(ch)))
                current = setpoint * 0.98 + 0.05 * np.sin(t * 3 + ord(ch)) + np.random.normal(0, 0.01)
                power = voltage * current
                
                self.time_data.append(t)
                self.voltage_data[ch].append(voltage)
                self.current_data[ch].append(current)
                
                self.root.after(0, lambda v=voltage, i=current, p=power, ch=ch: 
                    self.status_label[ch].config(text=f"{i:.2f} mA @ {v:.2f} V {{{p:.2f} W}}"))
                
                state = self.get_channel_state(ch, voltage, current)
                self.root.after(0, lambda s=state, ch=ch: 
                    self.status_label[ch].config(text=s, fg=self.get_state_color(s)))
            
                if len(self.time_data) > self.max_points:
                    self.time_data.pop(0)
                    for ch2 in self.channels:
                        self.voltage_data[ch2].pop(0)
                        self.current_data[ch2].pop(0)
            """
                        
            
    
    def get_channel_state(self, channel, voltage, current):
        """Détermine l'état selon tes critères PID"""
        setpoint = self.get_setpoint(channel)
        error = abs(setpoint - current) / setpoint
        
        if error < 0.02:      # Erreur < 2%
            return "Regulating ✓"
        elif error < 0.1:     # Erreur 2-10%
            return "Converging"
        elif voltage > 20:    # Tension trop haute
            return "Overload !"
        elif current == 0:
            return "Off"
        else:
            return "Error"
            
    def get_state_color(self, state):
        if "✓" in state:
            return "green"
        elif "!" in state:
            return "red"
        elif "Converging" in state:
            return "orange"
        else:
            return "gray"

    def update_plot(self):
        if self.time_data:
            for ch in self.channels:
                self.voltage_lines[ch].set_data(self.time_data, self.voltage_data[ch])
            self.ax_voltage.relim()
            self.ax_voltage.autoscale_view()
            
            for ch in self.channels:
                self.current_lines[ch].set_data(self.time_data, self.current_data[ch])
            self.ax_current.relim()
            self.ax_current.autoscale_view()
            
        self.canvas.draw()
        self.root.after(50, self.update_plot)

    def read_serial(self):
        if self.ser is not None:
            asyncio.run(serfn.read_serial_values(self.ser, self.rows, serfn.channels, loop_mode=False))
            print(self.rows)
        self.root.after(50, self.read_serial)


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
        
        # Status connection
        self.connection_status = tk.Label(parent, text="Disconnected", 
                                        font=("Arial", 11, "bold"), fg="red",
                                        bg="#f8f9fa", relief=tk.RIDGE, pady=5, height=1)
        self.connection_status.pack(fill=tk.X, padx=10, pady=(0, 5))


    def connect_pico(self):
        try:
            port = self.device_var.get()
            baud = int(self.baud_var.get())
            
            self.ser = serfn.setup_serial_link(port, baud, None)
            self.connection_status.config(text=f"Connected: {port} @ {baud}", fg="green")
            print(f"Connected to {port} @ {baud}")
            
        except Exception as e:
            self.connection_status.config(text=f"Connection failed: {str(e)}", fg="red")
            print(f"Connection error: {e}")
            self.ser= None


    def run(self):
        self.update_plot()
        self.read_serial()
        self.root.mainloop()

if __name__ == "__main__":
    app = RealTimeGUI()
    app.run()
