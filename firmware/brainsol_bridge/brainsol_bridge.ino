// brainsol bridge firmware for the keyestudio uno (atmega328p, 16 mhz)
//
// the raspberry pi runs the control loop, this board only reads the sensors,
// drives the two servos and talks a small line protocol over the usb serial port.
// the protocol and the pin map are described in firmware/README.md

#include <Servo.h>
#include <Wire.h>

#define FW_VERSION "1.0.0"

// serial link, same settings on the pi side
const unsigned long BAUD = 115200;

// longest command line we accept, without the newline
const uint8_t LINE_MAX = 96;

// caps bits in the identity line
const uint8_t CAP_BH1750 = 1;
const uint8_t CAP_INA219 = 2;

// error codes in E lines
const uint8_t ERR_BAD_COMMAND = 1;
const uint8_t ERR_TOO_LONG = 2;

// ---------------------------------------------------------------------------
// replies

// a reply (I, P or E line) waits here until the transmit buffer has room for all of it,
// so the loop never sits in Serial.write waiting for bytes to drain
char reply_buf[32];
bool reply_pending = false;

void flush_reply() {
  if (!reply_pending) {
    return;
  }
  int len = strlen(reply_buf);
  if (Serial.availableForWrite() < len) {
    return;
  }
  Serial.write(reply_buf, len);
  reply_pending = false;
}

// only one reply can wait at a time, read_serial stops taking new lines while one waits
void queue_reply(const char *text) {
  strncpy(reply_buf, text, sizeof(reply_buf) - 2);
  reply_buf[sizeof(reply_buf) - 2] = '\0';
  strcat(reply_buf, "\n");
  reply_pending = true;
  flush_reply();
}

void send_error(uint8_t code, const char *text) {
  char buf[sizeof(reply_buf)];
  snprintf(buf, sizeof(buf), "E,%u,%s", (unsigned)code, text);
  queue_reply(buf);
}

// the pi waits for this line after it opens the port, so it is the first thing we send
void send_identity() {
  char buf[sizeof(reply_buf)];
  snprintf(buf, sizeof(buf), "I,brainsol,%s,%u", FW_VERSION, (unsigned)caps());
  queue_reply(buf);
}

// ---------------------------------------------------------------------------
// helpers

// out of range values from the pi are clamped, so the board never ends up in an odd state
long clamp_long(long value, long low, long high) {
  if (value < low) {
    return low;
  }
  if (value > high) {
    return high;
  }
  return value;
}

// true once per period. now minus last is computed in unsigned 32 bit, so the result
// stays right when micros() wraps around after about 71 minutes
bool tick_due(uint32_t &last, uint32_t period, uint32_t now) {
  if ((uint32_t)(now - last) < period) {
    return false;
  }
  last += period;
  // after a long stall start fresh instead of firing a burst of late ticks
  if ((uint32_t)(now - last) >= period) {
    last = now;
  }
  return true;
}

// ---------------------------------------------------------------------------
// light sensors

// adc channels 0 to 3 are the pins a0 to a3: left, right, up, down
const uint8_t LDR_COUNT = 4;
// readings summed per channel and set, 8 x 1023 = 8184 still fits into a uint16_t
const uint8_t ADC_READS = 8;

// the last complete set of sums, this is what the frames report
uint16_t ldr_sum[LDR_COUNT];

// the set being measured right now
uint16_t adc_work[LDR_COUNT];
uint8_t adc_channel = 0;
// conversions done on this channel so far, number 0 is the throwaway one
uint8_t adc_reads = 0;

// analogRead waits about 110 us for every conversion. here we start one and pick up
// the result on a later pass of loop, so the loop never waits for the adc
void adc_start(uint8_t channel) {
  // avcc as reference, the same as analogRead with the default reference
  ADMUX = _BV(REFS0) | (channel & 0x07);
  ADCSRA |= _BV(ADSC);
}

