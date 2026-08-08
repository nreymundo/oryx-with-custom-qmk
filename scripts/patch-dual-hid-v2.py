#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


def patch_openrgb_module(root: Path) -> None:
    module = root / "modules" / "openrgb"
    if not module.is_dir():
        raise RuntimeError(f"OpenRGB module not found at {module}")

    hits = 0
    for path in module.rglob("*"):
        if path.is_file() and path.suffix in {".c", ".h", ".inc"}:
            text = path.read_text()
            count = text.count("RAW_EPSIZE")
            if count:
                hits += count
                path.write_text(text.replace("RAW_EPSIZE", "OPENRGB_EPSIZE"))
    if not hits:
        raise RuntimeError("OpenRGB module: RAW_EPSIZE not found")

    path = module / "openrgb.c"
    text = path.read_text()
    if not re.search(r"\braw_hid_receive\b", text):
        raise RuntimeError("OpenRGB module: raw_hid_receive not found")
    if not re.search(r"\braw_hid_send\b", text):
        raise RuntimeError("OpenRGB module: raw_hid_send not found")

    text = re.sub(r"\braw_hid_receive\b", "openrgb_raw_hid_receive", text)
    text = re.sub(r"\braw_hid_send\b", "openrgb_hid_send", text)

    marker = '#include "raw_hid.h"'
    if marker not in text:
        raise RuntimeError("OpenRGB module: raw_hid.h include not found")
    text = text.replace(
        marker,
        marker + '\n\nvoid openrgb_hid_send(uint8_t *data, uint8_t length);',
        1,
    )
    path.write_text(text)


def patch_descriptor_h(root: Path) -> None:
    path = root / "tmk_core/protocol/usb_descriptor.h"

    raw_struct = """#ifdef RAW_ENABLE
    // Raw HID Interface
    USB_Descriptor_Interface_t Raw_Interface;
    USB_HID_Descriptor_HID_t   Raw_HID;
    USB_Descriptor_Endpoint_t  Raw_INEndpoint;
    USB_Descriptor_Endpoint_t  Raw_OUTEndpoint;
#endif
"""
    replace_once(path, raw_struct, raw_struct + """
    // Dedicated OpenRGB HID Interface
    USB_Descriptor_Interface_t OpenRGB_Interface;
    USB_HID_Descriptor_HID_t   OpenRGB_HID;
    USB_Descriptor_Endpoint_t  OpenRGB_INEndpoint;
    USB_Descriptor_Endpoint_t  OpenRGB_OUTEndpoint;
""", "descriptor struct")

    raw_interface = """#ifdef RAW_ENABLE
    RAW_INTERFACE,
#endif
"""
    replace_once(path, raw_interface, raw_interface + """
    // Raw stays interface 1 for ZSA/Keymapp; OpenRGB becomes interface 2.
    OPENRGB_INTERFACE,
""", "interface enum")

    raw_eps = """#ifdef RAW_ENABLE
    RAW_IN_EPNUM = NEXT_EPNUM,
#    ifdef USB_ENDPOINTS_ARE_REORDERABLE
#        define RAW_OUT_EPNUM RAW_IN_EPNUM
#    else
    RAW_OUT_EPNUM         = NEXT_EPNUM,
#    endif
#endif
"""
    replace_once(path, raw_eps, raw_eps + """
    OPENRGB_IN_EPNUM = NEXT_EPNUM,
#ifdef USB_ENDPOINTS_ARE_REORDERABLE
#    define OPENRGB_OUT_EPNUM OPENRGB_IN_EPNUM
#else
    OPENRGB_OUT_EPNUM = NEXT_EPNUM,
#endif
""", "endpoint enum")

    replace_once(
        path,
        "#define RAW_EPSIZE 32\n",
        "#define RAW_EPSIZE 32\n#ifndef OPENRGB_EPSIZE\n#    define OPENRGB_EPSIZE 64\n#endif\n",
        "endpoint size",
    )


