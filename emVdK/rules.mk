CONSOLE_ENABLE = no
COMMAND_ENABLE = no
ORYX_ENABLE = yes
RGB_MATRIX_CUSTOM_KB = yes
TAP_DANCE_ENABLE = yes
SPACE_CADET_ENABLE = no
COMBO_ENABLE = yes
LAYER_LOCK_ENABLE = yes

# The STM32F303 runs out of USB endpoint numbers with OpenRGB + the dedicated
# Oryx HID interface + Navigator Trackpad digitizer. Share mouse reports with
# QMK's existing shared HID endpoint to reclaim one endpoint. This preserves
# mouse keys/trackball functionality at the cost of Boot Mouse compatibility.
MOUSE_SHARED_EP = yes
