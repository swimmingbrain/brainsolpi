"""every dimension of the brainSOL body in one place

units are millimetres, angles are degrees
device frame: x to the right, y forward, z up, seen from behind, the table is z = 0
values marked measure are assumptions until the kit arrives, MEASURE.md lists them
after changing a value run `uv run build.py` again, every part and check follows
"""

# print rules for the A1 mini with a 0.4 mm nozzle and matte PLA

BED = (175.0, 175.0, 175.0)  # usable box we allow per part, the plate is 180 mm
NOZZLE = 0.4
LAYER = 0.2
WALL_MIN = 1.6  # four perimeters, anything thinner flexes and looks cheap
FIT_SLIDE = 0.25  # per side, parts that must slide or turn
FIT_SNUG = 0.15  # per side, parts that are pushed in and stay
OVERHANG_MAX = 45.0
BRIDGE_MAX = 25.0

# fasteners, the kit screws are M3 flat head, the holes also seat a pan head

M3_TAP = 2.65  # self threading hole, 2.6 for tight PLA, 2.7 if the screw is hard to drive
M3_CLEAR = 3.4
M3_CSK_D = 6.4  # countersink top diameter for the 90 degree flat head
M3_HEAD_H = 1.65
M3X8 = 8.0
M3X14 = 14.0
TAP_DEPTH_MIN = 6.0

# the look, one radius family, one shadow gap, one edge chamfer

R_BIG = 20.0  # base corners
R_MID = 12.0  # head corners
R_SMALL = 6.0  # neck and foot corners
GAP = 0.8  # the shadow gap between lid and tray, and the width of every parting groove
EDGE = 0.8  # crisp chamfer on outer edges

# sg90 class servo, both servos are the same
# measure with calipers, the model is the case, the tabs, the round gear boss and the spline

SERVO_L = 22.9  # case length, the direction of the mounting tabs
SERVO_W = 12.2  # case width
SERVO_H = 22.7  # case bottom to the top cover
SERVO_SHAFT_FROM_END = 5.9  # spline axis to the near short end of the case
SERVO_TAB_LEN = 4.7  # each mounting tab beyond the case end
SERVO_TAB_T = 2.5
SERVO_TAB_Z = 15.6  # underside of the tabs above the case bottom
SERVO_BOSS_R = 5.9  # round gear boss on the top cover around the spline
SERVO_BOSS_TOP = 26.4  # face of the gear boss above the case bottom
SERVO_SPLINE_D = 4.8
SERVO_SPLINE_LEN = 3.2  # how far the spline sticks out of the boss face
SERVO_LEAD_Z = 4.5  # the lead leaves the far short end this high above the case bottom
SERVO_LEAD_W = 4.0
SERVO_LEAD_T = 1.4

# servo horns from the servo bag, both joints use the single arm horn
# measure: hub diameter, total height from arm underside to hub top, arm thickness and length

HORN_HUB_D = 7.0
HORN_TOTAL_H = 3.8  # arm underside to the end of the hub that faces the servo
HORN_ARM_T = 1.6
HORN_ARM_W0 = 6.0  # arm width next to the hub
HORN_ARM_W1 = 4.0  # arm width at the tip
HORN_SINGLE_LEN = 15.5  # hub centre to the tip of the single arm horn
HORN_SCREW_HEAD_D = 4.0
HORN_SCREW_HEAD_H = 1.4
HORN_HUB_PLAY = 0.3  # gap between the hub end and the servo boss face

# keyestudio photoresistor module, the bh1750 module has the same board and holes
# measure: board size, hole position, photoresistor position and height, bh1750 chip position

MOD_L = 32.0
MOD_W = 24.0
MOD_T = 1.6
MOD_HOLE_D = 4.9
MOD_HOLE_FROM_SENSOR_END = 20.0  # photos and the lego grid say 20, an earlier estimate was about 21
MOD_HOLE_SPACING = 16.0
LDR_FROM_END = 6.3  # centre of the photoresistor from the sensor end
LDR_D = 5.0
LDR_TOP = 2.5  # top face of the photoresistor above the board top
MOD_PARTS_H = 4.0  # tallest thing above the board, the header with a plug on it
MOD_UNDER = 1.6  # solder joints under the board
BH_CHIP_FROM_END = 12.8  # bh1750 sensor window from the module end without header
BH_CHIP_TOP = 1.0

# dupont plugs and cables

