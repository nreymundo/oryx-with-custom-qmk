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


def patch_oryx_module(root: Path) -> None:
    """Move ZSA/Oryx off QMK's stock Raw HID transport.

    QMK-OpenRGB remains completely untouched and therefore continues to own
    QMK's normal Raw HID interface (USB interface 1) exactly as stock OpenRGB
    expects. Oryx gets its own 32-byte HID transport on interface 2.
    """
    module = root / "modules" / "zsa" / "oryx"
    if not module.is_dir():
        raise RuntimeError(f"ZSA Oryx module not found at {module}")

    # OpenRGB Rev D makes RAW_EPSIZE 64. Keymapp/Oryx still needs its original
    # 32-byte packets, so decouple every Oryx buffer from RAW_EPSIZE.
    epsize_hits = 0
    for path in module.rglob("*"):
        if path.is_file() and path.suffix in {".c", ".h", ".inc"}:
            text = path.read_text()
            count = text.count("RAW_EPSIZE")
            if count:
                epsize_hits += count
                path.write_text(text.replace("RAW_EPSIZE", "ORYX_EPSIZE"))

    if epsize_hits == 0:
        raise RuntimeError("Oryx module: RAW_EPSIZE not found")

    oryx_c = module / "oryx.c"
    text = oryx_c.read_text()

    old_endpoint = "#    define RAW_EP_NAME USB_ENDPOINT_IN_RAW"
    if text.count(old_endpoint) != 1:
        raise RuntimeError("Oryx module: ChibiOS Raw endpoint definition not found exactly once")
    text = text.replace(old_endpoint, "#    define RAW_EP_NAME USB_ENDPOINT_IN_ORYX", 1)

    old_receive = "void raw_hid_receive(uint8_t *data, uint8_t length) {"
    if text.count(old_receive) != 1:
        raise RuntimeError("Oryx module: raw_hid_receive definition not found exactly once")
    text = text.replace(old_receive, "void oryx_hid_receive(uint8_t *data, uint8_t length) {", 1)

    oryx_c.write_text(text)


def patch_descriptor_h(root: Path) -> None:
    path = root / "tmk_core" / "protocol" / "usb_descriptor.h"

    raw_struct = """#ifdef RAW_ENABLE
    // Raw HID Interface
    USB_Descriptor_Interface_t Raw_Interface;
    USB_HID_Descriptor_HID_t   Raw_HID;
    USB_Descriptor_Endpoint_t  Raw_INEndpoint;
    USB_Descriptor_Endpoint_t  Raw_OUTEndpoint;
#endif
"""
    replace_once(
        path,
        raw_struct,
        raw_struct + """
    // Dedicated ZSA/Oryx HID Interface
    USB_Descriptor_Interface_t Oryx_Interface;
    USB_HID_Descriptor_HID_t   Oryx_HID;
    USB_Descriptor_Endpoint_t  Oryx_INEndpoint;
    USB_Descriptor_Endpoint_t  Oryx_OUTEndpoint;
""",
        "Oryx descriptor struct",
    )

    raw_interface = """#ifdef RAW_ENABLE
    RAW_INTERFACE,
#endif
"""
    replace_once(
        path,
        raw_interface,
        raw_interface + """
    // QMK Raw HID remains interface 1 for stock OpenRGB. Oryx moves to 2.
    ORYX_INTERFACE,
""",
        "Oryx interface enum",
    )

    raw_endpoints = """#ifdef RAW_ENABLE
    RAW_IN_EPNUM = NEXT_EPNUM,
#    ifdef USB_ENDPOINTS_ARE_REORDERABLE
#        define RAW_OUT_EPNUM RAW_IN_EPNUM
#    else
    RAW_OUT_EPNUM         = NEXT_EPNUM,
#    endif
#endif
"""
    replace_once(
        path,
        raw_endpoints,
        raw_endpoints + """
    ORYX_IN_EPNUM = NEXT_EPNUM,
#ifdef USB_ENDPOINTS_ARE_REORDERABLE
#    define ORYX_OUT_EPNUM ORYX_IN_EPNUM
#else
    ORYX_OUT_EPNUM = NEXT_EPNUM,
#endif
""",
        "Oryx endpoint enum",
    )

    replace_once(
        path,
        "#define RAW_EPSIZE 32\n",
        "#define RAW_EPSIZE 32\n#ifndef ORYX_EPSIZE\n#    define ORYX_EPSIZE 32\n#endif\n",
        "Oryx endpoint size",
    )


