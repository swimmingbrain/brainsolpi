"""every dimension of the brainSOL body in one place

units are millimetres, angles are degrees
device frame: x to the right, y forward, z up, seen from behind, the table is z = 0
values marked measure are checked with the fit test, the readme says how
after changing a value run `uv run build.py` again, every part and check follows
"""

# print rules for the A1 mini with a 0.4 mm nozzle and matte PLA

BED = (178.0, 178.0, 178.0)  # usable box we allow per part, 1 mm from each edge of the 180 mm plate
NOZZLE = 0.4
LAYER = 0.2
WALL_MIN = 1.6  # four perimeters, anything thinner flexes and looks cheap
FIT_SLIDE = 0.25  # per side, parts that must slide or turn
FIT_SNUG = 0.15  # per side, parts that are pushed in and stay
OVERHANG_MAX = 45.0
BRIDGE_MAX = 25.0
# engravings on a face that lies on the plate, they print in the first layers
ENGRAVE_STROKE_MIN = 0.9  # every recessed stroke and join, two lines of the nozzle and some
ENGRAVE_ISLAND_MIN = 0.8  # every counter, gap or wall of plastic between recesses
ENGRAVE_SPAN_MAX = 3.0  # widest recess across, its floor is a bridge people see, a soft limit
ENGRAVE_SKIN_MIN = 2.0  # solid plastic behind the floor of the recess
ENGRAVE_CLEAR_MIN = 3.0  # recess to the edge of the flat face, a hole or another recess

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

# sg90 class servo, both servos are the same, the keyestudio micro servo of the kit
# measure with calipers, the model is the case, the tabs, the two round bosses on the top cover,
# the spline, the screw heads on the bottom and the lead

SERVO_L = 22.9  # case length, the direction of the mounting tabs
SERVO_W = 12.2  # case width
SERVO_H = 22.7  # case bottom to the top cover
SERVO_SHAFT_FROM_END = 5.9  # spline axis to the near short end of the case
SERVO_TAB_LEN = 4.7  # each mounting tab beyond the case end
SERVO_TAB_T = 2.5
SERVO_TAB_Z = 15.6  # underside of the tabs above the case bottom
SERVO_BOSS_R = 5.9  # round gear boss on the top cover around the spline
SERVO_BOSS_TOP = 26.4  # face of the gear boss above the case bottom
SERVO_BOSS2_R = 2.6  # small round boss beside the gear boss, read from a photo
SERVO_BOSS2_X = 7.4  # its centre from the spline axis toward the far end, its far edge is about 10 out
SERVO_BOSS2_TOP = 26.4  # its face above the case bottom, taken as high as the gear boss
SERVO_SPLINE_D = 4.8
SERVO_SPLINE_LEN = 3.2  # how far the spline sticks out of the boss face
SERVO_SCREW_PROUD = 0.5  # the four case screws stand this far out of the case bottom
SERVO_LEAD_Z = 1.0  # the flat lead leaves the near short end, the spline side, this high above the case bottom
SERVO_LEAD_Y = 3.6  # middle of the lead off the middle of the case, toward one long side, either side fits
SERVO_LEAD_W = 4.0
SERVO_LEAD_T = 1.4
# the pockets in the neck, the tabs set the servo along its shaft, the case gets air and crush ribs
SERVO_PLAY = 0.5  # more air on every side of the case, one up to 1 mm longer and wider than above still goes in
SERVO_BOSS_AIR = 0.5  # air around both bosses in every opening they pass
SERVO_RIB_BITE = 0.1  # how far each crush rib reaches into a case of the size above

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
BH_CHIP_SIDE = 2.5  # measure, chip centre off the board centre line, toward minus v as the module lies in the head
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

PANEL_W = 137.0  # the delivered panel, its label says 137 x 85
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
MARK_DEPTH = 0.4  # the small sun mark near the front edge of the lid

# signature engraved into the lid top behind the sun mark, read upright by a person in front
# the sizes are the smallest that pass the engraving limits above, checks.py measures them

SIG_ON = True  # False gives a plain lid
SIG_URL = "swimmingbrain.dev"  # the name line
SIG_TAG = "FTM-NES-BB-26"  # the class tag
SIG_URL_FONT = "inter_semibold.ttf"
SIG_TAG_FONT = "jetbrains_mono_extrabold.ttf"
# the official fhv logo from https://commons.wikimedia.org/wiki/File:FHV-Fachhochschule_Vorarlberg_logo_(2021%E2%80%93).svg
SIG_LOGO_FILE = "fhv_logo.svg"
SIG_X_HEIGHT = 7.3  # lowercase x height of the name line, Inter needs this for the joins of m and the openings of s and g
SIG_URL_TRACK = 0.0  # extra space between letters of the name line
SIG_TAG_CAP = 6.6  # cap height of the class tag, the fhv mark is a third taller
SIG_TAG_TRACK = 0.6  # keeps the gaps between the mono letters above the island limit
SIG_ROW_GAP = 4.4  # tail of the g to the top of the mark row
SIG_RULE_W = 1.0  # the thin rule between the fhv mark and the class tag
SIG_RULE_GAP = 4.4  # space on each side of the rule
SIG_DEPTH = 0.6  # three layers
SIG_SAMPLE = ("swim", "FTM-NES")  # the tightest signs of both rows, engraved under the fit test
SIG_X = 0.0  # on the centre line of the lid, like the sun mark and the neck
SIG_Y = 48.0  # front edge of the signature, the sun mark ring starts at 57

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

NECK_W = 44.0  # the ears run outside the side walls, the tilt servo fits between them
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
PIVOT_BOSS_R = 4.0
PIVOT_BOSS_X0 = 15.5  # inner end of the pivot boss, the cable column passes beside it

# hinge ears and caps

EAR_GAP = 0.5  # ear plate to neck side wall
EAR_T = 6.5
EAR_HUB_R = 10.25
EAR_HUB_H = 5.5  # with the hub the pivot screw gets 8.5 mm of thread in the ear
EAR_W = 26.0  # ear width where it meets the head
EAR_SCREW_DEPTH = 8.0  # tap holes in the end of the ear plate
EAR_RIB_W = 8.0  # the rib under the hub where it meets the end face, the ears print standing on that face
EAR_RIB_H = 2.5  # rib above the outer face of the plate at the end face
EAR_FOOT_C = 0.4  # chamfer round the end face and the tap hole mouths against elephant foot
HORN_SEAT_DEPTH = 1.9  # servo side of the tilt horn arm below the inner face of the left ear, it places the tilt servo
HORN_POCKET_DEPTH = 3.72  # inner face of the left ear to the pocket floor, 0.22 past the horn arm
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
BH_WINDOW_D = 3.6  # width of the slot in front of the bh1750 chip
BH_WINDOW_SIDE = (2.0, 3.0)  # the slot lets the chip look out anywhere this far below the board centre line
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
