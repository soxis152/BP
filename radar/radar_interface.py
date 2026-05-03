"""Tenký wrapper nad radarovým sériovým portem.

Parser Texas Instruments pracuje s jedním blokem bytů. Tahle třída řeší jen
otevření portu, načtení dat a předání bufferu parseru. Díky tomu nemusí
`ingestion.py` znát detaily sériové knihovny ani parseru.
"""

import serial
from parser_mmw_demo import parser_one_mmw_demo_output_packet


class RadarInterface:
    def __init__(self, port, baudrate):
        """
        Initialize the Radar Interface with a specified serial port and baud rate.
        :param port: Serial port to which the radar is connected (e.g., 'COM3' or '/dev/ttyUSB0').
        :param baudrate: Communication baud rate (e.g., 115200).
        """
        self.serial_port = serial.Serial(port, baudrate, timeout=1)
        if self.serial_port.is_open:
            print(f"Connected to radar on {port} at {baudrate} baud.")
        else:
            raise Exception(f"Failed to open serial port {port}.")

    def read_data(self, buffer_size=4096):
        """
        Read data from the radar's serial port.
        :param buffer_size: Maximum number of bytes to read in one call.
        :return: Byte array of the received data.
        """
        # Radar posila binarni stream. Ctu pevny blok a parser si uvnitr
        # najde magic pattern zacatku frame.
        return self.serial_port.read(buffer_size)

    def parse_frame(self, data):
        """
        Parse a single frame of radar data.
        :param data: Byte array of raw data from the radar.
        :return: Parsed results including detected objects and their attributes.
        """
        read_num_bytes = len(data)
        if read_num_bytes > 0:
            try:
                result = parser_one_mmw_demo_output_packet(data, read_num_bytes)
                return result
            except Exception as e:
                print(f"Error parsing frame: {e}")
        return None

    def close(self):
        """
        Close the serial connection.
        """
        if self.serial_port.is_open:
            self.serial_port.close()
            print("Serial port closed.")