def patch_descriptor_c(root: Path) -> None:
    path = root / "tmk_core" / "protocol" / "usb_descriptor.c"

    console_report = """#ifdef CONSOLE_ENABLE
const USB_Descriptor_HIDReport_Datatype_t PROGMEM ConsoleReport[] = {
"""
    oryx_report = """const USB_Descriptor_HIDReport_Datatype_t PROGMEM OryxReport[] = {
    HID_RI_USAGE_PAGE(16, 0xFF60), // QMK/ZSA vendor page
    HID_RI_USAGE(8, 0x61),         // QMK/ZSA Raw HID usage
    HID_RI_COLLECTION(8, 0x01),
        // Data to host
        HID_RI_USAGE(8, 0x62),
        HID_RI_LOGICAL_MINIMUM(8, 0x00),
        HID_RI_LOGICAL_MAXIMUM(16, 0x00FF),
        HID_RI_REPORT_COUNT(8, ORYX_EPSIZE),
        HID_RI_REPORT_SIZE(8, 0x08),
        HID_RI_INPUT(8, HID_IOF_DATA | HID_IOF_VARIABLE | HID_IOF_ABSOLUTE),

        // Data from host
        HID_RI_USAGE(8, 0x63),
        HID_RI_LOGICAL_MINIMUM(8, 0x00),
        HID_RI_LOGICAL_MAXIMUM(16, 0x00FF),
        HID_RI_REPORT_COUNT(8, ORYX_EPSIZE),
        HID_RI_REPORT_SIZE(8, 0x08),
        HID_RI_OUTPUT(8, HID_IOF_DATA | HID_IOF_VARIABLE | HID_IOF_ABSOLUTE | HID_IOF_NON_VOLATILE),
    HID_RI_END_COLLECTION(0),
};

"""
    replace_once(path, console_report, oryx_report + console_report, "Oryx report descriptor")

    mouse_marker = """#if defined(MOUSE_ENABLE) && !defined(MOUSE_SHARED_EP)
    /*
     * Mouse
     */
    .Mouse_Interface  = {
"""
    oryx_config = """    /*
     * Dedicated ZSA/Oryx HID
     */
    .Oryx_Interface = {
        .Header = {
            .Size               = sizeof(USB_Descriptor_Interface_t),
            .Type               = DTYPE_Interface
        },
        .InterfaceNumber        = ORYX_INTERFACE,
        .AlternateSetting       = 0x00,
        .TotalEndpoints         = 2,
        .Class                  = HID_CSCP_HIDClass,
        .SubClass               = HID_CSCP_NonBootSubclass,
        .Protocol               = HID_CSCP_NonBootProtocol,
        .InterfaceStrIndex      = NO_DESCRIPTOR
    },
    .Oryx_HID = {
        .Header = {
            .Size               = sizeof(USB_HID_Descriptor_HID_t),
            .Type               = HID_DTYPE_HID
        },
        .HIDSpec                = VERSION_BCD(1, 1, 1),
        .CountryCode            = 0x00,
        .TotalReportDescriptors = 1,
        .HIDReportType          = HID_DTYPE_Report,
        .HIDReportLength        = sizeof(OryxReport)
    },
    .Oryx_INEndpoint = {
        .Header = {
            .Size               = sizeof(USB_Descriptor_Endpoint_t),
            .Type               = DTYPE_Endpoint
        },
        .EndpointAddress        = (ENDPOINT_DIR_IN | ORYX_IN_EPNUM),
        .Attributes             = (EP_TYPE_INTERRUPT | ENDPOINT_ATTR_NO_SYNC | ENDPOINT_USAGE_DATA),
        .EndpointSize           = ORYX_EPSIZE,
        .PollingIntervalMS      = 0x01
    },
    .Oryx_OUTEndpoint = {
        .Header = {
            .Size               = sizeof(USB_Descriptor_Endpoint_t),
            .Type               = DTYPE_Endpoint
        },
        .EndpointAddress        = (ENDPOINT_DIR_OUT | ORYX_OUT_EPNUM),
        .Attributes             = (EP_TYPE_INTERRUPT | ENDPOINT_ATTR_NO_SYNC | ENDPOINT_USAGE_DATA),
        .EndpointSize           = ORYX_EPSIZE,
        .PollingIntervalMS      = 0x01
    },

"""
    replace_once(path, mouse_marker, oryx_config + mouse_marker, "Oryx configuration descriptor")

    hid_switch = """        case HID_DTYPE_HID:
            switch (wIndex) {
"""
    replace_once(
        path,
        hid_switch,
        hid_switch + """                case ORYX_INTERFACE:
                    Address = &ConfigurationDescriptor.Oryx_HID;
                    Size    = sizeof(USB_HID_Descriptor_HID_t);
                    break;

""",
        "Oryx HID descriptor lookup",
    )

    report_switch = """        case HID_DTYPE_Report:
            switch (wIndex) {
"""
    replace_once(
        path,
        report_switch,
        report_switch + """                case ORYX_INTERFACE:
                    Address = &OryxReport;
                    Size    = sizeof(OryxReport);
                    break;

""",
        "Oryx report descriptor lookup",
    )


