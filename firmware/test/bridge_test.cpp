// runs the bridge sketch on a pc against a fake uart, fake servos, a fake adc and fake
// i2c sensors, and checks the protocol, the timing, the slew and the watchdog.
// build and run it with firmware/test/run.sh, it builds this file once as it is and once with
// PANEL_A4 for the variant with the panel on a4
#include "Arduino.h"
#include "Servo.h"
#include "Wire.h"

#include <regex>

// the identity line after boot, the variant says 4 for the panel on a4
#ifdef PANEL_A4
#define IDENTITY "I,brainsol,1.0.0,4"
#else
#define IDENTITY "I,brainsol,1.0.0,0"
#endif

uint64_t mock_time_us = 0;
uint64_t mock_us_offset = 0;
uint64_t mock_ms_offset = 0;
int mock_irq_off = 0;
uint8_t mock_pin_mode[32];
uint8_t mock_pin_level[32];
uint8_t ADMUX, ADCSRA, ADCL, ADCH;
MockSerial Serial;
MockBus bus;
TwoWire Wire;
std::vector<ServoEvent> servo_events;
int Servo::count = 0;

void pinMode(uint8_t pin, uint8_t mode) { mock_pin_mode[pin] = mode; }
void digitalWrite(uint8_t pin, uint8_t level) { mock_pin_level[pin] = level; }

// the arduino build adds prototypes by itself, this is the one function used before it
// is defined
uint8_t caps();
#include "../brainsol_bridge/brainsol_bridge.ino"

// the servo timer: pan pulse at the start of every 20 ms frame, tilt right after it
int digitalRead(uint8_t pin) {
  uint32_t t = (uint32_t)(mock_time_us % 20000);
  if (pin == PAN_PIN && pan_servo.active) {
    return t < (uint32_t)pan_servo.pulse_us ? HIGH : LOW;
  }
  if (pin == TILT_PIN && tilt_servo.active) {
    uint32_t start = pan_servo.active ? (uint32_t)pan_servo.pulse_us : 0;
    return (t >= start && t < start + (uint32_t)tilt_servo.pulse_us) ? HIGH : LOW;
  }
  return mock_pin_level[pin];
}

// ===========================================================================
// simulation

// the four light sensors and a4, the first reading after a channel switch is a mix with the
// previous channel like on the real chip, so a missing throwaway would show
uint16_t adc_value[8] = {100, 200, 300, 400, 0, 0, 0, 0};
int adc_last_channel = -1;
bool adc_running = false;
uint64_t adc_started = 0;
double tx_credit = 0;
// time one pass of loop takes on the board, roughly
const int PASS_US = 30;

void step() {
  mock_time_us += PASS_US;
  // the uart sends 11.52 bytes per ms at 115200 baud
  tx_credit += PASS_US * 0.01152;
  while (tx_credit >= 1 && Serial.tx_used > 0) {
    Serial.tx_used--;
    tx_credit -= 1;
  }
  if (Serial.tx_used == 0 && tx_credit > 2) {
    tx_credit = 2;
  }
  if (ADCSRA & _BV(ADSC)) {
    if (!adc_running) {
      adc_running = true;
      adc_started = mock_time_us;
    } else if (mock_time_us - adc_started >= 104) {
      int channel = ADMUX & 7;
      uint16_t v = adc_value[channel];
      if (adc_last_channel >= 0 && adc_last_channel != channel) {
        v = (uint16_t)((v + adc_value[adc_last_channel]) / 2);
      }
      adc_last_channel = channel;
      ADCL = (uint8_t)(v & 0xFF);
      ADCH = (uint8_t)(v >> 8);
      ADCSRA = (uint8_t)(ADCSRA & ~_BV(ADSC));
      adc_running = false;
    }
  }
  loop();
}

void run_ms(uint32_t ms) {
  uint64_t end = mock_time_us + (uint64_t)ms * 1000;
  while (mock_time_us < end) {
    step();
  }
}

// ===========================================================================
// reading the output

size_t out_pos = 0;

