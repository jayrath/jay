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





# import threading
# import logging
# import time
# from datetime import datetime
# import serial
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusServerContext, ModbusSlaveContext
# from pymodbus.transaction import ModbusRtuFramer
# from pymodbus.constants import Endian
# from pymodbus.payload import BinaryPayloadBuilder
# from pymodbus.server.sync import ModbusSerialServer
# from pymodbus.payload import BinaryPayloadBuilder
# from pymodbus.constants import Endian
# from pymodbus.server.sync import ModbusSerialServer
#
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Define serial settings
# serial_settings = {
#     'port': 'COM3',
#     'baudrate': 9600,
#     'bytesize': serial.EIGHTBITS,
#     'parity': serial.PARITY_NONE,
#     'stopbits': serial.STOPBITS_ONE,
#     'timeout': 1
# }
#
# # Read data from file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
# def update_holding_registers(context):
#     try:
#         params = read_params_from_file()
#         if params:
#             date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
#             year = date_time.year
#             month = date_time.month
#             day = date_time.day
#             hour = date_time.hour
#             minute = date_time.minute
#             second = date_time.second
#
#             scaled_temp = int(temp_c * 10)
#             scaled_humidity = int(humidity * 100)
#             scaled_wind_speed = int(wind_speed * 100)
#             scaled_wind_dir = int(wind_dir * 10)
#             scaled_rainfall = int(rainfall * 100)
#             holding_register_values = [
#                 year, month, day, hour, minute, second, scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             ]
#             # holding_register_values = [
#             #     date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#             #     scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             # ]
#             context[0].setValues(1, 0, holding_register_values)  # Slave ID: 1, Holding Register Address: 0
#             print("Values written to holding register:", holding_register_values)
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#
# def configure_modbus_server():
#     store = ModbusSlaveContext()
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
# def run_modbus_server(context):
#     try:
#         # Configure serial port
#         serial_port = serial.Serial(**serial_settings)
#
#         server = StartSerialServer(context[0], framer=ModbusRtuFramer, port=serial_port, timeout=1)
#         print("Modbus RTU Server started successfully")
#         server.serve_forever()
#     except Exception as e:
#         logging.error(f"Error starting Modbus RTU Server: {e}")
#
# def update_sensor_values(context):
#     while True:
#         print("Updating holding registers with sensor values...")
#         update_holding_registers(context)
#         time.sleep(60)  # Update sensor data every minute
#
# # def handle_modbus_request(context, serial_port):
# #     while True:
# #         try:
# #             print("Waiting for Modbus RTU client request...")
# #             # Read 8 bytes (Modbus RTU request length)
# #             request = serial_port.read(8)
# #             if request:
# #                 print("Received Modbus RTU client request:", request.hex())
# #                 process_modbus_request(context, serial_port)
# #         except Exception as e:
# #             logging.error(f"Error receiving Modbus RTU client request: {e}")
#
# ##### THIS FUNCTION GIVES CORRECT REQUEST - b'\x01\x03\x00\x00\x00\x0cE\xcf' #######
# # def handle_modbus_request(context, serial_port):
# #     while True:
# #         try:
# #             print("Waiting for Modbus RTU client request...")
# #             request_hex = serial_port.read(8)  # Read 8 bytes (Modbus RTU request length) as hexadecimal string
# #             if request_hex:
# #                 print("Received Modbus RTU client request:", request_hex)
# #                 # Convert hexadecimal string to bytes
# #                 request = bytes.fromhex(request_hex.decode('utf-8'))
# #                 process_modbus_request(context, request, serial_port)
# #         except Exception as e:
# #             logging.error(f"Error receiving Modbus RTU client request: {e}")
#
# def handle_modbus_request(context, serial_port):
#     while True:
#         try:
#             print("Waiting for Modbus RTU client request...")
#             request_hex = serial_port.read(8).hex()  # Read 8 bytes and convert to hexadecimal string
#             if request_hex:
#                 print("Received Modbus RTU client request:", request_hex)
#                 request = bytes.fromhex(request_hex)  # Decode hexadecimal string to bytes
#                 process_modbus_request(context, request, serial_port)  # Call process_modbus_request here
#         except Exception as e:
#             logging.error(f"Error receiving Modbus RTU client request: {e}")
#
#
# def process_modbus_request(context, request, serial_port):
#     print("Processing Modbus RTU client request")
#     print("Request inside process modbus request is .....:", request)
#
#     try:
#         # Extracting slave ID, function code, start address, and number of registers to read from the request
#         slave_id = request[0]
#         print("Slave ID is....:", slave_id)
#         function_code = request[1]
#         print("Function code is....:", function_code)
#         start_address = int.from_bytes(request[2:4], byteorder='big', signed=False)  # Assuming unsigned bytes
#         print("Start address is....:", start_address)
#         num_registers = int.from_bytes(request[4:6], byteorder='big', signed=False)  # Assuming unsigned bytes
#         print("Number of registers to read is....:", num_registers)
#
#         # Get values from holding registers based on the extracted parameters from the request
#         values = context[0].getValues(slave_id, start_address, num_registers)
#         print("Values are....:", values)
#
#         if values:
#             # Convert byte array to integer values
#             int_values = []
#             for i in range(0, len(values), 2):
#                 int_values.append(
#                     int.from_bytes(values[i:i + 2], byteorder='big', signed=True))  # Assuming signed bytes
#
#             # Create a bytearray from the integer values
#             response = bytearray(int_values)
#
#             # Send response to the client
#             serial_port.write(response)
#             print("Values sent to Modbus RTU client:", response)
#         else:
#             # If no values found, send an error response (exception code 2)
#             response = bytearray([0x83, 0x02])
#             # Send error response to the client
#             serial_port.write(response)
#             print("Error response sent to Modbus RTU client:", response.hex())
#
#     except Exception as e:
#         # If an error occurs during request handling, print the error
#         print("Error handling Modbus RTU client request:", e)
#
#
# # def process_modbus_request(context, request, serial_port):
# #     print("Processing Modbus RTU client request")
# #     print("Request inside process modbus request is .....:", request)
# #
# #     try:
# #         # Extracting slave ID, function code, start address, and number of registers to read from the request
# #         slave_id = request[0]
# #         print("Slave ID is....:", slave_id)
# #         function_code = request[1]
# #         print("Function code is....:", function_code)
# #         start_address = int.from_bytes(request[2:4], byteorder='big', signed=False)  # Assuming unsigned bytes
# #         if start_address < 0:
# #             raise ValueError("Start address cannot be negative")
# #         print("Start address is....:", start_address)
# #         num_registers = int.from_bytes(request[4:6], byteorder='big', signed=False)  # Assuming unsigned bytes
# #         if num_registers < 0:
# #             raise ValueError("Number of registers cannot be negative")
# #         print("Number of registers to read is....:", num_registers)
# #
# #         # Get values from holding registers based on the extracted parameters from the request
# #         values = context[0].getValues(slave_id, start_address, num_registers)
# #         print("Values are....:", values)
# #
# #         if values:
# #             # Ensure all values are converted to unsigned integers
# #             values = [value & 0xFFFF for value in values]
# #
# #             # Construct the response bytearray
# #             response = bytearray([slave_id, function_code])  # Slave ID and function code
# #             response_length = min(len(values) * 2, 255)  # Limit the response length to 255 bytes
# #             response.append(response_length)  # Length byte
# #
# #             # Add register values to the response
# #             for value in values:
# #                 response.extend(value.to_bytes(2, byteorder='big'))
# #
# #             # Send response to the client
# #             serial_port.write(response)
# #             print("Values sent to Modbus RTU client:", response)
# #         else:
# #             # If no values found, send an error response (exception code 2)
# #             response = bytearray([slave_id, function_code + 0x80, 0x02])  # Set high bit for exception code
# #             # Send error response to the client
# #             serial_port.write(response)
# #             print("Error response sent to Modbus RTU client:", response.hex())
# #
# #     except Exception as e:
# #         # If an error occurs during request handling, print the error
# #         print("Error handling Modbus RTU client request:", e)
#
#
# def start_main():
#     try:
#         print("Starting Modbus RTU Server...")
#         logging.info("Starting Modbus RTU Server...")
#         context = configure_modbus_server()
#
#         # Create a thread for updating sensor values
#         sensor_thread = threading.Thread(target=update_sensor_values, args=(context,))
#         sensor_thread.start()
#
#         # Create a serial port
#         serial_port = serial.Serial(**serial_settings)
#
#         # Create a thread for handling Modbus requests
#         request_thread = threading.Thread(target=handle_modbus_request, args=(context, serial_port))
#         request_thread.start()
#
#         # Start the Modbus RTU server
#         run_modbus_server(context)
#
#         # Wait for both threads to finish
#         sensor_thread.join()
#         request_thread.join()
#
#     except KeyboardInterrupt:
#         logging.info("Main thread Stopped by user")
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")
#
# if __name__ == "__main__":
#     start_main()