void adc_step() {
  if (bit_is_set(ADCSRA, ADSC)) {
    // still converting
    return;
  }
  // ADCL has to be read first, that keeps ADCH from changing until it is read too
  uint8_t low = ADCL;
  uint8_t high = ADCH;
  uint16_t value = ((uint16_t)high << 8) | low;

  // the first reading after a channel switch is thrown away, the sample and hold
  // capacitor still carries some charge from the previous channel
  if (adc_reads > 0) {
    adc_work[adc_channel] += value;
  }
  adc_reads++;
  if (adc_reads > ADC_READS) {
    adc_reads = 0;
    adc_channel++;
    if (adc_channel == LDR_COUNT) {
      // a full set is done, publish it and start the next one
      for (uint8_t i = 0; i < LDR_COUNT; i++) {
        ldr_sum[i] = adc_work[i];
        adc_work[i] = 0;
      }
      adc_channel = 0;
    }
  }
  adc_start(adc_channel);
}

// ---------------------------------------------------------------------------
// i2c sensors

// i2c transfers wait for the bus. without a timeout a stuck or half plugged sensor would
// hang the loop for good, 3 ms is about ten times a normal transfer at 100 khz
const uint32_t I2C_TIMEOUT_US = 3000;
// one sensor transfer per step keeps every loop pass short
const uint32_t SENSOR_STEP_MS = 50;
// failed reads in a row before a sensor counts as unplugged
const uint8_t SENSOR_FAILS_MAX = 3;

// the stock module has ADDR low and answers on 0x23, with ADDR high it is 0x5c
const uint8_t BH1750_ADDRS[2] = {0x23, 0x5C};
const uint8_t BH1750_POWER_ON = 0x01;
const uint8_t BH1750_CONT_HRES = 0x10;

// 0 while no bh1750 is found
uint8_t bh1750_addr = 0;
uint8_t bh1750_fails = 0;
// the last reading, lux times 10, 0 without a sensor as the protocol says
uint32_t lux10 = 0;

const uint8_t INA219_ADDR = 0x40;
const uint8_t INA219_REG_CONFIG = 0x00;
const uint8_t INA219_REG_SHUNT = 0x01;
const uint8_t INA219_REG_BUS = 0x02;
// 32 v range, shunt gain /8 for +-320 mv, 12 bit, shunt and bus measured all the time.
// that is the power on default, we write it anyway because the chip keeps an older
// setting for as long as it has power
const uint16_t INA219_CONFIG = 0x399F;

bool ina219_found = false;
uint8_t ina219_fails = 0;
// the last readings, 0 without a sensor as the protocol says
uint16_t panel_mv = 0;
long panel_ua = 0;

uint32_t last_sensor_ms = 0;
uint8_t sensor_turn = 0;