std::vector<std::string> take_lines() {
  std::vector<std::string> lines;
  size_t nl;
  while ((nl = Serial.out.find('\n', out_pos)) != std::string::npos) {
    lines.push_back(Serial.out.substr(out_pos, nl - out_pos));
    out_pos = nl + 1;
  }
  return lines;
}

int failures = 0;

#define CHECK(cond, msg)                              \
  do {                                                \
    if (!(cond)) {                                    \
      failures++;                                     \
      printf("FAIL line %d: %s\n", __LINE__, msg);    \
    }                                                 \
  } while (0)

// the frame table of the protocol, character for character
const std::regex frame_re(
    "^S,(\\d+),(\\d+),(\\d+),(\\d+),(\\d+),(\\d+),(\\d+),(-?\\d+),(\\d+),(\\d+),(\\d+)$");

enum { SEQ, L, R, U, D, LUX10, MV, UA, PAN, TILT, FLAGS };

struct Frame {
  long v[11];
};

std::vector<Frame> frames_of(const std::vector<std::string> &lines,
                             std::vector<std::string> *others = nullptr) {
  std::vector<Frame> frames;
  for (const std::string &line : lines) {
    std::smatch m;
    if (std::regex_match(line, m, frame_re)) {
      Frame f;
      for (int i = 0; i < 11; i++) {
        f.v[i] = atol(m[i + 1].str().c_str());
      }
      frames.push_back(f);
    } else if (!line.empty() && line[0] == 'S') {
      printf("FAIL bad frame: %s\n", line.c_str());
      failures++;
    } else if (others != nullptr) {
      others->push_back(line);
    }
  }
  return frames;
}

Frame last_frame(const std::vector<Frame> &frames, int line) {
  static Frame zero = {};
  if (frames.empty()) {
    printf("FAIL line %d: no frames\n", line);
    failures++;
    return zero;
  }
  return frames.back();
}

std::vector<std::string> answers(const std::vector<std::string> &lines) {
  std::vector<std::string> result;
  for (const std::string &line : lines) {
    if (line.empty() || line[0] != 'S') {
      result.push_back(line);
    }
  }
  return result;
}

// sends text, runs for a while and returns everything that is not a frame
std::vector<std::string> ask(const std::string &text, uint32_t ms = 50) {
  take_lines();
  Serial.feed(text);
  run_ms(ms);
  return answers(take_lines());
}

bool one_answer(const std::vector<std::string> &got, const char *want) {
  if (got.size() == 1 && got[0] == want) {
    return true;
  }
  printf("   wanted [%s], got %zu lines:", want, got.size());
  for (const std::string &line : got) {
    printf(" [%s]", line.c_str());
  }
  printf("\n");
  return false;
}

// ===========================================================================
// tests

void test_boot_and_frames() {
  ADCSRA = 0x87;  // what the core leaves behind: adc on, prescaler 128
  setup();
  std::vector<std::string> lines = take_lines();
  CHECK(lines.size() == 1 && lines[0] == IDENTITY, "identity line comes first");

  run_ms(1000);
  std::vector<Frame> frames = frames_of(take_lines());
  printf("frames in the first second: %zu\n", frames.size());
  CHECK(frames.size() >= 49 && frames.size() <= 51, "about 50 frames per second");
  for (size_t i = 1; i < frames.size(); i++) {
    CHECK(frames[i].v[SEQ] == (frames[i - 1].v[SEQ] + 1) % 65536, "seq counts up by one");
  }
  Frame f = last_frame(frames, __LINE__);
  CHECK(f.v[L] == 800 && f.v[R] == 1600 && f.v[U] == 2400 && f.v[D] == 3200,
        "sums of 8 readings per channel, the mixed first reading is thrown away");
  CHECK(f.v[LUX10] == 0 && f.v[MV] == 0 && f.v[UA] == 0, "no sensors gives zeros");
  CHECK(f.v[PAN] == 0 && f.v[TILT] == 0, "detached servos report 0");
  CHECK(f.v[FLAGS] == 0, "no flags after 1 s");

  run_ms(600);
  f = last_frame(frames_of(take_lines()), __LINE__);
  CHECK(f.v[FLAGS] == 2, "watchdog flag after 1.6 s without M");
}