def patch_descriptor_c(root: Path) -> None:
    path = root / "tmk_core/protocol/usb_descriptor.c"

    console_report = """#ifdef CONSOLE_ENABLE
const USB_Descriptor_HIDReport_Datatype_t PROGMEM ConsoleReport[] = {
"""
    replace_once(path, console_report, """const USB_Descriptor_HIDReport_Datatype_t PROGMEM OpenRGBReport[] = {
    HID_RI_USAGE_PAGE(16, 0xFF60),
    HID_RI_USAGE(8, 0x61),
    HID_RI_COLLECTION(8, 0x01),
        HID_RI_USAGE(8, 0x62),
        HID_RI_LOGICAL_MINIMUM(8, 0x00),
        HID_RI_LOGICAL_MAXIMUM(16, 0x00FF),
        HID_RI_REPORT_COUNT(8, OPENRGB_EPSIZE),
        HID_RI_REPORT_SIZE(8, 0x08),
        HID_RI_INPUT(8, HID_IOF_DATA | HID_IOF_VARIABLE | HID_IOF_ABSOLUTE),
        HID_RI_USAGE(8, 0x63),
        HID_RI_LOGICAL_MINIMUM(8, 0x00),
        HID_RI_LOGICAL_MAXIMUM(16, 0x00FF),
        HID_RI_REPORT_COUNT(8, OPENRGB_EPSIZE),
        HID_RI_REPORT_SIZE(8, 0x08),
        HID_RI_OUTPUT(8, HID_IOF_DATA | HID_IOF_VARIABLE | HID_IOF_ABSOLUTE | HID_IOF_NON_VOLATILE),
    HID_RI_END_COLLECTION(0),
};

""" + console_report, "OpenRGB report")

    mouse_marker = """#if defined(MOUSE_ENABLE) && !defined(MOUSE_SHARED_EP)
    /*
     * Mouse
     */
    .Mouse_Interface  = {
"""
    openrgb_cfg = """    /* Dedicated OpenRGB HID */
    .OpenRGB_Interface = {
        .Header = {.Size = sizeof(USB_Descriptor_Interface_t), .Type = DTYPE_Interface},
        .InterfaceNumber = OPENRGB_INTERFACE,
        .AlternateSetting = 0x00,
        .TotalEndpoints = 2,
        .Class = HID_CSCP_HIDClass,
        .SubClass = HID_CSCP_NonBootSubclass,
        .Protocol = HID_CSCP_NonBootProtocol,
        .InterfaceStrIndex = NO_DESCRIPTOR
    },
    .OpenRGB_HID = {
        .Header = {.Size = sizeof(USB_HID_Descriptor_HID_t), .Type = HID_DTYPE_HID},
        .HIDSpec = VERSION_BCD(1, 1, 1),
        .CountryCode = 0x00,
        .TotalReportDescriptors = 1,
        .HIDReportType = HID_DTYPE_Report,
        .HIDReportLength = sizeof(OpenRGBReport)
    },
    .OpenRGB_INEndpoint = {
        .Header = {.Size = sizeof(USB_Descriptor_Endpoint_t), .Type = DTYPE_Endpoint},
        .EndpointAddress = (ENDPOINT_DIR_IN | OPENRGB_IN_EPNUM),
        .Attributes = (EP_TYPE_INTERRUPT | ENDPOINT_ATTR_NO_SYNC | ENDPOINT_USAGE_DATA),
        .EndpointSize = OPENRGB_EPSIZE,
        .PollingIntervalMS = 0x01
    },
    .OpenRGB_OUTEndpoint = {
        .Header = {.Size = sizeof(USB_Descriptor_Endpoint_t), .Type = DTYPE_Endpoint},
        .EndpointAddress = (ENDPOINT_DIR_OUT | OPENRGB_OUT_EPNUM),
        .Attributes = (EP_TYPE_INTERRUPT | ENDPOINT_ATTR_NO_SYNC | ENDPOINT_USAGE_DATA),
        .EndpointSize = OPENRGB_EPSIZE,
        .PollingIntervalMS = 0x01
    },

"""
    replace_once(path, mouse_marker, openrgb_cfg + mouse_marker, "OpenRGB configuration")

    hid_switch = """        case HID_DTYPE_HID:
            switch (wIndex) {
"""
    replace_once(path, hid_switch, hid_switch + """                case OPENRGB_INTERFACE:
                    Address = &ConfigurationDescriptor.OpenRGB_HID;
                    Size    = sizeof(USB_HID_Descriptor_HID_t);
                    break;

""", "HID descriptor lookup")

    report_switch = """        case HID_DTYPE_Report:
            switch (wIndex) {
"""
    replace_once(path, report_switch, report_switch + """                case OPENRGB_INTERFACE:
                    Address = &OpenRGBReport;
                    Size    = sizeof(OpenRGBReport);
                    break;

""", "report descriptor lookup")


def patch_endpoints_h(root: Path) -> None:
    path = root / "tmk_core/protocol/chibios/usb_endpoints.h"

    raw_caps = """#if !defined(RAW_OUT_CAPACITY)
#    define RAW_OUT_CAPACITY USB_DEFAULT_BUFFER_CAPACITY
#endif
"""
    replace_once(path, raw_caps, raw_caps + """
#if !defined(OPENRGB_IN_CAPACITY)
#    define OPENRGB_IN_CAPACITY USB_DEFAULT_BUFFER_CAPACITY
#endif
#if !defined(OPENRGB_OUT_CAPACITY)
#    define OPENRGB_OUT_CAPACITY USB_DEFAULT_BUFFER_CAPACITY
#endif
""", "OpenRGB capacities")

    raw_in = """#if defined(RAW_ENABLE)
    USB_ENDPOINT_IN_RAW,
#endif
"""
    replace_once(path, raw_in, raw_in + "    USB_ENDPOINT_IN_OPENRGB,\n", "OpenRGB IN LUT")

    raw_out = """#if defined(RAW_ENABLE)
    USB_ENDPOINT_OUT_RAW,
#endif
"""
    replace_once(path, raw_out, raw_out + "    USB_ENDPOINT_OUT_OPENRGB,\n", "OpenRGB OUT LUT")