# from pymodbus.server.sync import StartSerialServer
# import serial
# import threading
# import logging
# import time
# from datetime import datetime
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# from pymodbus.payload import BinaryPayloadBuilder
# from pymodbus.constants import Endian
# from pymodbus.payload import BinaryPayloadBuilder
# import crcmod
#
# import logging
# import asyncio
# from datetime import datetime
# import serial
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusServerContext, ModbusSlaveContext, ModbusSequentialDataBlock
# from pymodbus.transaction import ModbusRtuFramer
#
#
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Unit ID for the Modbus device
# UNIT_ID = 1
#
# # Define serial settings
# serial_settings = {
#     'port': 'COM3',
#     'baudrate': 9600,
#     'bytesize': serial.EIGHTBITS,
#     'parity': serial.PARITY_NONE,
#     'stopbits': serial.STOPBITS_ONE,
#     'timeout': 1
# }
#
# # Read data from file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
# def update_holding_registers(context):
#     try:
#         params = read_params_from_file()
#         if params:
#             date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
#             scaled_temp = int(temp_c * 10)
#             scaled_humidity = int(humidity * 100)
#             scaled_wind_speed = int(wind_speed * 100)
#             scaled_wind_dir = int(wind_dir * 10)
#             scaled_rainfall = int(rainfall * 100)
#             holding_register_values = [
#                 date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#                 scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             ]
#             context[0].setValues(1, 0, holding_register_values)  # Slave ID: 1, Holding Register Address: 0
#             print("Values written to holding register:", holding_register_values)
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#
# def configure_modbus_server():
#     store = ModbusSlaveContext()
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
# def run_modbus_server(context):
#     try:
#         #Configure serial port
#         serial_port = serial.Serial(
#             port='COM3',
#             baudrate=9600,
#             bytesize=serial.EIGHTBITS,  # Data bits: 8
#             parity=serial.PARITY_NONE,  # Parity: None
#             stopbits=serial.STOPBITS_ONE,  # Stop bits: 1
#             timeout=1  # Timeout in seconds
#         )
#
#         server = StartSerialServer(context[0], framer=ModbusRtuFramer, port=serial_port, timeout=1)
#         print("Modbus RTU Server started successfully")
#         server.serve_forever()
#     except Exception as e:
#         logging.error(f"Error starting Modbus RTU Server: {e}")
#
# def update_sensor_values(context):
#     while True:
#         print("Updating holding registers with sensor values...")
#         update_holding_registers(context)
#         time.sleep(60)  # Update sensor data every minute
#
# def handle_modbus_requests(context, serial_port):
#     while True:
#         try:
#             print("Waiting for Modbus RTU client request...")
#             request = serial_port.read(8)  # Read 8 bytes (Modbus RTU request length)
#             if request:
#                 print("Received Modbus RTU client request:", request.hex())
#                 handle_modbus_request(context, request, serial_port)
#         except Exception as e:
#             logging.error(f"Error receiving Modbus RTU client request: {e}")
#
#
# # def handle_modbus_request(context, request, serial_port):
# #     hex_request = request.hex()
# #     print("Received Modbus RTU client request:", hex_request)
# #
# #     print("Checking the request...")
# #     # Get values from holding registers
# #     values = context[0].getValues(1, 0, 12)  # Slave ID: 1, Holding Register Address: 0, Number of Registers: 12
# #     print("Values getting from holding reg:", values)
# #
# #     # Convert values to a string of decimal values separated by commas
# #     values_decimal_str = ','.join([str(value) for value in values])
# #     print("Values in Modscan32 format:", values_decimal_str)
# #
# #     # Send values to Modscan32
# #     serial_port.write(values_decimal_str.encode())
# #
# #     # Print the values sent
# #     print("Values sent to Modscan32:", values_decimal_str)
# #
# def handle_modbus_request(context, request, serial_port):
#     print("Received Modbus RTU client request:", request.hex())
#
#     # Extracting function code and register address from the request
#     function_code = request[1]
#     register_address = int.from_bytes(request[2:4], byteorder='big')
#
#     if function_code == 3:  # Read Holding Registers
#         # Get values from holding registers
#         values = context[0].getValues(1, register_address, REGISTER_SIZE)
#         if values:
#             # Convert values to bytes
#             response = bytearray([len(values) * 2]) + bytearray(values)
#             # Send response to the client
#             serial_port.write(response)
#             print("Values sent to Modbus RTU client:", response.hex())
#         else:
#             # If no values found, send an error response (exception code 2)
#             response = bytearray([0x83, 0x02])
#             # Send error response to the client
#             serial_port.write(response)
#             print("Error response sent to Modbus RTU client:", response.hex())
#
#     else:
#         # If the function code is not supported, send an error response (exception code 1)
#         response = bytearray([0x83, 0x01])
#         # Send error response to the client
#         serial_port.write(response)
#         print("Error response sent to Modbus RTU client:", response.hex())
#
#     # Convert values to bytes
#     #response_bytes = b"".join([value.to_bytes(2, byteorder='big', signed=True) for value in values])
#     #values_decimal_str = ','.join([str(value) for value in values])
#
#     # Send values to Modscan32
#     #serial_port.write(response_bytes)
#     #serial_port.write(values_decimal_str.encode())
#
#     # Print the values sent
#     #print("Values sent to Modscan32:", response_bytes)
#     #print("Values sent to Modscan32:", values_decimal_str)
#
# ######## WORKING AND OUTPUT IN HEX ######
#
#     # hex_request = request.hex()
#     # print("Received Modbus RTU client request:", hex_request)
#     #
#     # print("Checking the request...")
#     # # Get values from holding registers
#     # values = context[0].getValues(1, 0, 12)  # Slave ID: 1, Holding Register Address: 0, Number of Registers: 12
#     # print("Values getting from holding reg:", values)
#     # #serial_port.write(values)
#     #
#     # # Convert values to a string of hexadecimal bytes separated by commas
#     # values_hex_str = ','.join([format(value, '04X') for value in values])
#     # print("Values in Modscan32 format:", values_hex_str)
#     #
#     # # Send values to Modscan32
#     # #serial_port.write(values_hex_str.encode())
#     #
#     # # Print the values sent
#     # print("Values sent to Modscan32:", values_hex_str)
#
#     ###################
#
#     # Convert values to bytes
#     # response_bytes = b""
#     # for value in values:
#     #     response_bytes += value.to_bytes(2, byteorder='big', signed=True)
#     # #serial_port.write(response_bytes)
#
#     # response_values = []
#     # for value in values:
#     #     response_values.append(
#     #         int.from_bytes(value.to_bytes(2, byteorder='big', signed=True), byteorder='big', signed=True))
#     #
#     # # Write response values to the serial port
#     # response_bytes = bytearray(response_values)
#     # print("Response value ....:", response_bytes)
#     # serial_port.write(response_values)
#
#     # # Create CRC-16 function
#     # crc16 = crcmod.predefined.mkCrcFun('modbus')
#     #
#     # # Convert values to integers and append to the response list
#     # response_values = []
#     # for value in values:
#     #     response_values.append(
#     #         int.from_bytes(value.to_bytes(2, byteorder='big', signed=True), byteorder='big', signed=True))
#     #
#     # # Calculate CRC over the response values
#     # crc = crc16(bytearray(response_values))
#     #
#     # # Append CRC to the response
#     # response_bytes = bytearray(response_values) + crc.to_bytes(2, byteorder='little')
#     #
#     # # Write response bytes to the serial port
#     # serial_port.write(response_bytes)
#
#     # Write response bytes to the serial port
#     #print("Response bytes to be sent to Modbus RTU client:", response_bytes)
#     #serial_port.write(response_bytes)
#
#     ######## WORKING AND OUTPUT IN HEX ######
#
# def start_main():
#     try:
#         print("Starting Modbus RTU Server...")
#         logging.info("Starting Modbus RTU Server...")
#         context = configure_modbus_server()
#
#         # Create a thread for updating sensor values
#         sensor_thread = threading.Thread(target=update_sensor_values, args=(context,))
#         sensor_thread.start()
#
#         # Create a serial port
#         serial_port = serial.Serial(
#             port='COM3',
#             baudrate=4800,
#             bytesize=serial.EIGHTBITS,  # Data bits: 8
#             parity=serial.PARITY_NONE,  # Parity: None
#             stopbits=serial.STOPBITS_ONE,  # Stop bits: 1
#             timeout=1  # Timeout in seconds
#         )
#
#         # Create a thread for handling Modbus requests
#         request_thread = threading.Thread(target=handle_modbus_requests, args=(context, serial_port))
#         request_thread.start()
#
#         # Start the Modbus RTU server
#         run_modbus_server(context)
#
#         # Wait for both threads to finish
#         sensor_thread.join()
#         request_thread.join()
#
#     except KeyboardInterrupt:
#         logging.info("Main thread Stopped by user")
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")
#
# if __name__ == "__main__":
#     start_main()
#