void test_command_parser() {
  CHECK(one_answer(ask("?\n"), IDENTITY), "identity on ?");
  CHECK(one_answer(ask("P,12345678901234567890\n"), "P,12345678901234567890"), "ping with 20 digits");
  CHECK(one_answer(ask("P,123456789012345678901\n"), "E,1,bad number"), "ping with 21 digits");
  CHECK(one_answer(ask("P,12a\n"), "E,1,bad number"), "ping with a letter");
  CHECK(one_answer(ask("p,7\r\n"), "P,7"), "lower case letter and a cr before the newline");
  CHECK(one_answer(ask("X\n"), "E,1,unknown command"), "unknown letter");
  CHECK(one_answer(ask("MM,1,2\n"), "E,1,unknown command"), "two letters");
  CHECK(one_answer(ask(",\n"), "E,1,unknown command"), "only a comma");
  CHECK(ask("\n\r\n\n").empty(), "empty lines are ignored");
  CHECK(one_answer(ask("M,1500\n"), "E,1,wrong field count"), "M with one value");
  CHECK(one_answer(ask("M,1500,1500,1\n"), "E,1,wrong field count"), "M with three values");
  CHECK(one_answer(ask("M,1,2,3,4,5,6\n"), "E,1,wrong field count"), "M with six values");
  CHECK(one_answer(ask("D,1\n"), "E,1,wrong field count"), "D with a value");
  CHECK(one_answer(ask("M,15a0,1500\n"), "E,1,bad number"), "letter in a number");
  CHECK(one_answer(ask("M,,1500\n"), "E,1,bad number"), "empty number");
  CHECK(one_answer(ask("M,1500, 1500\n"), "E,1,bad number"), "space in a number");
  CHECK(one_answer(ask("M,9999999999,1500\n"), "E,1,bad number"), "ten digits");
  CHECK(one_answer(ask("M,-,1500\n"), "E,1,bad number"), "minus alone");
  CHECK(one_answer(ask("R,\n"), "E,1,bad number"), "R without a value");
  CHECK(!pan_servo.active, "no bad line attached a servo");

  // an overlong line is dropped up to its newline and the next line works again
  std::vector<std::string> got = ask(std::string(300, 'A') + "\n?\n", 100);
  CHECK(got.size() == 2 && got[0] == "E,2,line too long" && got[1] == IDENTITY,
        "overlong line, then a good one");
  std::string p96 = "P," + std::string(94, '1');
  CHECK(one_answer(ask(p96 + "\n"), "E,1,bad number"), "96 characters are still parsed");
  CHECK(one_answer(ask(p96 + "1\n"), "E,2,line too long"), "97 characters are too long");

  // noise on the line
  CHECK(one_answer(ask(std::string("\xff\x00\x13M,1500,1500\n", 15)), "E,1,bad character"),
        "bytes that are not printable");
  CHECK(!pan_servo.active, "noise attached no servo");

  // a half line left over from an earlier session is glued to the next command
  ask("M,15");
  CHECK(one_answer(ask("?\n"), "E,1,wrong field count"), "half line plus a new command");
  CHECK(one_answer(ask("?\n"), IDENTITY), "the line after that works");
}

void test_first_move() {
  servo_events.clear();
  CHECK(ask("M,2500,520\n", 15).empty(), "M has no answer");
  bool attach_near_target = true;
  bool irq_off = true;
  for (const ServoEvent &e : servo_events) {
    printf("   servo %d %s %d with interrupts %s\n", e.servo, e.what.c_str(), e.value,
           e.irq_off ? "off" : "on");
    // before attach the library clamps to 544 to 2400, so 2400 and 544 are the closest
    if (e.what == "attach" && e.value != (e.servo == 0 ? 2400 : 544)) {
      attach_near_target = false;
    }
    if (!e.irq_off) {
      irq_off = false;
    }
  }
  CHECK(attach_near_target, "the pulse is set before attach, no default 1500 us");
  CHECK(irq_off, "attach runs with interrupts off");
  CHECK(pan_servo.pulse_us == 2500 && tilt_servo.pulse_us == 520, "exact pulses after attach");
  run_ms(30);
  Frame f = last_frame(frames_of(take_lines()), __LINE__);
  CHECK(f.v[PAN] == 2500 && f.v[TILT] == 520, "frame shows the commanded pulses at once");
  CHECK(f.v[FLAGS] == 1, "attached, watchdog fed, not slewing");
}