def patch_endpoints_c(root: Path) -> None:
    path = root / "tmk_core/protocol/chibios/usb_endpoints.c"

    midi_marker = """#if defined(MIDI_ENABLE)
#    if defined(USB_ENDPOINTS_ARE_REORDERABLE)
"""
    openrgb_in = """#if defined(USB_ENDPOINTS_ARE_REORDERABLE)
    [USB_ENDPOINT_IN_OPENRGB] = QMK_USB_ENDPOINT_IN_SHARED(USB_EP_MODE_TYPE_INTR, OPENRGB_EPSIZE, OPENRGB_IN_EPNUM, OPENRGB_IN_CAPACITY, NULL, QMK_USB_REPORT_STORAGE_DEFAULT(OPENRGB_EPSIZE)),
#else
    [USB_ENDPOINT_IN_OPENRGB] = QMK_USB_ENDPOINT_IN(USB_EP_MODE_TYPE_INTR, OPENRGB_EPSIZE, OPENRGB_IN_EPNUM, OPENRGB_IN_CAPACITY, NULL, QMK_USB_REPORT_STORAGE_DEFAULT(OPENRGB_EPSIZE)),
#endif

"""
    replace_once(path, midi_marker, openrgb_in + midi_marker, "OpenRGB IN endpoint")

    raw_lut = """#if defined(RAW_ENABLE)
    [RAW_INTERFACE] = USB_ENDPOINT_IN_RAW,
#endif
"""
    replace_once(path, raw_lut, raw_lut + "    [OPENRGB_INTERFACE] = USB_ENDPOINT_IN_OPENRGB,\n", "OpenRGB interface LUT")

    raw_out = """#if defined(RAW_ENABLE)
    [USB_ENDPOINT_OUT_RAW] = QMK_USB_ENDPOINT_OUT(USB_EP_MODE_TYPE_INTR, RAW_EPSIZE, RAW_OUT_EPNUM, RAW_OUT_CAPACITY),
#endif
"""
    replace_once(path, raw_out, raw_out + "    [USB_ENDPOINT_OUT_OPENRGB] = QMK_USB_ENDPOINT_OUT(USB_EP_MODE_TYPE_INTR, OPENRGB_EPSIZE, OPENRGB_OUT_EPNUM, OPENRGB_OUT_CAPACITY),\n", "OpenRGB OUT endpoint")


def patch_usb_main(root: Path) -> None:
    path = root / "tmk_core/protocol/chibios/usb_main.c"
    midi_marker = """#ifdef MIDI_ENABLE

void send_midi_packet(MIDI_EventPacket_t *event) {
"""
    openrgb_io = """void openrgb_raw_hid_receive(uint8_t *data, uint8_t length);

void openrgb_hid_send(uint8_t *data, uint8_t length) {
    if (length != OPENRGB_EPSIZE) return;
    send_report(USB_ENDPOINT_IN_OPENRGB, data, length);
}

void openrgb_hid_task(void) {
    uint8_t buffer[OPENRGB_EPSIZE];
    while (receive_report(USB_ENDPOINT_OUT_OPENRGB, buffer, sizeof(buffer))) {
        openrgb_raw_hid_receive(buffer, sizeof(buffer));
    }
}

"""
    replace_once(path, midi_marker, openrgb_io + midi_marker, "OpenRGB I/O")


def patch_main(root: Path) -> None:
    path = root / "quantum/main.c"
    raw_task = """#ifdef RAW_ENABLE
        void raw_hid_task(void);
        raw_hid_task();
#endif
"""
    replace_once(path, raw_task, raw_task + """
        void openrgb_hid_task(void);
        openrgb_hid_task();
""", "OpenRGB task")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <qmk_firmware>")
    root = Path(sys.argv[1]).resolve()
    if not (root / "tmk_core").is_dir():
        raise SystemExit(f"{root} does not look like QMK")

    patch_openrgb_module(root)
    patch_descriptor_h(root)
    patch_descriptor_c(root)
    patch_endpoints_h(root)
    patch_endpoints_c(root)
    patch_usb_main(root)
    patch_main(root)

    print("Dual HID patch applied")
    print("  HID interface 1: ZSA/Oryx Raw HID, 32 bytes")
    print("  HID interface 2: QMK-OpenRGB, 64 bytes")


if __name__ == "__main__":
    main()