PITCH = 2.54
DUPONT_LEN = 14.0  # housing length of one female plug
DUPONT_W = 2.54
PLUG_REACH = 14.5  # from the module board edge to where the wire leaves a plug on the right angle header
HEADER_BASE_H = 2.5  # plastic base of a straight male header
PHOTO_CABLE = 200.0  # measure, the 3 pin F to F cables, tip to tip
BH_CABLE = 350.0  # the 4 pin cable used for the bh1750
SERVO_LEAD = 250.0
CABLE_LEN_INCLUDES_PLUGS = True  # the safe reading, 200 tip to tip leaves 172 of wire between the plugs
CABLE_SLACK_MIN = 8.0  # we want at least this much spare wire on the worst pose

# solar panel, measure: width, height, thickness and where the lead leaves the back

PANEL_W = 125.0
PANEL_H = 85.0
PANEL_T = 2.5
PANEL_FIT = 0.3  # per side in the bezel pocket

# raspberry pi 3b+, values from the official mechanical drawing
# local frame of the drawing: X along the 85 side from the sd card end, Y from the power edge

PI_L = 85.0
PI_W = 56.0
PI_T = 1.4
PI_HOLES = ((3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5))
PI_HOLE_D = 2.75
PI_PORT_OVERHANG = 2.0  # usb and ethernet jacks stick out of the board edge
PI_USB_Y = (29.0, 47.0)  # centres of the two usb pairs
PI_USB_W = 13.5
PI_USB_H = 16.0
PI_ETH_Y = 10.25
PI_ETH_W = 16.0
PI_ETH_H = 13.5
PI_PWR_X = 10.6  # micro usb power, on the power edge
PI_UNDER = 2.0
PI_SD_OVERHANG = 2.5
PI_GPIO_H = 8.5
PI_PIN_D = 2.45  # printed pin through the 2.75 mounting hole
PI_STANDOFF = 4.0

# keyestudio uno, standard uno outline and holes
# local frame: u along the 68.6 side from the usb end, w from the analog edge

UNO_L = 68.6
UNO_W = 53.4
UNO_T = 1.6
UNO_HOLES = ((13.97, 2.54), (15.24, 50.8), (66.04, 7.62), (66.04, 35.56))
UNO_USED_HOLES = (0, 1, 3)  # the hole next to the turret slot is left free
UNO_HOLE_D = 3.2
UNO_USB_W = (34.0, 46.0)  # measure, usb b socket span along w
UNO_USB_H = 11.0
UNO_USB_OVERHANG = 6.3
UNO_DC_W = (3.3, 12.3)
UNO_DC_H = 11.0
UNO_DC_OVERHANG = 1.8
UNO_A0_U = 47.5  # measure, A0 column of the G V S block from the usb end
UNO_GVS_W = (12.1, 9.6, 7.0)  # rows G, V, S from the analog edge
UNO_D9_U = 29.8  # measure, D9 column of the digital G V S block from the usb end
UNO_D10_U = 26.3
UNO_DGVS_W = (41.3, 43.8, 46.4)  # rows G, V, S of the digital block from the analog edge
UNO_I2C_U = 64.5  # measure, the GND VCC SDA SCL header near the far end
UNO_I2C_W = (6.0, 8.5, 11.0, 13.5)
UNO_PIN_H = 8.5  # male header pin tip above the board
UNO_UNDER = 2.0

# usb plugs and cables, measure the plugs of the kit cable

USB_A_PLUG = (16.0, 8.0, 40.0)  # width, height, length with strain relief
USB_B_PLUG = (12.5, 11.0, 40.0)
MICRO_USB_PLUG = (11.0, 7.5, 24.0)
PLUG_STRAIGHT = 48.0  # straight room we keep in front of each usb plug

# base

BASE_W = 156.0
BASE_D = 156.0
BASE_TOP = 48.0  # lid top above the table
FOOT_PAD_H = 3.0  # the feet lift the tray so air reaches the floor vents
FOOT_PAD_D = 14.0
WALL = 2.4
FLOOR = 2.4
LID_T = 3.0
LID_SKIRT_H = 5.0
LID_SKIRT_T = 1.6
COLUMN_D = 8.0  # lid columns that stand on the floor and take the foot screws
COLUMN_INSET = 12.0  # column centre from the outer wall
VENT_W = 2.4
VENT_PITCH = 5.2
MARK_DEPTH = 0.4

# layout inside the base, see the inside render

TURRET_X = 0.0
TURRET_Y = -32.0  # turret axis behind the centre so the head clears the base front edge
PI_X0 = -18.0  # power edge of the pi, the board lies to the left of it
PI_Y0 = -61.0  # sd card end of the pi, the usb ports face forward
UNO_ABLOCK_DX = 0.0  # the A0 to A3 plugs sit right under the pan axis, so panning only twists their wires
UNO_PLUG_TOP_GAP = 6.0  # room above the uno plugs for the wires to bend
UNO_POST_D = 7.0
PI_FINGER_D = 5.6

