#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import time

from ch341_transceiver import CH341I2cTransceiver
from sensirion_driver_adapters.i2c_adapter.i2c_channel import I2cChannel
from sensirion_i2c_driver import CrcCalculator, I2cConnection
from sensirion_i2c_stcc4.device import Stcc4Device


parser = argparse.ArgumentParser(
    description="Read Sensirion STCC4 through a CH341 USB-I2C adapter."
)
parser.add_argument("--device", type=int, default=0, help="CH341 device index. Default: 0")
parser.add_argument("--dll", default=None, help="Optional path to CH341DLL.DLL")
parser.add_argument(
    "--speed",
    choices=sorted(CH341I2cTransceiver.SPEED_MODES.keys()),
    default="100k",
    help="I2C bus speed. Default: 100k",
)
parser.add_argument(
    "--address",
    type=lambda value: int(value, 0),
    default=0x64,
    help="7-bit STCC4 I2C address. Default: 0x64",
)
parser.add_argument("--count", type=int, default=50, help="Number of samples. Default: 50")
args = parser.parse_args()


with CH341I2cTransceiver(
    device_index=args.device,
    dll_path=args.dll,
    speed=args.speed,
) as i2c_transceiver:
    channel = I2cChannel(
        I2cConnection(i2c_transceiver),
        slave_address=args.address,
        crc=CrcCalculator(8, 0x31, 0xFF, 0x00),
    )
    sensor = Stcc4Device(channel)

    sensor.stop_continuous_measurement()
    product_id, serial_number = sensor.get_product_id()
    print(f"product_id: {product_id}; serial_number: {serial_number};")

    test_result = sensor.check_self_test()
    print(f"test_result: {test_result};")

    sensor.start_continuous_measurement()
    try:
        for _ in range(args.count):
            try:
                time.sleep(1.0)
                co2_concentration, temperature, relative_humidity, sensor_status = (
                    sensor.read_measurement()
                )
            except BaseException:
                time.sleep(0.15)
                co2_concentration, temperature, relative_humidity, sensor_status = (
                    sensor.read_measurement()
                )

            print(
                f"co2_concentration: {co2_concentration}; "
                f"temperature: {temperature}; "
                f"relative_humidity: {relative_humidity}; "
                f"sensor_status: {sensor_status};"
            )
    finally:
        sensor.stop_continuous_measurement()
