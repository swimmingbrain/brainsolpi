// brainsol bridge firmware for the keyestudio uno (atmega328p, 16 mhz)
//
// the raspberry pi runs the control loop, this board only reads the sensors,
// drives the two servos and talks a small line protocol over the usb serial port.
// the protocol and the pin map are described in firmware/README.md

#include <Servo.h>

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

uint8_t caps() {
  // no sensors yet
  return 0;
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
                     0UL, 0U, 0L, pan_out, tilt_out, flags);
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
}
