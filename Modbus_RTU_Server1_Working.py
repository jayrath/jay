import threading
import logging
import time
from datetime import datetime
import serial
from pymodbus.server.sync import StartSerialServer
from pymodbus.datastore import ModbusServerContext, ModbusSlaveContext
from pymodbus.transaction import ModbusRtuFramer
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadBuilder
from pymodbus.server.sync import ModbusSerialServer
from pymodbus.payload import BinaryPayloadBuilder
from pymodbus.constants import Endian
import crcmod


# Configure logging
logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define serial settings
serial_settings = {
    'port': 'COM3',
    'baudrate': 9600,
    'bytesize': serial.EIGHTBITS,
    'parity': serial.PARITY_NONE,
    'stopbits': serial.STOPBITS_ONE,
    'timeout': 1
}

# Read data from file
def read_params_from_file():
    try:
        with open("parameter_values.txt", 'r') as file:
            lines = file.readlines()
            if lines:
                latest_line = lines[-1].strip()
                values = latest_line.split(',')
                if len(values) == 6:
                    # Extracting values
                    date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
                    temp_c = float(values[1])
                    humidity = float(values[2])
                    wind_speed = float(values[3])
                    wind_dir = float(values[4])
                    rainfall = float(values[5])

                    return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
                else:
                    logging.error("Invalid data format in the file")
                    return None
            else:
                logging.error("File is empty")
                return None
    except Exception as e:
        logging.error("Error reading file:", e)
        return None

def update_holding_registers(context):
    try:
        params = read_params_from_file()
        if params:
            date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
            year = date_time.year
            month = date_time.month
            day = date_time.day
            hour = date_time.hour
            minute = date_time.minute
            second = date_time.second

            # Apply scaling to sensor values
            scaled_temp = int(temp_c * 10)
            scaled_humidity = int(humidity * 100)
            scaled_wind_speed = int(wind_speed * 100)
            scaled_wind_dir = int(wind_dir * 10)
            scaled_rainfall = int(rainfall * 100)

            # Update holding register values
            holding_register_values = [
                year, month, day, hour, minute, second,
                scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
            ]
            context[0].setValues(1, 0, holding_register_values)  # Slave ID: 1, Holding Register Address: 0
            print("Values written to holding register:", holding_register_values)
    except Exception as e:
        logging.error(f"Error updating holding registers: {e}")

def configure_modbus_server():
    store = ModbusSlaveContext()
    context = ModbusServerContext(slaves=store, single=True)
    return context

def run_modbus_server(context):
    try:
        # Configure serial port
        serial_port = serial.Serial(**serial_settings)

        server = StartSerialServer(context[0], framer=ModbusRtuFramer, port=serial_port, timeout=1)
        print("Modbus RTU Server started successfully")
        server.serve_forever()
    except Exception as e:
        logging.error(f"Error starting Modbus RTU Server: {e}")

def update_sensor_values(context):
    while True:
        print("Updating holding registers with sensor values...")
        update_holding_registers(context)
        time.sleep(60)  # Update sensor data every minute

def handle_modbus_request(context, serial_port):
    while True:
        try:
            print("Waiting for Modbus RTU client request...")
            request_hex = serial_port.read(8).hex()  # Read 8 bytes and convert to hexadecimal string
            if request_hex:
                print("Received Modbus RTU client request:", request_hex)
                request = bytes.fromhex(request_hex)  # Decode hexadecimal string to bytes
                process_modbus_request(context, request, serial_port)  # Call process_modbus_request here
        except Exception as e:
            logging.error(f"Error receiving Modbus RTU client request: {e}")

def calculate_crc(data):
    crc16 = crcmod.mkCrcFun(0x18005, rev=True, initCrc=0xFFFF, xorOut=0x0000)
    crc = crc16(data)
    return crc.to_bytes(2, byteorder='little')

# Modify the process_modbus_request function to include CRC calculation
def process_modbus_request(context, request, serial_port):
    print("Processing Modbus RTU client request")
    print("Request inside process modbus request is .....:", request)

    try:
        # Extracting slave ID, function code, start address, and number of registers to read from the request
        slave_id = request[0]
        print("Slave ID is....:", slave_id)
        function_code = request[1]
        print("Function code is....:", function_code)
        start_address = int.from_bytes(request[2:4], byteorder='big', signed=False)  # Assuming unsigned bytes
        print("Start address is....:", start_address)
        num_registers = int.from_bytes(request[4:6], byteorder='big', signed=False)  # Assuming unsigned bytes
        print("Number of registers to read is....:", num_registers)

        # Get values from holding registers based on the extracted parameters from the request
        values = context[0].getValues(slave_id, start_address, num_registers)
        print("Values are....:", values)

        if values:
            # Convert values to bytes, truncating if necessary
            int_values = []
            for value in values:
                int_value = max(0, min(value, 65535))  # Ensure value is within the valid range
                int_bytes = int_value.to_bytes(2, byteorder='big', signed=True)  # Convert to bytes
                int_values.extend(int_bytes)

            # Create a bytearray from the integer values
            response_data = bytes([slave_id, function_code]) + bytes([len(int_values)]) + bytearray(int_values)

            # Calculate CRC
            crc = calculate_crc(response_data)

            # Construct the complete response
            response = response_data + crc

            # Send response to the client
            serial_port.write(response)
            print("Response sent to Modbus RTU client:", response)
        else:
            # If no values found, send an error response (exception code 2)
            response = bytes([slave_id, function_code + 0x80, 0x02])  # Add 0x80 to function code for error response
            # Send error response to the client
            serial_port.write(response)
            print("Error response sent to Modbus RTU client:", response.hex())

    except Exception as e:
        # If an error occurs during request handling, print the error
        print("Error handling Modbus RTU client request:", e)



def start_main():
    try:
        print("Starting Modbus RTU Server...")
        logging.info("Starting Modbus RTU Server...")
        context = configure_modbus_server()

        # Create a thread for updating sensor values
        sensor_thread = threading.Thread(target=update_sensor_values, args=(context,))
        sensor_thread.start()

        # Create a serial port
        serial_port = serial.Serial(**serial_settings)

        # Create a thread for handling Modbus requests
        request_thread = threading.Thread(target=handle_modbus_request, args=(context, serial_port))
        request_thread.start()

        # Start the Modbus RTU server
        run_modbus_server(context)

        # Wait for both threads to finish
        sensor_thread.join()
        request_thread.join()

    except KeyboardInterrupt:
        logging.info("Main thread Stopped by user")
    except Exception as e:
        logging.error(f"An error occurred: {e}")

if __name__ == "__main__":
    start_main()








