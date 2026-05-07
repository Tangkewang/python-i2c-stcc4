param(
    [int]$DeviceIndex = 0,
    [int]$SpeedMode = 1,
    [string]$WriteHex,
    [int]$ReadLength = 0,
    [string]$DllPath = "CH341DLL.DLL"
)

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class CH341NativeTransfer
{
    [DllImport("CH341DLL.DLL")]
    public static extern int CH341OpenDevice(int iIndex);

    [DllImport("CH341DLL.DLL")]
    public static extern bool CH341ResetDevice(int iIndex);

    [DllImport("CH341DLL.DLL")]
    public static extern bool CH341CloseDevice(int iIndex);

    [DllImport("CH341DLL.DLL")]
    public static extern bool CH341SetStream(int iIndex, int iMode);

    [DllImport("CH341DLL.DLL")]
    public static extern bool CH341StreamI2C(
        int iIndex,
        int iWriteLength,
        byte[] iWriteBuffer,
        int iReadLength,
        byte[] oReadBuffer
    );
}
"@

function Convert-HexToBytes {
    param([string]$Hex)
    $clean = ($Hex -replace "0x", "" -replace "[^0-9a-fA-F]", "")
    if (($clean.Length % 2) -ne 0) {
        throw "WriteHex must contain an even number of hex digits."
    }
    $bytes = New-Object byte[] ($clean.Length / 2)
    for ($i = 0; $i -lt $bytes.Length; $i++) {
        $bytes[$i] = [Convert]::ToByte($clean.Substring($i * 2, 2), 16)
    }
    return $bytes
}

function Open-CH341Device {
    param(
        [int]$Index,
        [int]$Mode,
        [int]$RetryCount = 8,
        [int]$RetryDelayMs = 300
    )

    for ($i = 0; $i -lt $RetryCount; $i++) {
        $handle = [CH341NativeTransfer]::CH341OpenDevice($Index)
        if ($handle -ne -1) {
            if ([CH341NativeTransfer]::CH341SetStream($Index, $Mode)) {
                return $handle
            }
            [void][CH341NativeTransfer]::CH341CloseDevice($Index)
        }
        [void][CH341NativeTransfer]::CH341ResetDevice($Index)
        Start-Sleep -Milliseconds $RetryDelayMs
    }
    return -1
}

$handle = Open-CH341Device -Index $DeviceIndex -Mode $SpeedMode
if ($handle -eq -1) {
    Write-Output "ERROR CH341OpenDevice failed"
    exit 2
}

try {
    $writeBuffer = Convert-HexToBytes $WriteHex
    $readBufferSize = [Math]::Max(1, $ReadLength)
    $readBuffer = New-Object byte[] $readBufferSize
    $ok = [CH341NativeTransfer]::CH341StreamI2C(
        $DeviceIndex,
        $writeBuffer.Length,
        $writeBuffer,
        $ReadLength,
        $readBuffer
    )

    if (-not $ok) {
        Write-Output "ERROR CH341StreamI2C failed"
        exit 3
    }

    if ($ReadLength -gt 0) {
        $hex = ($readBuffer[0..($ReadLength - 1)] | ForEach-Object { $_.ToString("X2") }) -join " "
        Write-Output "OK $hex"
    }
    else {
        Write-Output "OK"
    }
}
finally {
    [void][CH341NativeTransfer]::CH341CloseDevice($DeviceIndex)
}
