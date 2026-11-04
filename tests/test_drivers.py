from mckpxe.drivers import extract_hwids, minimal_dirs, parse_inf

NET_INF = """; Intel network driver
[Version]
Signature   = "$WINDOWS NT$"
Class       = Net
Provider    = %Intel%
DriverVer   = 05/01/2025,12.19.2.45

[Manufacturer]
%Intel%     = Intel, NTamd64.10.0

[Intel.NTamd64.10.0]
%E15F3NC.DeviceDesc% = E15F3, PCI\\VEN_8086&DEV_15F3&SUBSYS_00008086
%Audio% = A, HDAUDIO\\FUNC_01&VEN_10EC&DEV_0257&SUBSYS_17AA2280
%Touch% = T, ACPI\\VEN_INT&DEV_33A1, ACPI\\PNP0C50
%Cam%   = C, USB\\VID_04F2&PID_B6D9&MI_00

[Strings]
Intel = "Intel Corporation"
"""


def test_parse_utf16_inf():
    info = parse_inf("﻿".encode("utf-16-le") + NET_INF.encode("utf-16-le"))
    assert info["class_name"] == "Net"
    assert info["provider"] == "Intel Corporation"
    assert info["version"] == "12.19.2.45"
    assert info["hardware_ids"] == [
        "ACPI\\INT33A1", "ACPI\\PNP0C50", "HDAUDIO\\VEN_10EC&DEV_0257",
        "PCI\\VEN_8086&DEV_15F3", "USB\\VID_04F2&PID_B6D9",
    ]


def test_x86_only_inf_is_skipped():
    inf = NET_INF.replace("NTamd64.10.0", "NTx86")
    assert parse_inf(inf.encode()) is None


def test_undecorated_inf_is_kept():
    inf = NET_INF.replace("Intel, NTamd64.10.0", "Intel").replace("[Intel.NTamd64.10.0]", "[Intel]")
    assert parse_inf(inf.encode())["class_name"] == "Net"


def test_hwid_normalisation_matches_agent_format():
    assert extract_hwids("pci\\ven_8086&dev_a0f0&subsys_1") == ["PCI\\VEN_8086&DEV_A0F0"]


def test_minimal_dirs():
    assert minimal_dirs(["a/b", "a", "c/d", "c/d/e"]) == ["a", "c/d"]
    assert minimal_dirs(["x", "."]) == ["."]
