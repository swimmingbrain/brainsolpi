// brainsol bridge firmware for the keyestudio uno (atmega328p, 16 mhz)
//
// the raspberry pi runs the control loop, this board only reads the sensors,
// drives the two servos and talks a small line protocol over the usb serial port.
// the protocol and the pin map are described in firmware/README.md

#define FW_VERSION "1.0.0"

// serial link, same settings on the pi side
const unsigned long BAUD = 115200;

// caps bits in the identity line
const uint8_t CAP_BH1750 = 1;
const uint8_t CAP_INA219 = 2;

uint8_t caps() {
  // no sensors yet
  return 0;
}

// the pi waits for this line after it opens the port, so it must be the first thing we send
void send_identity() {
  Serial.print(F("I,brainsol," FW_VERSION ","));
  Serial.print(caps());
  Serial.print('\n');
}

void setup() {
  Serial.begin(BAUD);
  send_identity();
}

void loop() {
}