#
# import threading
# import time
# import logging
# from datetime import datetime
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# import serial
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Unit ID for the Modbus device
# UNIT_ID = 1
#
# # Read data from file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
#
# def update_holding_registers(context):
#     try:
#         params = read_params_from_file()
#         if params:
#             date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
#             scaled_temp = int(temp_c * 10)
#             scaled_humidity = int(humidity * 100)
#             scaled_wind_speed = int(wind_speed * 100)
#             scaled_wind_dir = int(wind_dir * 10)
#             scaled_rainfall = int(rainfall * 100)
#             holding_register_values = [
#                 date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#                 scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             ]
#             context[0].setValues(1, 0, holding_register_values)  # Slave ID: 1, Holding Register Address: 0
#             #values_written = context[0].getValues(1, 0, len(holding_register_values))  # Slave ID: 1, Holding Register Address: 0
#             print("Values written to holding register")
#             #print("Values written to holding register:", values_written)
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#
# def configure_modbus_server():
#     store = ModbusSlaveContext()
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
# def run_modbus_server(context):
#     try:
#         # Configure serial port
#         serial_port = serial.Serial(
#             port='COM5',
#             baudrate=9600,
#             bytesize=serial.EIGHTBITS,  # Data bits: 8
#             parity=serial.PARITY_NONE,  # Parity: None
#             stopbits=serial.STOPBITS_ONE,  # Stop bits: 1
#             timeout=1  # Timeout in seconds
#         )
#
#         server = StartSerialServer(context[0], framer=ModbusRtuFramer, port=serial_port, timeout=1)
#         print("Modbus RTU Server started successfully")
#         server.serve_forever()
#     except Exception as e:
#         logging.error(f"Error starting Modbus RTU Server: {e}")
#
# def update_sensor_values(context):
#     while True:
#         print("Updating holding registers with sensor values...")
#         update_holding_registers(context)
#         time.sleep(60)  # Update sensor data every minute
#
# def handle_modbus_requests(context, serial_port):
#     while True:
#         try:
#             print("Waiting for Modbus RTU client request...")
#             request = serial_port.read(8)  # Read 8 bytes (Modbus RTU request length)
#             if request:
#                 print("Received Modbus RTU client request:", request.hex())
#                 handle_modbus_request(context, request, serial_port)
#         except Exception as e:
#             logging.error(f"Error receiving Modbus RTU client request: {e}")
#
# def handle_modbus_request(context, request, serial_port):
#     hex_request = request.hex()
#     if hex_request[:4] == "0103" and hex_request[4:8] == "0000":
#         print("Checking the request...")
#         # Read holding register values
#         values = context[0].getValues(1, 0, 12)  # Slave ID: 1, Holding Register Address: 0, Number of Registers: 12
#         print("Values getting from holding reg.....",values)
#         if values is None:
#             logging.error("Requested address is out of range")
#             print("Requested address is out of range")
#             response = [131, 3]  # Exception Response: Illegal Data Address
#         else:
#             # Convert each big integer value into bytes
#             response_bytes = b"".join(value.to_bytes(2, byteorder="big", signed=True) for value in values)
#             # Write response bytes to the serial port
#             serial_port.write(response_bytes)
#             print("Response bytes sent to Modbus RTU client", response_bytes)
#     else:
#         print("Request not matched.")
#
# def start_main():
#     try:
#         print("Starting Modbus RTU Server...")
#         logging.info("Starting Modbus RTU Server...")
#         context = configure_modbus_server()
#
#         # Create a serial port
#         serial_port = serial.Serial(
#             port='COM5',
#             baudrate=9600,
#             bytesize=serial.EIGHTBITS,  # Data bits: 8
#             parity=serial.PARITY_NONE,  # Parity: None
#             stopbits=serial.STOPBITS_ONE,  # Stop bits: 1
#             timeout=1  # Timeout in seconds
#         )
#
#         # Start the Modbus RTU server
#         run_modbus_server(context)
#
#         # Create a thread for updating sensor values
#         sensor_thread = threading.Thread(target=update_sensor_values, args=(context,))
#         sensor_thread.start()
#
#         # Create a thread for handling Modbus requests
#         request_thread = threading.Thread(target=handle_modbus_requests, args=(context, serial_port))
#         request_thread.start()
#
#         # Wait for both threads to finish
#         sensor_thread.join()
#         request_thread.join()
#
#     except KeyboardInterrupt:
#         logging.info("Main thread Stopped by user")
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")
#
# if __name__ == "__main__":
#     start_main()
#


# import threading
# import time
# import logging
# from datetime import datetime
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# import serial
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Unit ID for the Modbus device
# UNIT_ID = 1
#
# # Read data from file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
# # Update holding registers with parameter values
# def update_holding_registers(context):
#     try:
#         params = read_params_from_file()
#         if params:
#             date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
#             scaled_temp = int(temp_c * 10)
#             scaled_humidity = int(humidity * 100)
#             scaled_wind_speed = int(wind_speed * 100)
#             scaled_wind_dir = int(wind_dir * 10)
#             scaled_rainfall = int(rainfall * 100)
#             holding_register_values = [
#                 #UNIT_ID,  # Include UNIT_ID as the first value
#                 date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#                 scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             ]
#             print(holding_register_values)
#             context[0].setValues(1, 0, holding_register_values)  # Slave ID: 1, Holding Register Address: 0
#             values_written = context[0].getValues(1, 0, len(holding_register_values))  # Slave ID: 1, Holding Register Address: 0
#
#             print("Values written to holding register:", values_written)
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#
# # Handle Modbus request
# def handle_modbus_request(context, request, serial_port):
#     hex_request = request.hex()
#     if hex_request == "01030000000c45cf":
#         print("Thread 2 started: Checking the request...")
#         # Read holding register values
#         values = context[0].getValues(1, 0, 12)  # Slave ID: 1, Holding Register Address: 0, Number of Registers: 12
#         if values is None:
#             logging.error("Requested address is out of range")
#             print("Requested address is out of range")
#             response = [131, 3]  # Exception Response: Illegal Data Address
#         else:
#             response = values  # Return values to send as response
#             print("Response to Modbus RTU client request:", response)
#             # Ensure all values are within range (0 to 255)
#             response_bytes = bytes([min(max(value, 0), 255) for value in response])
#             # Write response bytes to the serial port
#             serial_port.write(response_bytes)
#             print("Response sent to Modbus RTU client")
#     else:
#         print("Request not matched.")
#
# # Modbus RTU server configuration
# def configure_modbus_server():
#     store = ModbusSlaveContext()
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
# def run_modbus_server(context):
#     try:
#         # Configure serial port
#         serial_port = serial.Serial(
#             port='COM5',
#             baudrate=9600,
#             bytesize=serial.EIGHTBITS,  # Data bits: 8
#             parity=serial.PARITY_NONE,  # Parity: None
#             stopbits=serial.STOPBITS_ONE,  # Stop bits: 1
#             timeout=1  # Timeout in seconds
#         )
#
#         server = StartSerialServer(context[0], framer=ModbusRtuFramer, port=serial_port, timeout=1)
#         print("Modbus RTU Server started successfully")
#         server.serve_forever()
#     except Exception as e:
#         logging.error(f"Error starting Modbus RTU Server: {e}")
#
#     # Listen for Modbus RTU client requests
#     while True:
#         try:
#             print("Waiting for Modbus RTU client request...")
#             request = serial_port.read(8)  # Read 8 bytes (Modbus RTU request length)
#             if request:
#                 print("Received Modbus RTU client request:", request.hex())
#                 # Create a thread to handle the request
#                 request_thread = threading.Thread(target=handle_modbus_request, args=(context, request, serial_port))
#                 request_thread.start()
#         except Exception as e:
#             logging.error(f"Error receiving Modbus RTU client request: {e}")
#
#         # Wait for 1 minute before checking for requests again
#         time.sleep(60)
#
# def start_main():
#     try:
#         print("Starting Modbus RTU Server...")
#         logging.info("Starting Modbus RTU Server...")
#         context = configure_modbus_server()
#
#         # Create a thread for reading sensor values and updating holding registers
#         sensor_thread = threading.Thread(target=update_sensor_values, args=(context,))
#         sensor_thread.start()
#
#         # Start the Modbus RTU server
#         server_thread = threading.Thread(target=run_modbus_server, args=(context,))
#         server_thread.start()
#
#         # Wait for both threads to finish
#         sensor_thread.join()
#         server_thread.join()
#
#     except KeyboardInterrupt:
#         logging.info("Main thread Stopped by user")
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")
#
# def update_sensor_values(context):
#     while True:
#         print("Thread 1 started: Reading sensor values and updating holding registers...")
#         update_holding_registers(context)
#         time.sleep(60)  # Update sensor data every minute
#
# if __name__ == "__main__":
#     start_main()
#