void test_slew() {
  ask("M,500,2500\n", 5);
  int steps = 1;  // one tick already ran inside those 5 ms
  uint64_t t0 = mock_time_us;
  bool small_steps = true;
  while (pan_servo.pulse_us != 500 && mock_time_us - t0 < 2000000) {
    int before = pan_servo.pulse_us;
    step();
    if (pan_servo.pulse_us != before) {
      if (before - pan_servo.pulse_us > 30) {
        small_steps = false;
      }
      steps++;
    }
  }
  printf("slew from 2500 to 500 us: %d steps\n", steps);
  CHECK(small_steps, "no step is larger than 30 us");
  CHECK(steps == 67, "2000 us at 30 us per tick are 67 steps");
  CHECK(tilt_servo.pulse_us == 2500, "tilt reached its target too");
  run_ms(30);
  CHECK(last_frame(frames_of(take_lines()), __LINE__).v[FLAGS] == 1, "slewing flag clears at the target");

  ask("M,1000,2000\n", 5);
  run_ms(20);
  CHECK(last_frame(frames_of(take_lines()), __LINE__).v[FLAGS] == 5, "slewing flag while on the way");

  ask("L,200\n", 5);
  ask("M,2500,500\n", 5);
  run_ms(100);
  CHECK(pan_servo.pulse_us == 2500 && tilt_servo.pulse_us == 500, "L,200 is fast");
  ask("L,0\n", 5);
  CHECK(slew_cap == 1, "L clamps to 1");
  ask("L,100000\n", 5);
  CHECK(slew_cap == 200, "L clamps to 200");
  ask("L,30\n", 5);

  ask("M,-5,99999\n", 5);
  CHECK(pan_target == 500 && tilt_target == 2500, "M clamps to 500 and 2500");
}

void test_rate() {
  ask("R,100\n", 5);
  take_lines();
  run_ms(1000);
  size_t n = frames_of(take_lines()).size();
  printf("frames per second at R,100: %zu\n", n);
  CHECK(n >= 99 && n <= 101, "100 Hz");

  ask("R,0\n", 5);
  take_lines();
  run_ms(3000);
  n = frames_of(take_lines()).size();
  CHECK(n == 3, "R,0 is clamped to 1 Hz");
  ask("R,50\n", 5);
}

void test_watchdog() {
  ask("M,1500,1500\n", 5);
  run_ms(1400);
  take_lines();
  run_ms(50);
  CHECK((last_frame(frames_of(take_lines()), __LINE__).v[FLAGS] & 2) == 0, "no flag at 1.45 s");
  run_ms(100);
  CHECK((last_frame(frames_of(take_lines()), __LINE__).v[FLAGS] & 2) == 2, "flag at 1.55 s");
  int pan_before = pan_servo.pulse_us;
  run_ms(2000);
  CHECK(pan_servo.pulse_us == pan_before && pan_servo.active, "the watchdog only holds");
  ask("M,1500,1500\n", 5);
  run_ms(30);
  CHECK((last_frame(frames_of(take_lines()), __LINE__).v[FLAGS] & 2) == 0, "M clears the flag");
}