# neck and turret

NECK_W = 44.0  # room for the pan servo lead to bend up at the far end of the case
NECK_D = 30.0
NECK_WALL = 2.0
NECK_TOP_ABOVE_AXIS = 13.5
NECK_TOP_CHAMFER = 6.0
FOOT_W = 52.0
FOOT_H = 10.0
FOOT_FLARE_H = 4.0
FOOT_FLOOR_T = 2.4
PAN_BOSS_GAP = 0.4  # servo boss face above the lid top, the foot carries the weight
PAN_HORN_PLAY = 0.4  # vertical play of the pan horn under the lid
SLOT_R = 10.5  # radius of the cable slot in the lid around the pan axis
SLOT_W = 6.0
SLOT_HALF_ANGLE = 118.0
EXIT_W = 5.0  # cable exit in the foot floor
EXIT_L = 13.0
RING_R = 8.0  # ring boss on each side wall that the ear collars around
RING_H = 2.0
PIVOT_BOSS_R = 4.0
PIVOT_BOSS_X0 = 15.5  # inner end of the pivot boss, the cable column passes beside it

# hinge ears and caps

EAR_GAP = 0.5  # ear plate to neck side wall
EAR_T = 6.5
EAR_HUB_R = 10.25
EAR_HUB_H = 5.5  # the pivot screw gets a full 6 mm of thread in the hub
EAR_W = 26.0  # ear width where it meets the head
EAR_SCREW_DEPTH = 8.0  # tap holes in the end of the ear plate
COLLAR_PLAY = 0.8  # axial play of the ear collar over the ring boss
CAP_D = 12.0
CAP_T = 1.6

# head

BORDER_SIDE = 19.5  # wide enough for the bh1750 board next to the panel
BORDER_TB = 14.0
HEAD_CLEAR = 3.0  # head to lid at tilt 0 and tilt 180
HEAD_OFFSET = 22.0  # tilt axis to the back face of the head
EYE_FROM_PANEL = 5.0  # photoresistor centre beyond the panel edge
BEZEL_LIP = 2.0  # how far the bezel covers the panel edge
BEZEL_FRONT_T = 1.6
BACK_T = 2.0
HEAD_WALL_T = 2.0
MOD_STANDOFF = 2.0
PARTS_TO_PANEL = 0.5
HEAD_JOINT = 7.0  # parting plane of back shell and bezel, from the back face
SHADE_K = 1.2  # target shade wall height over sensor width, the k of simmodel.py
EYE_FLARE = 45.0
BH_WINDOW_D = 3.6
HEAD_CABLE_U = 0.0  # cable exit in the back of the head, centred between the side sensors

# ranges of the two axes

PAN_RANGE = (-90.0, 90.0)
TILT_RANGE = (0.0, 180.0)

# kit fasteners

KIT_FASTENERS = {
    "M3x8 flat head": 29,
    "M3x14 flat head": 4,
    "M3 nut": 6,
    "M4x8 round head": 2,
    "servo horn screw": 2,
}

# colour roles, the twin of the web app uses the same ones

COLORS = {
    "body": "#e4e2dd",
    "dark": "#2a2a2e",
    "accent": "#d19a66",
    "panel": "#141a2a",
    "background": "#111113",
}


# derived values, do not edit, they follow from the ones above

TRAY_Z0 = FOOT_PAD_H
FLOOR_TOP = TRAY_Z0 + FLOOR
LID_BOTTOM = BASE_TOP - LID_T
TRAY_TOP = LID_BOTTOM - GAP

HEAD_W = PANEL_W + 2 * BORDER_SIDE
HEAD_H = PANEL_H + 2 * BORDER_TB
PCB_BOTTOM_N = BACK_T + MOD_STANDOFF
PCB_TOP_N = PCB_BOTTOM_N + MOD_T
PANEL_BACK_N = PCB_TOP_N + MOD_PARTS_H + PARTS_TO_PANEL
PANEL_FRONT_N = PANEL_BACK_N + PANEL_T
HEAD_T = PANEL_FRONT_N + BEZEL_FRONT_T
LDR_FACE_N = PCB_TOP_N + LDR_TOP
SHADE_H = HEAD_T - LDR_FACE_N
SHADE_K_ACTUAL = SHADE_H / LDR_D

Z_TILT = BASE_TOP + HEAD_H / 2 + HEAD_CLEAR
NECK_TOP = Z_TILT + NECK_TOP_ABOVE_AXIS
HEAD_BACK_Y = TURRET_Y + HEAD_OFFSET  # at pan 0 and tilt 0
