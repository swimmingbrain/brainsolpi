// stand in for the avr Servo library. it clamps like the real one: before attach()
// the range is the default 544 to 2400 us, attach() sets the range it is given
#pragma once
#include "Arduino.h"

struct ServoEvent {
  int servo;
  std::string what;
  // the pulse for write and attach, the line level for detach
  int value;
  int irq_off;
};
extern std::vector<ServoEvent> servo_events;

class Servo {
 public:
  static int count;
  int index;
  int8_t min = 0;
  int8_t max = 0;
  int pin = -1;
  bool active = false;
  // the pulse the timer would send next
  int pulse_us = 1500;

  Servo() { index = count++; }

  uint8_t attach(int p, int lo, int hi) {
    pin = p;
    min = (int8_t)((544 - lo) / 4);
    max = (int8_t)((2400 - hi) / 4);
    pinMode((uint8_t)p, OUTPUT);
    active = true;
    servo_events.push_back({index, "attach", pulse_us, mock_irq_off});
    return (uint8_t)index;
  }

  void detach() {
    int level = digitalRead((uint8_t)pin);
    active = false;
    servo_events.push_back({index, "detach", level, mock_irq_off});
  }

  void writeMicroseconds(int value) {
    int lo = 544 - min * 4;
    int hi = 2400 - max * 4;
    if (value < lo) {
      value = lo;
    } else if (value > hi) {
      value = hi;
    }
    pulse_us = value;
    servo_events.push_back({index, "write", value, mock_irq_off});
  }

  bool attached() { return active; }
};
