// brainsol bridge firmware for the keyestudio uno (atmega328p, 16 mhz)
//
// the raspberry pi runs the control loop, this board only reads the sensors,
// drives the two servos and talks a small line protocol over the usb serial port.
// the protocol and the pin map are described in firmware/README.md

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
// command lines

void handle_line(char *line) {
  if (strcmp(line, "?") == 0) {
    send_identity();
    return;
  }
  send_error(ERR_BAD_COMMAND, "unknown command");
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
  Serial.begin(BAUD);
  send_identity();
}

void loop() {
  flush_reply();
  read_serial();
}