#
# import threading
# import time
# import logging
# from datetime import datetime
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# import serial
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Unit ID for the Modbus device
# UNIT_ID = 1
#
# # Read data from file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
# # Update holding registers with parameter values
# def update_holding_registers(context):
#     try:
#         params = read_params_from_file()
#         if params:
#             date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
#             scaled_temp = int(temp_c * 10)
#             scaled_humidity = int(humidity * 100)
#             scaled_wind_speed = int(wind_speed * 100)
#             scaled_wind_dir = int(wind_dir * 10)
#             scaled_rainfall = int(rainfall * 100)
#             holding_register_values = [
#                 UNIT_ID,  # Include UNIT_ID as the first value
#                 date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#                 scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             ]
#             context[0].setValues(1, 0, holding_register_values)  # Slave ID: 1, Holding Register Address: 0
#             values_written = context[0].getValues(1, 0, len(holding_register_values))  # Slave ID: 1, Holding Register Address: 0
#             print("Values written to holding register:", values_written)
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#
# # Handle Modbus request
# def handle_modbus_request(context, request, serial_port):
#     hex_request = request.hex()
#     if hex_request == "01030000000c45cf":
#         print("Thread 2 started: Checking the request...")
#         # Read holding register values
#         values = context[0].getValues(1, 0, 12)  # Slave ID: 1, Holding Register Address: 0, Number of Registers: 12
#         if values is None:
#             logging.error("Requested address is out of range")
#             print("Requested address is out of range")
#             response = [131, 3]  # Exception Response: Illegal Data Address
#         else:
#             response = values  # Return values to send as response
#             print("Response to Modbus RTU client request:", response)
#             # Convert response values to bytes
#             response_bytes = bytes(response)
#             # Write response bytes to the serial port
#             serial_port.write(response_bytes)
#             print("Response sent to Modbus RTU client")
#     else:
#         print("Request not matched.")
#
# # Modbus RTU server configuration
# def configure_modbus_server():
#     store = ModbusSlaveContext()
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
# def run_modbus_server(context):
#     try:
#         # Configure serial port
#         serial_port = serial.Serial(
#             port='COM5',
#             baudrate=9600,
#             bytesize=serial.EIGHTBITS,  # Data bits: 8
#             parity=serial.PARITY_NONE,  # Parity: None
#             stopbits=serial.STOPBITS_ONE,  # Stop bits: 1
#             timeout=1  # Timeout in seconds
#         )
#
#         server = StartSerialServer(context[0], framer=ModbusRtuFramer, port=serial_port, timeout=1)
#         print("Modbus RTU Server started successfully")
#         server.serve_forever()
#     except Exception as e:
#         logging.error(f"Error starting Modbus RTU Server: {e}")
#
#     # Listen for Modbus RTU client requests
#     while True:
#         try:
#             print("Waiting for Modbus RTU client request...")
#             request = serial_port.read(8)  # Read 8 bytes (Modbus RTU request length)
#             if request:
#                 print("Received Modbus RTU client request:", request.hex())
#                 # Create a thread to handle the request
#                 request_thread = threading.Thread(target=handle_modbus_request, args=(context, request, serial_port))
#                 request_thread.start()
#         except Exception as e:
#             logging.error(f"Error receiving Modbus RTU client request: {e}")
#
#         # Wait for 1 minute before checking for requests again
#         time.sleep(60)
#
# def start_main():
#     try:
#         print("Starting Modbus RTU Server...")
#         logging.info("Starting Modbus RTU Server...")
#         context = configure_modbus_server()
#
#         # Create a thread for reading sensor values and updating holding registers
#         sensor_thread = threading.Thread(target=update_sensor_values, args=(context,))
#         sensor_thread.start()
#
#         # Start the Modbus RTU server
#         server_thread = threading.Thread(target=run_modbus_server, args=(context,))
#         server_thread.start()
#
#         # Wait for both threads to finish
#         sensor_thread.join()
#         server_thread.join()
#
#     except KeyboardInterrupt:
#         logging.info("Main thread Stopped by user")
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")
#
# def update_sensor_values(context):
#     while True:
#         print("Thread 1 started: Reading sensor values and updating holding registers...")
#         update_holding_registers(context)
#         time.sleep(60)  # Update sensor data every minute
#
# if __name__ == "__main__":
#     start_main()
#






# import threading
# import time
# import logging
# from datetime import datetime
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# import serial
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Unit ID for the Modbus device
# UNIT_ID = 1
#
# # Read data from file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
# # Update holding registers with parameter values
# def update_holding_registers(context):
#     try:
#         params = read_params_from_file()
#         if params:
#             date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
#             scaled_temp = int(temp_c * 10)
#             scaled_humidity = int(humidity * 100)
#             scaled_wind_speed = int(wind_speed * 100)
#             scaled_wind_dir = int(wind_dir * 10)
#             scaled_rainfall = int(rainfall * 100)
#             holding_register_values = [
#                 UNIT_ID,  # Include UNIT_ID as the first value
#                 date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#                 scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             ]
#             context[0].setValues(1, 0, holding_register_values)  # Slave ID: 1, Holding Register Address: 0
#             values_written = context[0].getValues(1, 0, len(holding_register_values))  # Slave ID: 1, Holding Register Address: 0
#             print("Values written to holding register:", values_written)
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#
#
#
# # Modbus RTU server configuration
# def configure_modbus_server():
#     store = ModbusSlaveContext()
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
# def run_modbus_server(context):
#     try:
#         # Configure serial port
#         serial_port = serial.Serial(
#             port='COM5',
#             baudrate=9600,
#             bytesize=serial.EIGHTBITS,  # Data bits: 8
#             parity=serial.PARITY_NONE,  # Parity: None
#             stopbits=serial.STOPBITS_ONE,  # Stop bits: 1
#             timeout=1  # Timeout in seconds
#         )
#
#         server = StartSerialServer(context[0], framer=ModbusRtuFramer, port=serial_port, timeout=1)
#         print("Modbus RTU Server started successfully")
#         server.serve_forever()
#     except Exception as e:
#         logging.error(f"Error starting Modbus RTU Server: {e}")
#
#     # Listen for Modbus RTU client requests
#     while True:
#         try:
#             print("Waiting for Modbus RTU client request...")
#             request = serial_port.read(8)  # Read 8 bytes (Modbus RTU request length)
#             if request:
#                 print("Received Modbus RTU client request:", request.hex())
#                 # Create a thread to handle the request
#                 request_thread = threading.Thread(target=handle_modbus_request, args=(context, request))
#                 request_thread.start()
#         except Exception as e:
#             logging.error(f"Error receiving Modbus RTU client request: {e}")
#
#         # Wait for 1 minute before checking for requests again
#         time.sleep(1)
#
# def handle_modbus_request(context, request):
#     hex_request = request.hex()
#     if hex_request == "01030000000c45cf":
#         print("Thread 2 started: Checking the request...")
#         # Convert hexadecimal string to bytes
#         request_bytes = bytes.fromhex(hex_request)
#         # Extract components from request bytes
#         slave_id = request_bytes[0]
#         function_code = request_bytes[1]
#         start_address = (request_bytes[2] << 8) + request_bytes[3]  # Combine two bytes to get start address
#         num_registers = (request_bytes[4] << 8) + request_bytes[5]  # Combine two bytes to get number of registers
#
#         if slave_id == UNIT_ID and function_code == 3 and start_address == 0 and num_registers == 12:
#             logging.info("Received valid Modbus request")
#             print("Received valid Modbus request")
#
#             # Read holding register values
#             values = context[0].getValues(1, 0, num_registers)  # Slave ID: 1, Holding Register Address: 0
#             if values is None:
#                 logging.error("Requested address is out of range")
#                 print("Requested address is out of range")
#                 response = [131, 3]  # Exception Response: Illegal Data Address
#             else:
#                 response = values  # Return values to send as response
#             print("Response to Modbus RTU client request:", response)
#             return response
#         else:
#             logging.warning("Received invalid Modbus request")
#             print("Received invalid Modbus request")
#             return None
#
#     else:
#         print("Request not matched.")
#         return None
#
#
# def start_main():
#     try:
#         print("Starting Modbus RTU Server...")
#         logging.info("Starting Modbus RTU Server...")
#         context = configure_modbus_server()
#
#         # Create a thread for reading sensor values and updating holding registers
#         sensor_thread = threading.Thread(target=update_sensor_values, args=(context,))
#         sensor_thread.start()
#
#         # Start the Modbus RTU server
#         server_thread = threading.Thread(target=run_modbus_server, args=(context,))
#         server_thread.start()
#
#         # Wait for both threads to finish
#         sensor_thread.join()
#         server_thread.join()
#
#     except KeyboardInterrupt:
#         logging.info("Main thread Stopped by user")
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")
#
# def update_sensor_values(context):
#     while True:
#         print("Thread 1 started: Reading sensor values and updating holding registers...")
#         update_holding_registers(context)
#         time.sleep(60)  # Update sensor data every minute
#
# if __name__ == "__main__":
#     start_main()
#





