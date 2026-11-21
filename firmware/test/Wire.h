// stand in for Wire with a simulated bh1750 and ina219 that can be plugged and unplugged
#pragma once
#include "Arduino.h"

struct MockBus {
  bool bh_present = false;
  uint8_t bh_addr = 0x23;
  uint16_t bh_raw = 0;
  bool bh_powered = false;
  bool bh_continuous = false;
  bool ina_present = false;
  uint16_t ina_regs[8] = {0};
  uint8_t ina_pointer = 0;
  uint32_t timeout_us = 0;
  bool timeout_reset = false;
  // the variant with the panel on a4 must never touch the bus
  bool began = false;
  int transfers = 0;
};
extern MockBus bus;

class TwoWire {
 public:
  uint8_t tx_addr = 0;
  std::vector<uint8_t> tx;
  std::deque<uint8_t> rx;

  void begin() { bus.began = true; }
  void setWireTimeout(uint32_t timeout, bool reset) {
    bus.timeout_us = timeout;
    bus.timeout_reset = reset;
  }
  void beginTransmission(uint8_t addr) {
    tx_addr = addr;
    tx.clear();
  }
  size_t write(uint8_t value) {
    tx.push_back(value);
    return 1;
  }
  uint8_t endTransmission() {
    bus.transfers++;
    if (bus.bh_present && tx_addr == bus.bh_addr) {
      for (uint8_t b : tx) {
        if (b == 0x01) {
          bus.bh_powered = true;
        }
        if (b == 0x10) {
          bus.bh_continuous = true;
        }
      }
      return 0;
    }
    if (bus.ina_present && tx_addr == 0x40) {
      if (tx.size() >= 1) {
        bus.ina_pointer = tx[0] & 7;
      }
      if (tx.size() == 3) {
        bus.ina_regs[bus.ina_pointer] = (uint16_t)((tx[1] << 8) | tx[2]);
      }
      return 0;
    }
    // nobody answered the address
    return 2;
  }
  uint8_t requestFrom(uint8_t addr, uint8_t n) {
    bus.transfers++;
    rx.clear();
    uint16_t value;
    if (bus.bh_present && addr == bus.bh_addr) {
      value = bus.bh_raw;
    } else if (bus.ina_present && addr == 0x40) {
      value = bus.ina_regs[bus.ina_pointer];
    } else {
      return 0;
    }
    if (n != 2) {
      return 0;
    }
    rx.push_back((uint8_t)(value >> 8));
    rx.push_back((uint8_t)(value & 0xFF));
    return 2;
  }
  int available() { return (int)rx.size(); }
  int read() {
    if (rx.empty()) {
      return -1;
    }
    int value = rx.front();
    rx.pop_front();
    return value;
  }
};
extern TwoWire Wire;
