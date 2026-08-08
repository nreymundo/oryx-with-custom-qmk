#define USB_SUSPEND_WAKEUP_DELAY 0
#define SERIAL_NUMBER "emVdK/DzYvbK"
#define LAYER_STATE_8BIT
#define COMBO_COUNT 2

#define NAVIGATOR_SCROLL_DIVIDER 50

#define AUTOMOUSE_LAYER 3
#define AUTOMOUSE_TIMEOUT 620
#define AUTOMOUSE_THRESHOLD 10
#define AUTOMOUSE_SCROLL_THRESHOLD AUTOMOUSE_THRESHOLD / NAVIGATOR_SCROLL_DIVIDER

// Existing Navigator Trackball is mounted on the right.
#define NAVIGATOR_TRACKBALL_ROTATION 325

// Test Navigator Trackpad is intended for the left side. The driver has no
// left/right selector; side is physical on the shared I2C bus. Start with the
// module default orientation explicitly documented here and adjust after a
// real Trackpad is available if necessary.
#define NAVIGATOR_TRACKPAD_ROTATION 0

#define RGB_MATRIX_STARTUP_SPD 60