#
#
# import logging
# from datetime import datetime
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# import time
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO,
#                     format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Unit ID for the Modbus device
# UNIT_ID = 1
#
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
#
# # Prepare parameter values
# def prepare_parameter_values():
#     try:
#         params = read_params_from_file()
#         if params:
#             return params
#     except Exception as e:
#         logging.error(f"Error preparing parameter values: {e}")
#         return None
#
#
# # Update holding registers with parameter values
# def update_holding_registers(context):
#     try:
#         params = prepare_parameter_values()
#         if params:
#             hr_block = [int(value) for value in params]  # Convert values to integers
#             context[0].setValues(3, 0, hr_block)
#             logging.info("Updated holding registers with parameter values")
#             print("Updated holding registers with parameter values")
#             print("Sensor values written to holding register:",
#                   params)  # Print the sensor values written to holding register
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#         print(f"Error updating holding registers: {e}")
#
#
# # Handle Modbus request
# def handle_modbus_request(context, request):
#     slave_id = request[0]
#     function_code = request[1]
#     start_address = request[2]
#     num_registers = request[3]
#
#     if slave_id == UNIT_ID and function_code == 3 and start_address == 0 and num_registers == 12:
#         logging.info(f"Received valid Modbus request: {request}")
#         print(f"Received valid Modbus request: {request}")
#
#         # Read holding register values
#         values = context[0].getValues(3, start_address, num_registers)
#         if values is None:
#             logging.error("Requested address is out of range")
#             print("Requested address is out of range")
#             return [131, 3]  # Exception Response: Illegal Data Address
#         return values  # Return values to send as response
#
#     else:
#         logging.warning("Received invalid Modbus request")
#         print("Received invalid Modbus request")
#         return None
#
#
# # Modbus RTU server configuration
# def configure_modbus_server():
#     # Define a ModbusSequentialDataBlock for holding registers
#     holding_registers = ModbusSequentialDataBlock(0, [0] * 12)  # Initialize holding registers with 12 zeros
#     # Define a ModbusSlaveContext with the holding registers
#     store = ModbusSlaveContext(hr=holding_registers)
#     # Define a ModbusServerContext with the slave context
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
#
# # Main function
# if __name__ == "__main__":
#     logging.info("Starting Modbus RTU Server...")
#     print("Starting Modbus RTU Server...")
#     server_context = configure_modbus_server()
#
#     try:
#         server = StartSerialServer(server_context, framer=ModbusRtuFramer, port='COM5', baudrate=19200, timeout=2,
#                                    ignore_crc_errors=True)
#         logging.info("Modbus RTU Server started successfully")
#         print("Modbus RTU Server started successfully")
#
#         while True:
#             # Read sensor values and update holding registers
#             update_holding_registers(server_context)
#
#             # Wait for 1 minute
#             time.sleep(60)
#
#             # Execute Modbus request to read holding registers
#             request = (UNIT_ID, 3, 0, 12)
#             logging.info("Executing Modbus request to read holding registers...")
#             print("Executing Modbus request to read holding registers...")
#             response = handle_modbus_request(server_context, request)
#             if response:
#                 logging.info("Received Modbus response: %s", response)
#                 print("Received Modbus response:", response)
#
#     except KeyboardInterrupt:
#         logging.info("Server Stopped by user")
#         print("Server Stopped by user")
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")
#         print(f"An error occurred: {e}")
#





# import threading
# import time
# import logging
# from datetime import datetime
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# import serial
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Unit ID for the Modbus device
# UNIT_ID = 1
#
# # Read data from file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
#
# def update_holding_registers(context):
#     try:
#         params = read_params_from_file()
#         if params:
#             date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
#             scaled_temp = int(temp_c * 10)
#             scaled_humidity = int(humidity * 100)
#             scaled_wind_speed = int(wind_speed * 100)
#             scaled_wind_dir = int(wind_dir * 10)
#             scaled_rainfall = int(rainfall * 100)
#             holding_register_values = [
#                 date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#                 scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             ]
#             context[0].setValues(1, 0, holding_register_values)  # Slave ID: 1, Holding Register Address: 0
#             values_written = context[0].getValues(1, 0, len(holding_register_values))  # Slave ID: 1, Holding Register Address: 0
#             print("Values written to holding register:", values_written)
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#
# def configure_modbus_server():
#     store = ModbusSlaveContext()
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
# def run_modbus_server(context):
#     try:
#         # Configure serial port
#         serial_port = serial.Serial(
#             port='COM5',
#             baudrate=9600,
#             bytesize=serial.EIGHTBITS,  # Data bits: 8
#             parity=serial.PARITY_NONE,  # Parity: None
#             stopbits=serial.STOPBITS_ONE,  # Stop bits: 1
#             timeout=1  # Timeout in seconds
#         )
#
#         server = StartSerialServer(context[0], framer=ModbusRtuFramer, port=serial_port, timeout=1)
#         print("Modbus RTU Server started successfully")
#         server.serve_forever()
#     except Exception as e:
#         logging.error(f"Error starting Modbus RTU Server: {e}")
#
# def start_main():
#     try:
#         print("Starting Modbus RTU Server...")
#         logging.info("Starting Modbus RTU Server...")
#         context = configure_modbus_server()
#         update_holding_registers(context)
#         server_thread = threading.Thread(target=run_modbus_server, args=(context,))
#         server_thread.start()
#
#         while True:
#             # Main thread can perform other tasks if needed
#             update_holding_registers(context)
#             time.sleep(60)  # Update sensor data every minute
#
#     except KeyboardInterrupt:
#         logging.info("Main thread Stopped by user")
#         server_thread.join()
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")
#
# if __name__ == "__main__":
#     start_main()
#
#