bool i2c_send_byte(uint8_t addr, uint8_t value) {
  Wire.beginTransmission(addr);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

// reads two bytes, high byte first. leftovers of a short read are thrown away
bool i2c_read_word(uint8_t addr, uint16_t *value) {
  if (Wire.requestFrom(addr, (uint8_t)2) != 2) {
    while (Wire.available() > 0) {
      Wire.read();
    }
    return false;
  }
  uint8_t high = Wire.read();
  uint8_t low = Wire.read();
  *value = ((uint16_t)high << 8) | low;
  return true;
}

void bh1750_probe() {
  for (uint8_t i = 0; i < 2; i++) {
    uint8_t addr = BH1750_ADDRS[i];
    // wake it up, then continuous high resolution mode: 1 lx steps, a new value every 120 ms
    if (i2c_send_byte(addr, BH1750_POWER_ON) && i2c_send_byte(addr, BH1750_CONT_HRES)) {
      bh1750_addr = addr;
      bh1750_fails = 0;
      return;
    }
  }
}

void bh1750_read() {
  uint16_t raw;
  if (i2c_read_word(bh1750_addr, &raw)) {
    // lux is raw / 1.2, so lux times 10 is raw * 25 / 3. done in 32 bit and rounded,
    // the largest raw value gives 546125 which needs more than 16 bit
    lux10 = ((uint32_t)raw * 25 + 1) / 3;
    bh1750_fails = 0;
    return;
  }
  bh1750_fails++;
  if (bh1750_fails >= SENSOR_FAILS_MAX) {
    bh1750_addr = 0;
    lux10 = 0;
  }
}

bool ina219_write(uint8_t reg, uint16_t value) {
  Wire.beginTransmission(INA219_ADDR);
  Wire.write(reg);
  Wire.write((uint8_t)(value >> 8));
  Wire.write((uint8_t)(value & 0xFF));
  return Wire.endTransmission() == 0;
}

bool ina219_read(uint8_t reg, uint16_t *value) {
  if (!i2c_send_byte(INA219_ADDR, reg)) {
    return false;
  }
  return i2c_read_word(INA219_ADDR, value);
}

void ina219_probe() {
  if (ina219_write(INA219_REG_CONFIG, INA219_CONFIG)) {
    ina219_found = true;
    ina219_fails = 0;
  }
}

void ina219_failed() {
  ina219_fails++;
  if (ina219_fails >= SENSOR_FAILS_MAX) {
    ina219_found = false;
    panel_mv = 0;
    panel_ua = 0;
  }
}

void ina219_read_bus() {
  uint16_t raw;
  if (!ina219_read(INA219_REG_BUS, &raw)) {
    ina219_failed();
    return;
  }
  // bits 15 to 3 hold the bus voltage in 4 mv steps, the low bits are status flags
  panel_mv = (raw >> 3) * 4;
  ina219_fails = 0;
}

void ina219_read_shunt() {
  uint16_t raw;
  if (!ina219_read(INA219_REG_SHUNT, &raw)) {
    ina219_failed();
    return;
  }
  // signed, 10 uv per step. with the usual 0.1 ohm shunt on the module that is
  // 100 ua per step, so +-32000 steps become at most +-3.2 a, a long holds that easily
  panel_ua = (long)(int16_t)raw * 100;
  ina219_fails = 0;
}

void sensors_step(uint32_t now_ms) {
  if ((uint32_t)(now_ms - last_sensor_ms) < SENSOR_STEP_MS) {
    return;
  }
  last_sensor_ms = now_ms;

  // one transfer per step, so every value is fresh every 150 ms.
  // the bh1750 makes a new value every 120 ms, that is plenty
  if (sensor_turn == 0 && bh1750_addr != 0) {
    bh1750_read();
  } else if (sensor_turn == 1 && ina219_found) {
    ina219_read_bus();
  } else if (sensor_turn == 2 && ina219_found) {
    ina219_read_shunt();
  }
  sensor_turn++;
  if (sensor_turn >= 3) {
    sensor_turn = 0;
  }
}

uint8_t caps() {
  uint8_t bits = 0;
  if (bh1750_addr != 0) {
    bits |= CAP_BH1750;
  }
  if (ina219_found) {
    bits |= CAP_INA219;
  }
  return bits;
}

// ---------------------------------------------------------------------------
// servos

const uint8_t PAN_PIN = 9;
const uint8_t TILT_PIN = 10;
const int PULSE_MIN = 500;
const int PULSE_MAX = 2500;
const uint32_t SLEW_TICK_US = 10000;
const int SLEW_DEFAULT = 30;
const int SLEW_MIN = 1;
const int SLEW_MAX = 200;
// longest wait for a running pulse to end before a detach, a bit more than 2500 us
const uint32_t DETACH_WAIT_US = 3000;
// time without an M command before flag 2 goes up
const uint32_t WATCHDOG_MS = 1500;

Servo pan_servo;
Servo tilt_servo;
bool servos_attached = false;

// the pulses going out now and the pulses we are heading for, in us
int pan_now = 0;
int tilt_now = 0;
int pan_target = 0;
int tilt_target = 0;

// largest pulse change per slew tick
int slew_cap = SLEW_DEFAULT;
uint32_t last_slew_us = 0;

// the board never moves on its own. when the pi goes quiet we keep the last target
// and only raise a flag, the pi decides what happens next
uint32_t last_move_ms = 0;
bool watchdog_expired = false;

// the flag is latched, so it cannot clear by itself when millis() wraps after 49 days
void watchdog_check(uint32_t now_ms) {
  if (!watchdog_expired && (uint32_t)(now_ms - last_move_ms) >= WATCHDOG_MS) {
    watchdog_expired = true;
  }
}

// both servos start right at the commanded pulse, nothing jumps to the default 1500 us.
// the library learns our 500 to 2500 range only inside attach(), a write before that is
// clamped to its own default of 544 to 2400. so we set the pulse before attach, attach,
// and write once more to get the exact value. interrupts stay off for these few
// microseconds, the servo timer cannot start a pulse with a half set value in between
void attach_at(int pan_us, int tilt_us) {
  noInterrupts();
  pan_servo.writeMicroseconds(pan_us);
  tilt_servo.writeMicroseconds(tilt_us);
  pan_servo.attach(PAN_PIN, PULSE_MIN, PULSE_MAX);
  tilt_servo.attach(TILT_PIN, PULSE_MIN, PULSE_MAX);
  pan_servo.writeMicroseconds(pan_us);
  tilt_servo.writeMicroseconds(tilt_us);
  interrupts();

  pan_now = pan_us;
  tilt_now = tilt_us;
  servos_attached = true;
}

void command_move(long pan_us, long tilt_us) {
  pan_target = (int)clamp_long(pan_us, PULSE_MIN, PULSE_MAX);
  tilt_target = (int)clamp_long(tilt_us, PULSE_MIN, PULSE_MAX);
  last_move_ms = millis();
  watchdog_expired = false;

  // later targets are reached by slew_tick, step by step
  if (!servos_attached) {
    attach_at(pan_target, tilt_target);
  }
}

// one step of at most cap us toward the target. both values are between 500 and 2500,
// so the difference stays within 2000 and a 16 bit int never overflows
int slew_toward(int now, int target, int cap) {
  int diff = target - now;
  if (diff > cap) {
    return now + cap;
  }
  if (diff < -cap) {
    return now - cap;
  }
  return target;
}

// runs every SLEW_TICK_US, so the cap is a speed limit in us per 10 ms
void slew_tick() {
  if (!servos_attached) {
    return;
  }
  int pan_next = slew_toward(pan_now, pan_target, slew_cap);
  int tilt_next = slew_toward(tilt_now, tilt_target, slew_cap);
  // only write on a change, every write briefly blocks interrupts in the library
  if (pan_next != pan_now) {
    pan_now = pan_next;
    pan_servo.writeMicroseconds(pan_now);
  }
  if (tilt_next != tilt_now) {
    tilt_now = tilt_next;
    tilt_servo.writeMicroseconds(tilt_now);
  }
}

// detach() only stops the timer from touching the pin. called in the middle of a pulse
// the line would stay high for good, and pulling it low by hand would cut the pulse short,
// which the servo takes as a command to jump. so we wait until the line is low, at most
// one pulse of 2.5 ms, and detach with interrupts off so no new pulse can start meanwhile
void detach_between_pulses(Servo &servo, uint8_t pin) {
  uint32_t start = micros();
  bool done = false;
  while (!done) {
    bool timed_out = (uint32_t)(micros() - start) > DETACH_WAIT_US;
    noInterrupts();
    if (digitalRead(pin) == LOW || timed_out) {
      servo.detach();
      done = true;
    }
    interrupts();
  }
  digitalWrite(pin, LOW);
}

// no pulses at all, the head goes limp. the next M attaches again right at its pulse
void command_detach() {
  if (servos_attached) {
    detach_between_pulses(pan_servo, PAN_PIN);
    detach_between_pulses(tilt_servo, TILT_PIN);
  }
  servos_attached = false;
}

void command_slew(long cap) {
  slew_cap = (int)clamp_long(cap, SLEW_MIN, SLEW_MAX);
}

bool servos_slewing() {
  return servos_attached && (pan_now != pan_target || tilt_now != tilt_target);
}

// ---------------------------------------------------------------------------
// sample frames

const uint8_t RATE_DEFAULT = 50;
const uint8_t RATE_MIN = 1;
const uint8_t RATE_MAX = 100;

uint32_t sample_period_us = 1000000UL / RATE_DEFAULT;
uint32_t last_sample_us = 0;
// counts every frame that was due, also the skipped ones, so the pi sees a gap
uint16_t seq = 0;

const uint8_t FLAG_ATTACHED = 1;
const uint8_t FLAG_WATCHDOG = 2;
const uint8_t FLAG_SLEWING = 4;

void send_frame() {
  uint16_t this_seq = seq;
  seq++;

  // a detached servo gets no pulses at all, the frame says 0 for it
  unsigned pan_out = 0;
  unsigned tilt_out = 0;
  unsigned flags = 0;
  if (servos_attached) {
    pan_out = pan_now;
    tilt_out = tilt_now;
    flags |= FLAG_ATTACHED;
  }
  if (watchdog_expired) {
    flags |= FLAG_WATCHDOG;
  }
  if (servos_slewing()) {
    flags |= FLAG_SLEWING;
  }

  char buf[72];
  int len = snprintf(buf, sizeof(buf), "S,%u,%u,%u,%u,%u,%lu,%u,%ld,%u,%u,%u\n",
                     this_seq, ldr_sum[0], ldr_sum[1], ldr_sum[2], ldr_sum[3],
                     lux10, panel_mv, panel_ua, pan_out, tilt_out, flags);
  if (len <= 0 || len >= (int)sizeof(buf)) {
    return;
  }
  Serial.write(buf, len);
}

void command_rate(long hz) {
  hz = clamp_long(hz, RATE_MIN, RATE_MAX);
  sample_period_us = 1000000UL / (uint32_t)hz;
  // the next frame comes one new period from now
  last_sample_us = micros();
}

// ---------------------------------------------------------------------------
// command lines

// the longest command is M,<pan>,<tilt>, one more slot lets us notice extra fields
const uint8_t FIELDS_MAX = 4;

// splits a line in place at the commas, returns the number of fields,
// or 0 when there are more than max of them
uint8_t split_fields(char *line, char *field[], uint8_t max) {
  uint8_t count = 0;
  char *p = line;
  while (true) {
    if (count == max) {
      return 0;
    }
    field[count] = p;
    count++;
    char *comma = strchr(p, ',');
    if (comma == NULL) {
      return count;
    }
    *comma = '\0';
    p = comma + 1;
  }
}

// strict decimal number: an optional minus and 1 to 9 digits, nothing else.
// nine digits always fit into a long, so a silly value can never overflow
bool parse_number(const char *text, long *out) {
  bool negative = false;
  if (*text == '-') {
    negative = true;
    text++;
  }
  uint8_t digits = 0;
  long value = 0;
  while (*text != '\0') {
    if (*text < '0' || *text > '9') {
      return false;
    }
    digits++;
    if (digits > 9) {
      return false;
    }
    value = value * 10 + (*text - '0');
    text++;
  }
  if (digits == 0) {
    return false;
  }
  *out = negative ? -value : value;
  return true;
}

// the ping number is echoed as text, so the pi may use any counter up to 20 digits
void command_ping(const char *number) {
  uint8_t len = strlen(number);
  if (len == 0 || len > 20) {
    send_error(ERR_BAD_COMMAND, "bad number");
    return;
  }
  for (uint8_t i = 0; i < len; i++) {
    if (number[i] < '0' || number[i] > '9') {
      send_error(ERR_BAD_COMMAND, "bad number");
      return;
    }
  }
  char buf[sizeof(reply_buf)];
  snprintf(buf, sizeof(buf), "P,%s", number);
  queue_reply(buf);
}

void handle_line(char *line) {
  char *field[FIELDS_MAX];
  uint8_t count = split_fields(line, field, FIELDS_MAX);
  if (count == 0 || strlen(field[0]) != 1) {
    send_error(ERR_BAD_COMMAND, "unknown command");
    return;
  }
  // lower case letters are fine too, that helps when someone types into a serial monitor
  char cmd = (char)toupper((unsigned char)field[0][0]);

  // how many fields each command has, the letter included
  uint8_t want;
  switch (cmd) {
    case '?':
    case 'D':
      want = 1;
      break;
    case 'P':
    case 'R':
    case 'L':
      want = 2;
      break;
    case 'M':
      want = 3;
      break;
    default:
      send_error(ERR_BAD_COMMAND, "unknown command");
      return;
  }
  if (count != want) {
    send_error(ERR_BAD_COMMAND, "wrong field count");
    return;
  }

  // every number is checked before anything changes, a bad line has no effect at all
  long a = 0;
  long b = 0;
  bool numbers_ok = true;
  if (cmd == 'R' || cmd == 'L') {
    numbers_ok = parse_number(field[1], &a);
  } else if (cmd == 'M') {
    numbers_ok = parse_number(field[1], &a) && parse_number(field[2], &b);
  }
  if (!numbers_ok) {
    send_error(ERR_BAD_COMMAND, "bad number");
    return;
  }

  switch (cmd) {
    case '?':
      send_identity();
      break;
    case 'P':
      command_ping(field[1]);
      break;
    case 'R':
      command_rate(a);
      break;
    case 'L':
      command_slew(a);
      break;
    case 'D':
      command_detach();
      break;
    case 'M':
      command_move(a, b);
      break;
  }
}

// the line being received, it never holds more than LINE_MAX characters
char line_buf[LINE_MAX + 1];
uint8_t line_len = 0;
// set when a line grew past LINE_MAX, the rest is thrown away up to the next newline
bool line_too_long = false;
// set when a line holds a byte that is not printable ascii, for example noise on the wire
bool line_garbage = false;

void finish_line() {
  if (line_too_long) {
    send_error(ERR_TOO_LONG, "line too long");
  } else if (line_garbage) {
    send_error(ERR_BAD_COMMAND, "bad character");
  } else if (line_len > 0) {
    // empty lines are ignored so a stray newline from the pi does not cause an error
    line_buf[line_len] = '\0';
    handle_line(line_buf);
  }
  line_len = 0;
  line_too_long = false;
  line_garbage = false;
}

void read_serial() {
  // at most one complete line per pass, the other jobs in loop keep their timing,
  // and no new line is taken while an answer still waits for room
  while (!reply_pending && Serial.available() > 0) {
    uint8_t c = Serial.read();
    if (c == '\n') {
      finish_line();
      return;
    }
    if (c == '\r') {
      // a terminal may send \r\n, the \r carries no meaning
      continue;
    }
    if (line_too_long) {
      continue;
    }
    if (line_len >= LINE_MAX) {
      line_too_long = true;
      continue;
    }
    if (c < 32 || c > 126) {
      line_garbage = true;
    }
    line_buf[line_len] = (char)c;
    line_len++;
  }
}

// ---------------------------------------------------------------------------

void setup() {
  // the servo lines stay low until the first M, a floating line can make a servo twitch
  pinMode(PAN_PIN, OUTPUT);
  digitalWrite(PAN_PIN, LOW);
  pinMode(TILT_PIN, OUTPUT);
  digitalWrite(TILT_PIN, LOW);

  Serial.begin(BAUD);
  adc_start(0);

  Wire.begin();
  Wire.setWireTimeout(I2C_TIMEOUT_US, true);
  // the sensors are looked for before the identity line, so its caps are right
  bh1750_probe();
  ina219_probe();

  send_identity();
  last_sample_us = micros();
  last_slew_us = last_sample_us;
  last_move_ms = millis();
}

void loop() {
  flush_reply();
  read_serial();
  adc_step();

  // the clocks are read after the commands ran, a command may have just restarted a timer
  // and a time from before that would look like a huge negative gap
  uint32_t now_us = micros();
  if (tick_due(last_slew_us, SLEW_TICK_US, now_us)) {
    slew_tick();
  }
  if (tick_due(last_sample_us, sample_period_us, now_us)) {
    send_frame();
  }

  uint32_t now_ms = millis();
  watchdog_check(now_ms);
  sensors_step(now_ms);
}