def patch_endpoints_h(root: Path) -> None:
    path = root / "tmk_core" / "protocol" / "chibios" / "usb_endpoints.h"

    raw_caps = """#if !defined(RAW_OUT_CAPACITY)
#    define RAW_OUT_CAPACITY USB_DEFAULT_BUFFER_CAPACITY
#endif
"""
    replace_once(
        path,
        raw_caps,
        raw_caps + """
#if !defined(ORYX_IN_CAPACITY)
#    define ORYX_IN_CAPACITY USB_DEFAULT_BUFFER_CAPACITY
#endif
#if !defined(ORYX_OUT_CAPACITY)
#    define ORYX_OUT_CAPACITY USB_DEFAULT_BUFFER_CAPACITY
#endif
""",
        "Oryx endpoint capacities",
    )

    raw_in = """#if defined(RAW_ENABLE)
    USB_ENDPOINT_IN_RAW,
#endif
"""
    replace_once(path, raw_in, raw_in + "    USB_ENDPOINT_IN_ORYX,\n", "Oryx IN endpoint LUT")

    raw_out = """#if defined(RAW_ENABLE)
    USB_ENDPOINT_OUT_RAW,
#endif
"""
    replace_once(path, raw_out, raw_out + "    USB_ENDPOINT_OUT_ORYX,\n", "Oryx OUT endpoint LUT")