#
# import logging
# import serial
# from datetime import datetime
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# import time
# from pymodbus.constants import Endian
# from pymodbus.payload import BinaryPayloadBuilder
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Configure serial port
# serial_port = serial.Serial(
#     port='COM4',
#     baudrate=9600,
#     bytesize=serial.EIGHTBITS,  # Data bits: 8
#     parity=serial.PARITY_NONE,  # Parity: None
#     stopbits=serial.STOPBITS_ONE,  # Stop bits: 1
#     timeout=1  # Timeout in seconds
# )
#
# # Unit ID for the Modbus device
# UNIT_ID = 1
#
# # Read data from file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
# # Update holding registers with parameter values
# def update_holding_registers(context):
#     try:
#         params = read_params_from_file()
#         if params:
#             # Unpack parameters
#             date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
#
#             # Scale and clip values
#             scaled_temp = int(temp_c * 10)  # Scale temperature by 10
#             scaled_humidity = int(humidity * 100)  # Scale humidity by 100
#             scaled_wind_speed = int(wind_speed * 100)  # Scale wind speed by 100
#             scaled_wind_dir = int(wind_dir * 10)  # Scale wind direction by 10
#             scaled_rainfall = int(rainfall * 100)  # Scale rainfall by 100
#
#             # Write holding register values
#             holding_register_values = [
#                 date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#                 scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             ]
#
#             # Set values in the ModbusSequentialDataBlock
#             hr_block = []  # Initialize an empty list
#             for value in holding_register_values:
#                 hr_block.append(value)
#             context[0].setValues(3, 0, hr_block)
#             logging.info("Updated holding registers with parameter values")
#
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#
# # Modbus RTU server configuration
# def configure_modbus_server():
#     store = ModbusSlaveContext()
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
# # Main function
# if __name__ == "__main__":
#     try:
#         print("Starting Modbus RTU Server...")
#         logging.info("Starting Modbus RTU Server...")
#         server_context = configure_modbus_server()
#         server = StartSerialServer(server_context, framer=ModbusRtuFramer, port='COM4', timeout=1)  # Adjust timeout value as needed
#         print("Modbus RTU Server started successfully")
#         logging.info("Modbus RTU Server started successfully")
#
#         while True:
#             # Update sensor data
#             update_holding_registers(server_context)
#             time.sleep(30)  # Update sensor data every 30 seconds
#
#     except KeyboardInterrupt:
#         logging.info("Server Stopped by user")
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")
#



# import logging
# import serial
# from datetime import datetime
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# import time
# from pymodbus.constants import Endian
# from pymodbus.payload import BinaryPayloadBuilder
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Configure serial port
# serial_port = serial.Serial(
#     port='COM4',
#     baudrate=9600,
#     bytesize=serial.EIGHTBITS,  # Data bits: 8
#     parity=serial.PARITY_NONE,  # Parity: None
#     stopbits=serial.STOPBITS_ONE,  # Stop bits: 1
#     timeout=1  # Timeout in seconds
# )
#
# # Unit ID for the Modbus device
# UNIT_ID = 1
#
# # Read data from file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
# # Update holding registers with parameter values
# def update_holding_registers(context):
# #def update_holding_registers(server):
#     try:
#         params = read_params_from_file()
#         if params:
#             # Unpack parameters
#             date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
#
#             # Scale and clip values
#             scaled_temp = int(temp_c * 10)  # Scale temperature by 10
#             scaled_humidity = int(humidity * 100)  # Scale humidity by 100
#             scaled_wind_speed = int(wind_speed * 100)  # Scale wind speed by 100
#             scaled_wind_dir = int(wind_dir * 10)  # Scale wind direction by 10
#             scaled_rainfall = int(rainfall * 100)  # Scale rainfall by 100
#
#             # Write holding register values
#             holding_register_values = [
#                 date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#                 scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             ]
#
#             # Set values in the ModbusSequentialDataBlock
#             hr_block = []  # Initialize an empty list
#             for value in holding_register_values:
#                 hr_block.append(value)
#             context[0].setValues(3, 0, hr_block)
#             logging.info("Updated holding registers with parameter values")
#
#             # Get updated values from the holding registers
#             updated_values = context[0].getValues(3, 0, len(holding_register_values))
#
#             # Build the response packet
#             builder = BinaryPayloadBuilder(endian=Endian.Big)
#             for value in updated_values:
#                 builder.add_16bit_int(value)
#             response_payload = builder.build()
#
#             # Send the response to the Modbus RTU client
#             transaction = server_context[0].getTransaction(0)
#             transaction.setResponsePayload(response_payload)
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#
# # Modbus RTU server configuration
# def configure_modbus_server():
#     store = ModbusSlaveContext()
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
# # Main function
# if __name__ == "__main__":
#     try:
#         print("Starting Modbus RTU Server...")
#         logging.info("Starting Modbus RTU Server...")
#         server_context = configure_modbus_server()
#         server = StartSerialServer(server_context, framer=ModbusRtuFramer, port='COM4',
#                                    timeout=5)  # Adjust timeout value as needed
#         print("Modbus RTU Server started successfully")
#         logging.info("Modbus RTU Server started successfully")
#
#         while True:
#             # Wait for a Modbus RTU request
#             request = server.get_request()  # This will block until a request is received
#
#             # Extract request details
#             slave_id = request.slave_id
#             print(slave_id)
#             function_code = request.function_code
#             print(function_code)
#             address = request.address
#             print(address)
#             count = request.count
#             print(count)
#
#             # Log the received request
#             logging.info("Received Modbus RTU request: Slave ID=%s, Function Code=%s, Address=%s, Count=%s",
#                          slave_id, function_code, address, count)
#
#             # Update sensor data
#             update_holding_registers(server_context)
#             # update_holding_registers(server)
#             time.sleep(30)  # Update sensor data every minute
#
#             # Hardcoded request
#             start_address = 00
#             num_registers = 12
#
#             # Read holding registers
#             values_to_send = server_context[0].getValues(3, start_address, num_registers)
#
#             # Extract parameters
#             year = values_to_send[0]
#             month = values_to_send[1]
#             date = values_to_send[2]
#             hour = values_to_send[3]
#             minute = values_to_send[4]
#             second = values_to_send[5]
#             temperature = values_to_send[6]
#             humidity = values_to_send[7]
#             wind_speed = values_to_send[8]
#             wind_direction = values_to_send[9]
#             rainfall = values_to_send[10]
#
#             # Trim the list of values to remove any additional zeros
#             trimmed_values = [year, month, date, hour, minute, second, temperature, humidity, wind_speed,
#                               wind_direction, rainfall]
#
#             # Log holding register values
#             logging.info("Holding Register Values: Year=%s, Month=%s, Date=%s, Hour=%s, Minute=%s, Second=%s, "
#                          "Temperature=%s, Humidity=%s, Wind Speed=%s, Wind Direction=%s, Rainfall=%s",
#                          *trimmed_values)
#
#             # Respond to the Modbus RTU client with trimmed values
#             response = trimmed_values
#             logging.info("Sent Modbus response : %s", response)
#
#             # Print holding register values
#             print("Holding Register Values: Year={}, Month={}, Date={}, Hour={}, Minute={}, Second={}, "
#                   "Temperature={}, Humidity={}, Wind Speed={}, Wind Direction={}, Rainfall={}".format(
#                       *trimmed_values))
#
#             # Reset holding registers
#             server_context[0].setValues(3, start_address, [0] * num_registers)
#
#             # Wait for 5 milliseconds
#             time.sleep(0.005)
#
#     except KeyboardInterrupt:
#         logging.info("Server Stopped by user")
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")
#