void test_detach() {
  servo_events.clear();
  for (int k = 0; k < 40; k++) {
    ask("M,2000,1000\n", 600);
    // a different phase of the pulse train every round
    mock_time_us += 457;
    take_lines();
    Serial.feed("D\n");
    run_ms(30);
    CHECK(!pan_servo.active && !tilt_servo.active, "both detached");
    CHECK(mock_pin_level[PAN_PIN] == LOW && mock_pin_level[TILT_PIN] == LOW, "both lines low");
  }
  int detaches = 0;
  int cut = 0;
  for (const ServoEvent &e : servo_events) {
    if (e.what == "detach") {
      detaches++;
      if (e.value != LOW || !e.irq_off) {
        cut++;
      }
    }
  }
  printf("detaches: %d, in the middle of a pulse: %d\n", detaches, cut);
  CHECK(detaches == 80 && cut == 0, "a detach never cuts a pulse short");
  Frame f = last_frame(frames_of(take_lines()), __LINE__);
  CHECK(f.v[PAN] == 0 && f.v[TILT] == 0 && (f.v[FLAGS] & 1) == 0, "detached frame");

  ask("M,800,2200\n", 5);
  CHECK(pan_servo.pulse_us == 800 && tilt_servo.pulse_us == 2200, "the next M attaches at its pulse");
}

#ifndef PANEL_A4
void test_sensors() {
  // plugged in while running
  bus.bh_present = true;
  bus.bh_raw = 65535;
  bus.ina_present = true;
  bus.ina_regs[2] = (uint16_t)(((12000 / 4) << 3) | 2);  // 12 v and the conversion ready bit
  bus.ina_regs[1] = (uint16_t)(int16_t)-1234;
  run_ms(3200);
  CHECK(one_answer(ask("?\n"), "I,brainsol,1.0.0,3"), "caps 3 after a late plug");
  CHECK(bus.bh_powered && bus.bh_continuous, "bh1750 woken up and in continuous mode");
  CHECK(bus.ina_regs[0] == 0x399F, "ina219 config written");
  CHECK(bus.timeout_us > 0 && bus.timeout_reset, "wire timeout is on");
  run_ms(400);
  Frame f = last_frame(frames_of(take_lines()), __LINE__);
  printf("lux10 %ld, mv %ld, ua %ld\n", f.v[LUX10], f.v[MV], f.v[UA]);
  CHECK(f.v[LUX10] == 546125, "largest bh1750 value");
  CHECK(f.v[MV] == 12000, "12 v bus voltage");
  CHECK(f.v[UA] == -123400, "negative current");
  bus.bh_raw = 12;
  run_ms(400);
  CHECK(last_frame(frames_of(take_lines()), __LINE__).v[LUX10] == 100, "12 counts are 10.0 lux");

  bus.bh_present = false;
  bus.ina_present = false;
  run_ms(1000);
  f = last_frame(frames_of(take_lines()), __LINE__);
  CHECK(f.v[LUX10] == 0 && f.v[MV] == 0 && f.v[UA] == 0, "zeros after an unplug");
  CHECK(one_answer(ask("?\n"), "I,brainsol,1.0.0,0"), "caps 0 after an unplug");

  // the other bh1750 address
  bus.bh_addr = 0x5C;
  bus.bh_present = true;
  bus.bh_raw = 120;
  run_ms(3500);
  CHECK(one_answer(ask("?\n"), "I,brainsol,1.0.0,1"), "bh1750 on 0x5c");
  run_ms(400);
  CHECK(last_frame(frames_of(take_lines()), __LINE__).v[LUX10] == 1000, "120 counts are 100.0 lux");
}
#else
// the variant with the panel on a4: a4 is a fifth channel of the same round with the same
// throwaway and the same sum of 8, the panel field carries the pin voltage in mv, lux and the
// current stay 0, and the i2c bus is never touched
Frame frame_after(uint16_t a4_counts) {
  adc_value[4] = a4_counts;
  take_lines();
  run_ms(100);
  return last_frame(frames_of(take_lines()), __LINE__);
}