def patch_endpoints_c(root: Path) -> None:
    path = root / "tmk_core" / "protocol" / "chibios" / "usb_endpoints.c"

    midi_marker = """#if defined(MIDI_ENABLE)
#    if defined(USB_ENDPOINTS_ARE_REORDERABLE)
"""
    oryx_in = """#if defined(USB_ENDPOINTS_ARE_REORDERABLE)
    [USB_ENDPOINT_IN_ORYX] = QMK_USB_ENDPOINT_IN_SHARED(USB_EP_MODE_TYPE_INTR, ORYX_EPSIZE, ORYX_IN_EPNUM, ORYX_IN_CAPACITY, NULL, QMK_USB_REPORT_STORAGE_DEFAULT(ORYX_EPSIZE)),
#else
    [USB_ENDPOINT_IN_ORYX] = QMK_USB_ENDPOINT_IN(USB_EP_MODE_TYPE_INTR, ORYX_EPSIZE, ORYX_IN_EPNUM, ORYX_IN_CAPACITY, NULL, QMK_USB_REPORT_STORAGE_DEFAULT(ORYX_EPSIZE)),
#endif

"""
    replace_once(path, midi_marker, oryx_in + midi_marker, "Oryx IN endpoint")

    raw_lut = """#if defined(RAW_ENABLE)
    [RAW_INTERFACE] = USB_ENDPOINT_IN_RAW,
#endif
"""
    replace_once(
        path,
        raw_lut,
        raw_lut + "    [ORYX_INTERFACE] = USB_ENDPOINT_IN_ORYX,\n",
        "Oryx interface LUT",
    )

    raw_out = """#if defined(RAW_ENABLE)
    [USB_ENDPOINT_OUT_RAW] = QMK_USB_ENDPOINT_OUT(USB_EP_MODE_TYPE_INTR, RAW_EPSIZE, RAW_OUT_EPNUM, RAW_OUT_CAPACITY),
#endif
"""
    replace_once(
        path,
        raw_out,
        raw_out + "    [USB_ENDPOINT_OUT_ORYX] = QMK_USB_ENDPOINT_OUT(USB_EP_MODE_TYPE_INTR, ORYX_EPSIZE, ORYX_OUT_EPNUM, ORYX_OUT_CAPACITY),\n",
        "Oryx OUT endpoint",
    )


def patch_usb_main(root: Path) -> None:
    path = root / "tmk_core" / "protocol" / "chibios" / "usb_main.c"

    midi_marker = """#ifdef MIDI_ENABLE

void send_midi_packet(MIDI_EventPacket_t *event) {
"""
    oryx_io = """// Dedicated ZSA/Oryx HID interface. QMK's normal Raw HID path above is
// left untouched for the unmodified QMK-OpenRGB module.
void oryx_hid_receive(uint8_t *data, uint8_t length);

void oryx_hid_task(void) {
    uint8_t buffer[ORYX_EPSIZE];
    while (receive_report(USB_ENDPOINT_OUT_ORYX, buffer, sizeof(buffer))) {
        oryx_hid_receive(buffer, sizeof(buffer));
    }
}

"""
    replace_once(path, midi_marker, oryx_io + midi_marker, "Oryx HID task")


def patch_quantum_main(root: Path) -> None:
    path = root / "quantum" / "main.c"

    raw_task = """#ifdef RAW_ENABLE
        void raw_hid_task(void);
        raw_hid_task();
#endif
"""
    replace_once(
        path,
        raw_task,
        raw_task + """
        void oryx_hid_task(void);
        oryx_hid_task();
""",
        "Oryx task",
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <qmk_firmware>")

    root = Path(sys.argv[1]).resolve()
    if not (root / "tmk_core").is_dir():
        raise SystemExit(f"{root} does not look like a QMK firmware tree")

    patch_oryx_module(root)
    patch_descriptor_h(root)
    patch_descriptor_c(root)
    patch_endpoints_h(root)
    patch_endpoints_c(root)
    patch_usb_main(root)
    patch_quantum_main(root)

    # Guardrail: the OpenRGB module must remain untouched. This experiment is
    # specifically intended to work with an unmodified, normally-updatable
    # OpenRGB application and its stock QMK detector.
    openrgb_c = root / "modules" / "openrgb" / "openrgb.c"
    if "void raw_hid_receive(uint8_t *data, uint8_t length)" not in openrgb_c.read_text():
        raise RuntimeError("OpenRGB module no longer owns stock raw_hid_receive")

    print("Applied stock-OpenRGB dual-HID patch:")
    print("  interface 1: unmodified QMK-OpenRGB Raw HID, 64-byte reports")
    print("  interface 2: ZSA/Oryx/Keymapp HID, 32-byte reports")


if __name__ == "__main__":
    main()