#
# import logging
# from datetime import datetime
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# import time
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO,
#                     format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Unit ID for the Modbus device
# UNIT_ID = 1
#
#
# # Read data from file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
#
# # Update holding registers with parameter values
# def update_holding_registers(context):
#     try:
#         params = read_params_from_file()
#         if params:
#             # Unpack parameters
#             date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
#
#             # Scale and clip values
#             scaled_temp = int(temp_c * 10)  # Scale temperature by 10
#             scaled_humidity = int(humidity * 100)  # Scale humidity by 100
#             scaled_wind_speed = int(wind_speed * 100)  # Scale wind speed by 100
#             scaled_wind_dir = int(wind_dir * 10)  # Scale wind direction by 10
#             scaled_rainfall = int(rainfall * 100)  # Scale rainfall by 100
#
#             # Write holding register values
#             holding_register_values = [
#                 date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#                 scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             ]
#
#             # Set values in the ModbusSequentialDataBlock
#             hr_block = context[0].getValues(3, 0, len(holding_register_values))
#             for i, value in enumerate(holding_register_values):
#                 hr_block[i] = value
#             context[0].setValues(3, 0, hr_block)
#             logging.info("Updated holding registers with parameter values")
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#
#
#
#
# # Modbus RTU server configuration
# def configure_modbus_server():
#     store = ModbusSlaveContext(hr=ModbusSequentialDataBlock(0, [0] * 12))  # Holding Registers
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
#
# # Main function
# if __name__ == "__main__":
#     try:
#         logging.info("Starting Modbus RTU Server...")
#         server_context = configure_modbus_server()
#         server = StartSerialServer(server_context, framer=ModbusRtuFramer, port='COM4', baudrate=19200, timeout=2)
#         logging.info("Modbus RTU Server started successfully")
#         while True:
#             update_holding_registers(server_context)
#             time.sleep(60)  # Update sensor data every minute
#
#             # Hardcoded request
#             slave_id = 1
#             function_code = 3
#             start_address = 0
#             num_registers = 12
#
#             # Read holding registers
#             values_to_send = server_context[0].getValues(3, start_address, num_registers)
#             logging.info(f"Read holding registers at start address {start_address}: {values_to_send}")
#
#             # Respond to the Modbus RTU client
#             response = values_to_send
#             logging.info("Sent Modbus response : %s", response)
#
#             # Print holding register values
#             print("Holding Register Values:", response)
#
#             # Reset holding registers
#             server_context[0].setValues(3, start_address, [0] * num_registers)
#
#             # Wait for 5 milliseconds
#             time.sleep(0.005)
#
#     except KeyboardInterrupt:
#         logging.info("Server Stopped by user")
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")
#
#




# from pymodbus.server.sync import StartSerialServer
# from pymodbus.device import ModbusDeviceIdentification
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# import time
# import json
# import logging
#
# # Configure logging
# logging.basicConfig(filename='modbus_server.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Load sensor data from parameter file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = values[0]  # Leave as string
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
# # Write sensor data to holding registers
# def write_sensor_data(context, data):
#     for sensor_id, value in enumerate(data):
#         context[0].setValues(3, sensor_id, [value])
#
# # Reset holding registers
# def reset_holding_registers(context, num_registers):
#     for i in range(num_registers):
#         context[0].setValues(3, i, [0])
#
# # Modbus RTU server configuration
# def configure_modbus_server():
#     store = ModbusSlaveContext(hr=ModbusSequentialDataBlock(0, [0] * 12))
#     context = ModbusServerContext(slaves=store, single=True)
#     identity = ModbusDeviceIdentification()
#     identity.VendorName = 'OpenAI'
#     identity.ProductCode = 'MOD'
#     identity.VendorUrl = 'http://openai.com'
#     identity.ProductName = 'Modbus RTU Server'
#     identity.ModelName = 'Modbus RTU Server'
#     identity.MajorMinorRevision = '1.0'
#     return context, identity
#
# # Main function
# if __name__ == "__main__":
#     sensor_data = read_params_from_file()
#     server_context, server_identity = configure_modbus_server()
#
#     # Start Modbus RTU server
#     logging.info("Starting Modbus RTU server...")
#     server = StartSerialServer(server_context, framer=ModbusRtuFramer, identity=server_identity, port='/dev/ttyUSB0', baudrate=9600, timeout=2)
#     logging.info("Modbus RTU server started.")
#
#     try:
#         while True:
#             # Write sensor data to holding registers
#             write_sensor_data(server_context, sensor_data)
#             time.sleep(60)  # Update sensor data every minute
#
#             # Reset holding registers after writing
#             reset_holding_registers(server_context, 12)
#             time.sleep(60)  # Wait for 1 minute before resetting again
#
#     except KeyboardInterrupt:
#         logging.info("Server Stopped by User")
#










# ##### This code is for Modbus RTU Server (slave) #######
# import minimalmodbus
# import logging
# from time import sleep
# from datetime import datetime
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from serial import Serial
#
# # Define the serial port settings
# SERIAL_PORT = 'COM4'
# BAUDRATE = 9600
# PARITY = 'N'
# BYTESIZE = 8
# STOPBITS = 1
#
# # Define the unit ID
# UNIT_ID = 1
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO, format='%(asctime)s - %(message)s')
#
# # Create a Modbus server context
# store = ModbusSlaveContext(hr=ModbusSequentialDataBlock(0, [0] * 12))
# context = ModbusServerContext(slaves=store, single=True)
#
# # Read parameter values from file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
# # Update holding registers with parameter values
# def update_holding_registers():
#     try:
#         params = read_params_from_file()
#         if params:
#             # Unpack parameters
#             client_id = UNIT_ID
#             date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
#
#             # Scale and clip values
#             scaled_temp = int(temp_c * 10)  # Scale temperature by 10
#             scaled_humidity = int(humidity * 100)  # Scale humidity by 100
#             scaled_wind_speed = int(wind_speed * 100)  # Scale wind speed by 100
#             scaled_wind_dir = int(wind_dir * 10)  # Scale wind direction by 10
#             scaled_rainfall = int(rainfall * 100)  # Scale rainfall by 100
#
#             # Write holding register values
#             holding_register_values = [
#                 client_id, date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#                 scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             ]
#
#             # Set values in the Modbus RTU server
#             register_address = 1  # Start from address 1 (add0ress 0 is reserved for unit ID)
#             instrument.write_registers(register_address, holding_register_values)
#
#             # Log the data written to the holding registers
#             logging.info("Data written to holding registers: %s", holding_register_values)
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#
#
# # Open the serial port connection
# instrument = minimalmodbus.Instrument(SERIAL_PORT, UNIT_ID)
# instrument.serial.baudrate = BAUDRATE
# instrument.serial.parity = PARITY
# instrument.serial.bytesize = BYTESIZE
# instrument.serial.stopbits = STOPBITS
# instrument.serial.timeout = 1  # Timeout in seconds
#
# if __name__ == "__main__":
#     # Start the Modbus RTU server
#     print("Start server...")  # Debug statement
#     StartSerialServer(context, framer=None, identity=None, port=SERIAL_PORT)
#     print("Server is online")  # Debug statement
#
#     while True:
#         update_holding_registers()  # Update holding registers every minute
#         sleep(60)


# import logging
# from datetime import datetime
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# import time
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO,
#                     format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Unit ID for the Modbus device
# UNIT_ID = 1
#
#
# # Read data from file
# def read_params_from_file():
#     try:
#         with open("parameter_values.txt", 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return date_time, temp_c, humidity, wind_speed, wind_dir, rainfall
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
#
# # Prepare parameter values
# def prepare_parameter_values():
#     try:
#         params = read_params_from_file()
#         if params:
#             return params
#     except Exception as e:
#         logging.error(f"Error preparing parameter values: {e}")
#         return None
#
#
# # Update holding registers with parameter values
# def update_holding_registers(context):
#     try:
#         params = prepare_parameter_values()
#         if params:
#             # Unpack parameters
#             date_time, temp_c, humidity, wind_speed, wind_dir, rainfall = params
#
#             # Scale and clip values
#             scaled_temp = int(temp_c * 10)  # Scale temperature by 10
#             scaled_humidity = int(humidity * 100)  # Scale humidity by 100
#             scaled_wind_speed = int(wind_speed * 100)  # Scale wind speed by 100
#             scaled_wind_dir = int(wind_dir * 10)  # Scale wind direction by 10
#             scaled_rainfall = int(rainfall * 100)  # Scale rainfall by 100
#
#             # Write holding register values
#             holding_register_values = [
#                 date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#                 scaled_temp, scaled_humidity, scaled_wind_speed, scaled_wind_dir, scaled_rainfall
#             ]
#
#             # Set values in the ModbusSequentialDataBlock
#             hr_block = context[0].getValues(3, 0, len(holding_register_values))
#             for i, value in enumerate(holding_register_values):
#                 hr_block[i] = value
#             context[0].setValues(3, 0, hr_block)
#             logging.info("Updated holding registers with parameter values")
#     except Exception as e:
#         logging.error(f"Error updating holding registers: {e}")
#
#
# # Log request data
# def log_request_data(request):
#     logging.info(f"Request from Modbus RTU client: {request}")
#     # Extracting fields from the request
#     slave_id = request[0]
#     logging.info("Slave_ID : %s", slave_id)
#     print("Slave_ID : ", slave_id)
#     function_code = request[1]
#     logging.info("Function Code : %s", function_code)
#     print("Function Code : ", function_code)
#     start_address = request[2]
#     logging.info("Start Address : %s", start_address)
#     print("Start Address : ", start_address)
#     num_registers = request[3]
#     logging.info("Number of register to read : %s", num_registers)
#     print("Number of register to read : ", num_registers)
#
#
# # Modbus RTU server configuration
# def configure_modbus_server():
#     store = ModbusSlaveContext(hr=ModbusSequentialDataBlock(0, [0] * 12))  # Holding Registers
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
#
# # Main function
# if __name__ == "__main__":
#     logging.info("Starting Modbus RTU Server...")
#     server_context = configure_modbus_server()
#     try:
#         #server = StartSerialServer(server_context, framer=ModbusRtuFramer, port='/dev/ttyUSB0', baudrate=19200, timeout=2)
#         server = StartSerialServer(server_context, framer=ModbusRtuFramer, port='COM4', baudrate=19200,
#                                    timeout=2)
#         logging.info("Modbus RTU Server started successfully")
#
#         while True:
#             # Update holding registers with parameter values
#             update_holding_registers(server_context)
#             time.sleep(60)  # Update sensor data every minute
#
#     except KeyboardInterrupt:
#         logging.info("Server Stopped by user")
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")


