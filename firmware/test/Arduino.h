// small stand in for the arduino core, just enough to run the bridge sketch on a pc
#pragma once
#include <ctype.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <deque>
#include <string>
#include <vector>

typedef uint8_t byte;
typedef bool boolean;

#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define _BV(b) (1u << (b))
#define bit_is_set(reg, bit) ((reg) & _BV(bit))

// both clocks can start anywhere, so a test can run across the wrap
extern uint64_t mock_time_us;
extern uint64_t mock_us_offset;
extern uint64_t mock_ms_offset;
// every call costs a microsecond, so busy loops in the sketch see time pass
inline uint32_t micros() {
  mock_time_us += 1;
  return (uint32_t)(mock_time_us + mock_us_offset);
}
inline uint32_t millis() { return (uint32_t)(mock_time_us / 1000ULL + mock_ms_offset); }

extern int mock_irq_off;
inline void noInterrupts() { mock_irq_off = 1; }
inline void interrupts() { mock_irq_off = 0; }

extern uint8_t mock_pin_mode[32];
extern uint8_t mock_pin_level[32];
void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t level);
int digitalRead(uint8_t pin);

// adc registers of the atmega328p, the test plays the converter
extern uint8_t ADMUX, ADCSRA, ADCL, ADCH;
#define REFS0 6
#define ADSC 6

// the uart with its 64 byte ring buffer, 63 bytes of it usable like on the avr
struct MockSerial {
  std::deque<uint8_t> rx;
  std::string out;
  int tx_used = 0;
  // writes that would have made the real Serial.write wait
  int blocked_writes = 0;

  void begin(unsigned long) {}
  int available() { return (int)rx.size(); }
  int read() {
    if (rx.empty()) {
      return -1;
    }
    int c = rx.front();
    rx.pop_front();
    return c;
  }
  int availableForWrite() { return 63 - tx_used; }
  size_t write(const char *buf, size_t len) {
    if ((int)len > availableForWrite()) {
      blocked_writes++;
    }
    out.append(buf, len);
    tx_used += (int)len;
    if (tx_used > 63) {
      tx_used = 63;
    }
    return len;
  }
  void feed(const std::string &text) {
    for (char c : text) {
      rx.push_back((uint8_t)c);
    }
  }
};
extern MockSerial Serial;
