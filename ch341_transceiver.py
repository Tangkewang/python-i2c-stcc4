import ctypes
import os
import platform
import subprocess
import time
from ctypes import wintypes
from pathlib import Path
from typing import Optional


class CH341I2cTransceiver:
    """Sensirion I2C transceiver wrapper for CH341DLL.DLL."""

    API_VERSION = 1

    STATUS_OK = 0
    STATUS_CHANNEL_DISABLED = 1
    STATUS_NACK = 2
    STATUS_TIMEOUT = 3
    STATUS_UNSPECIFIED_ERROR = 4

    SPEED_MODES = {
        "20k": 0x00,
        "100k": 0x01,
        "400k": 0x02,
        "750k": 0x03,
    }

    def __init__(
        self,
        device_index: int = 0,
        dll_path: Optional[str] = None,
        speed: str = "100k",
        use_x86_powershell: bool = True,
        do_open: bool = True,
    ) -> None:
        self.device_index = device_index
        self.dll_path = dll_path or "CH341DLL.DLL"
        self.speed = speed
        self.use_x86_powershell = use_x86_powershell
        self._x86_bridge = False
        self.dll = None
        self.handle = None
        if do_open:
            self.open()

    def __enter__(self):
        if self.handle is None:
            self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @property
    def description(self):
        return f"CH341 I2C device {self.device_index}"

    @property
    def channel_count(self):
        return None

    def open(self) -> None:
        try:
            self.dll = ctypes.WinDLL(self.dll_path)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 193:
                if self.use_x86_powershell:
                    self._check_x86_powershell()
                    self._x86_bridge = True
                    return
                raise OSError(
                    f"Cannot load {self.dll_path}: DLL bitness does not match "
                    f"Python ({platform.architecture()[0]}). Use 32-bit Python "
                    "for common 32-bit CH341DLL.DLL, or pass a matching DLL "
                    "with --dll."
                ) from exc
            raise

        self._bind_functions()
        self.handle = self.dll.CH341OpenDevice(self.device_index)
        if self.handle == -1:
            self.dll.CH341ResetDevice(self.device_index)
            self.handle = self.dll.CH341OpenDevice(self.device_index)
        if self.handle == -1:
            raise OSError(
                f"CH341OpenDevice({self.device_index}) failed. "
                "Check USB connection and CH341 driver."
            )

        mode = self.SPEED_MODES.get(self.speed, self.SPEED_MODES["100k"])
        if not self.dll.CH341SetStream(self.device_index, mode):
            raise OSError(f"CH341SetStream failed, mode=0x{mode:02X}.")

    def close(self) -> None:
        if self._x86_bridge:
            self.handle = None
            return
        if self.dll is not None and self.handle not in (None, 0):
            self.dll.CH341CloseDevice(self.device_index)
        self.handle = None

    def transceive(self, slave_address, tx_data, rx_length, read_delay, timeout):
        assert type(slave_address) is int
        assert (tx_data is None) or (type(tx_data) is bytes)
        assert (rx_length is None) or (type(rx_length) is int)
        assert type(read_delay) in [float, int]
        assert type(timeout) in [float, int]

        try:
            rx_data = b""

            if tx_data is not None:
                write_address = (slave_address << 1) & 0xFE
                self._stream_i2c(bytes([write_address]) + tx_data, 0)

            if read_delay > 0:
                time.sleep(read_delay)

            if rx_length is not None:
                read_address = ((slave_address << 1) & 0xFE) | 0x01
                rx_data = self._stream_i2c(bytes([read_address]), rx_length)

            return self.STATUS_OK, None, rx_data
        except Exception as exc:
            return self.STATUS_UNSPECIFIED_ERROR, exc, b""

    def _stream_i2c(self, write_bytes: bytes, read_length: int) -> bytes:
        if not write_bytes:
            raise ValueError("write_bytes must not be empty")
        if self._x86_bridge:
            return self._stream_i2c_x86_powershell(write_bytes, read_length)

        write_buffer = (ctypes.c_ubyte * len(write_bytes))(*write_bytes)
        read_buffer_size = max(1, read_length)
        read_buffer = (ctypes.c_ubyte * read_buffer_size)()

        ok = self.dll.CH341StreamI2C(
            self.device_index,
            len(write_bytes),
            write_buffer,
            read_length,
            read_buffer,
        )
        if not ok:
            raise OSError("CH341StreamI2C failed.")
        return bytes(read_buffer[:read_length])

    def _stream_i2c_x86_powershell(self, write_bytes: bytes, read_length: int) -> bytes:
        script = Path(__file__).with_name("ch341_i2c_transfer_x86.ps1")
        powershell_x86 = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "SysWOW64"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        mode = self.SPEED_MODES.get(self.speed, self.SPEED_MODES["100k"])
        write_hex = " ".join(f"{value:02X}" for value in write_bytes)
        result = subprocess.run(
            [
                str(powershell_x86),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-DeviceIndex",
                str(self.device_index),
                "-SpeedMode",
                str(mode),
                "-WriteHex",
                write_hex,
                "-ReadLength",
                str(read_length),
            ],
            capture_output=True,
            text=True,
            encoding="gbk",
            errors="replace",
            timeout=10,
        )
        output = (result.stdout or "").strip()
        if result.returncode != 0 or not output.startswith("OK"):
            error = output or (result.stderr or "").strip() or "CH341 x86 PowerShell bridge failed."
            raise OSError(error)
        if read_length <= 0:
            return b""
        return bytes.fromhex(output[2:].strip())

    def _check_x86_powershell(self) -> None:
        powershell_x86 = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "SysWOW64"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        if not powershell_x86.exists():
            raise OSError(f"32-bit PowerShell not found: {powershell_x86}")

    def _bind_functions(self) -> None:
        self.dll.CH341OpenDevice.argtypes = [wintypes.ULONG]
        self.dll.CH341OpenDevice.restype = ctypes.c_int

        self.dll.CH341ResetDevice.argtypes = [wintypes.ULONG]
        self.dll.CH341ResetDevice.restype = wintypes.BOOL

        self.dll.CH341CloseDevice.argtypes = [wintypes.ULONG]
        self.dll.CH341CloseDevice.restype = wintypes.BOOL

        self.dll.CH341SetStream.argtypes = [wintypes.ULONG, wintypes.ULONG]
        self.dll.CH341SetStream.restype = wintypes.BOOL

        self.dll.CH341StreamI2C.argtypes = [
            wintypes.ULONG,
            wintypes.ULONG,
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.c_void_p,
        ]
        self.dll.CH341StreamI2C.restype = wintypes.BOOL