#
#
# import logging
# from datetime import datetime
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
# from pymodbus.transaction import ModbusRtuFramer
# import time
#
# # Configure logging
# logging.basicConfig(filename='modbus_rtu_server.log', level=logging.INFO,
#                     format='%(asctime)s - %(levelname)s - %(message)s')
#
# # Unit ID for the Modbus device
# UNIT_ID = 1
#
#
# # Load sensor data from parameter file
# def read_params_from_file(file_path):
#     try:
#         with open(file_path, 'r') as file:
#             lines = file.readlines()
#             if lines:
#                 latest_line = lines[-1].strip()
#                 values = latest_line.split(', ')
#                 if len(values) == 6:
#                     # Extracting values
#                     date_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M:%S')
#                     temp_c = float(values[1])
#                     humidity = float(values[2])
#                     wind_speed = float(values[3])
#                     wind_dir = float(values[4])
#                     rainfall = float(values[5])
#
#                     return {
#                         "date_time": date_time,
#                         "temp_c": temp_c,
#                         "humidity": humidity,
#                         "wind_speed": wind_speed,
#                         "wind_dir": wind_dir,
#                         "rainfall": rainfall
#                     }
#                 else:
#                     logging.error("Invalid data format in the file")
#                     return None
#             else:
#                 logging.error("File is empty")
#                 return None
#     except Exception as e:
#         logging.error("Error reading file:", e)
#         return None
#
#
# # Prepare parameter values
# def prepare_parameter_values():
#     sensor_data = read_params_from_file("parameter_values.txt")
#     if sensor_data:
#         date_time = sensor_data["date_time"]
#         temp_c = int(sensor_data["temp_c"] * 10)  # Scale temperature by 10
#         humidity = int(sensor_data["humidity"] * 100)  # Scale humidity by 100
#         wind_speed = int(sensor_data["wind_speed"] * 100)  # Scale wind speed by 100
#         wind_dir = int(sensor_data["wind_dir"] * 10)  # Scale wind direction by 10
#         rainfall = int(sensor_data["rainfall"] * 100)  # Scale rainfall by 100
#         return [
#             date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute, date_time.second,
#             temp_c, humidity, wind_speed, wind_dir, rainfall
#         ]
#     else:
#         return None
#
#
# # Write sensor data to holding registers
# def write_sensor_data(context, data):
#     try:
#         for sensor_id, value in data.items():
#             address = int(sensor_id) - 1  # Adjusting for 0-based index
#             context[0].setValues(3, address, [value])
#             logging.info(f"Value {value} written to holding register at address {address}")
#             print(f"Value {value} written to holding register at address {address}")
#     except Exception as e:
#         logging.error(f"Error writing sensor data to holding registers: {e}")
#
#
# # Reset holding registers
# def reset_holding_registers(context, num_registers):
#     for i in range(num_registers):
#         context[0].setValues(3, i, [0])
#         logging.info(f"Value reset in holding register at address {i}")
#         print(f"Value reset in holding register at address {i}")
#         time.sleep(0.005)  # Wait for 5 milliseconds
#
#
# # Modbus RTU server configuration
# def configure_modbus_server():
#     store = ModbusSlaveContext(hr=ModbusSequentialDataBlock(0, [0] * 12))  # Holding Registers
#     context = ModbusServerContext(slaves=store, single=True)
#     return context
#
#
# # Main function
# if __name__ == "__main__":
#     parameter_file_path = "parameter_values.txt"
#     logging.info("Starting Modbus RTU Server...")
#     sensor_data = read_params_from_file(parameter_file_path)
#     if sensor_data:
#         logging.info("Sensor data loaded successfully")
#     else:
#         logging.error("Failed to load sensor data. Exiting...")
#         exit(1)
#
#     server_context = configure_modbus_server()
#
#     # Start Modbus RTU server
#     try:
#         logging.info("Modbus RTU Server started successfully")
#
#         while True:
#             # Write sensor data to holding registers
#             write_sensor_data(server_context, sensor_data)
#             logging.info("Sensor data written to holding registers")
#
#             time.sleep(60)  # Update sensor data every minute
#             print("Waiting for 60 seconds...")
#
#             # Update holding registers with parameter values
#             holding_register_values = prepare_parameter_values()
#             if holding_register_values:
#                 # server_context[0].setValues(3, 0, holding_register_values)
#                 logging.info("Updated holding registers with parameter values")
#                 print("Updated holding registers with parameter values")
#
#             # Reset holding registers after writing
#             reset_holding_registers(server_context, 12)
#             logging.info("Holding registers reset")
#             print("Holding registers reset")
#
#             time.sleep(60)  # Wait for 1 minute before resetting again
#             print("Waiting for 60 seconds...")
#
#     except KeyboardInterrupt:
#         logging.info("Server Stopped by user")
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")


#
# import logging
# from pymodbus.server.sync import StartSerialServer
# from pymodbus.datastore import ModbusSequentialDataBlock
# from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
# from pymodbus.device import ModbusDeviceIdentification
# from twisted.internet.task import LoopingCall
# from random import randint
#
# UNIT_ID = 1
#
# def update_values(context):
#     # Generate 12 random numbers
#     values = [randint(0, 65535) for _ in range(12)]
#     # Update the holding register block
#     context[0].setValues(3, 0, values)
#     logging.info("Values generated: %s", values)
#     logging.info("Values written to holding register: %s", values)
#
# # Initialize Modbus context
# store = ModbusSlaveContext(
#     di=ModbusSequentialDataBlock(0, [0]*100),
#     co=ModbusSequentialDataBlock(0, [0]*100),
#     hr=ModbusSequentialDataBlock(0, [0]*100),
#     ir=ModbusSequentialDataBlock(0, [0]*100)
# )
# context = ModbusServerContext(slaves=store, single=True)
#
# # Set up Modbus server identification
# identity = ModbusDeviceIdentification()
# identity.VendorName = 'Pymodbus'
# identity.ProductCode = 'PM'
# identity.VendorUrl = 'http://github.com/riptideio/pymodbus/'
# identity.ProductName = 'Pymodbus Server'
# identity.ModelName = 'Pymodbus Server'
# identity.MajorMinorRevision = '1.0'
#
# # Configure logging
# logging.basicConfig(filename='modbus_RTU_server2.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#
# try:
#     logging.info("Server starting...")
#     print("Server starting...")
#
#     # Start the server
#     server = StartSerialServer(context, framer=None, identity=identity, port='COM5', baudrate=19200, timeout=1)
#
#     logging.info("Server started")
#     print("Server started")
#
#     # Modbus RTU server configuration
#     def configure_modbus_server():
#         store = ModbusSlaveContext(unit_id=UNIT_ID)
#         context = ModbusServerContext(slaves=store, single=True)
#         return context
#
#     # Schedule the update of values every minute
#     loop = LoopingCall(update_values, context)
#     loop.start(60)
#
#     # Run the server
#     server.serve_forever()
#
# except Exception as e:
#     logging.error(f"An error occurred: {e}")
#     print(f"An error occurred: {e}")