void test_panel_pin() {
  CHECK(!bus.began && bus.timeout_us == 0 && bus.transfers == 0, "the bus was never started");
  // a4 right after a much brighter a3, a mixed first reading would show in both sums
  adc_value[3] = 1000;
  Frame f = frame_after(512);
  printf("a4 at 512 counts: %ld mv\n", f.v[MV]);
  CHECK(f.v[MV] == 2500, "8 x 512 counts are 2500 mv at the pin");
  CHECK(f.v[D] == 8000, "a3 keeps its own sum");
  CHECK(f.v[L] == 800 && f.v[R] == 1600 && f.v[U] == 2400, "a0 after a4 drops its mixed first reading too");
  CHECK(f.v[LUX10] == 0 && f.v[UA] == 0, "no lux and no current in this variant");
  CHECK(frame_after(1023).v[MV] == 4995, "the top of the range is 4995 mv");
  CHECK(frame_after(1).v[MV] == 5, "one count is about 5 mv");
  CHECK(frame_after(0).v[MV] == 0, "nothing at the pin is 0 mv");
  adc_value[3] = 400;

  // sensors on the bus are never looked for, the caps stay the same
  bus.bh_present = true;
  bus.ina_present = true;
  run_ms(3500);
  CHECK(one_answer(ask("?\n"), IDENTITY), "caps 4 with sensors on the bus");
  f = frame_after(0);
  CHECK(f.v[LUX10] == 0 && f.v[UA] == 0, "still no lux and no current");
  CHECK(bus.transfers == 0 && !bus.bh_powered && bus.ina_regs[0] == 0, "nobody talked to them");
  bus.bh_present = false;
  bus.ina_present = false;
}
#endif

void test_longest_frame() {
  char buf[100];
  int n = snprintf(buf, sizeof(buf), "S,%u,%u,%u,%u,%u,%lu,%u,%ld,%u,%u,%u\n", 65535u, 8184u,
                   8184u, 8184u, 8184u, 546125ul, 32764u, -3276800l, 2500u, 2500u, 7u);
  printf("longest frame, %d characters with the newline: %s", n, buf);
  CHECK(n <= 63, "the longest frame fits into the transmit buffer");
}

void test_transmit_pressure() {
  CHECK(Serial.blocked_writes == 0, "no write had to wait so far");
  bus.bh_present = true;
  bus.ina_present = true;
  ask("R,100\n", 5);
  run_ms(3500);
  take_lines();
  for (int i = 0; i < 200; i++) {
    Serial.feed("P," + std::to_string(i) + "\n");
  }
  run_ms(1000);
  std::vector<std::string> others;
  std::vector<Frame> frames = frames_of(take_lines(), &others);
  int pings = 0;
  for (const std::string &line : others) {
    if (line.rfind("P,", 0) == 0) {
      pings++;
    }
  }
  printf("200 pings at once: %d answers, %zu frames in 1 s\n", pings, frames.size());
  CHECK(pings == 200, "every ping is answered");
  CHECK(Serial.blocked_writes == 0, "no write ever had to wait for room");

  seq = 65534;
  run_ms(50);
  frames = frames_of(take_lines());
  bool wrapped = false;
  for (size_t i = 1; i < frames.size(); i++) {
    if (frames[i - 1].v[SEQ] == 65535 && frames[i].v[SEQ] == 0) {
      wrapped = true;
    }
  }
  CHECK(wrapped, "seq wraps from 65535 to 0");
}

int main(int argc, char **argv) {
  setvbuf(stdout, NULL, _IONBF, 0);
  if (argc > 1 && strcmp(argv[1], "wrap") == 0) {
    // both clocks wrap two seconds after the start
    mock_us_offset = 0xFFFFFFFFULL - 2000000ULL;
    mock_ms_offset = 0xFFFFFFFFULL - 2000ULL;
    printf("run across the clock wrap\n");
  }
#ifdef PANEL_A4
  printf("variant with the panel on a4\n");
#endif
  test_boot_and_frames();
  test_command_parser();
  test_first_move();
  test_slew();
  test_rate();
  test_watchdog();
  test_detach();
#ifdef PANEL_A4
  test_panel_pin();
#else
  test_sensors();
#endif
  test_longest_frame();
  test_transmit_pressure();
  printf("%s, %d failures\n", failures ? "FAILED" : "all ok", failures);
  return failures ? 1 : 0;
}
