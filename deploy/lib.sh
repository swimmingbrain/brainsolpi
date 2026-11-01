#!/usr/bin/env bash
# shared helpers for the brainsol deploy scripts, install.sh, update.sh and uninstall.sh
# source it, do not run it

# the repo root is the folder above deploy/
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="$repo/.venv"
# raspberry pi os puts ~/.local/bin on the path at login when the folder exists
# shellcheck disable=SC2034
command_link="$HOME/.local/bin/brainsolpi"
unit_file=/etc/systemd/system/brainsolpi.service
# these two are used by the scripts that source this file
# shellcheck disable=SC2034
sudoers_file=/etc/sudoers.d/brainsolpi
# shellcheck disable=SC2034
http_port=8080

step() {
  printf '\n%s\n' "$*"
}

info() {
  printf '  %s\n' "$*"
}

warn() {
  printf '  warning: %s\n' "$*" >&2
}

fail() {
  printf '\nstopped: %s\n' "$*" >&2
  exit 1
}

# asks a yes or no question. the second argument is the answer for a plain enter, y or n.
# without a terminal nobody can answer, then the answer is always no
ask() {
  local question="$1"
  local default="${2:-n}"
  local hint="[y/N]"
  local answer=""
  if [ "$default" = y ]; then
    hint="[Y/n]"
  fi
  if [ ! -t 0 ]; then
    return 1
  fi
  read -r -p "  $question $hint " answer || answer=""
  answer="${answer:-$default}"
  case "$answer" in
    y | Y | yes | Yes | YES) return 0 ;;
    *) return 1 ;;
  esac
}

# prints the serial port of the first board it finds, same order as firmware/flash.sh
find_board_port() {
  local p
  for p in /dev/serial/by-id/*[Aa]rduino* /dev/ttyACM* /dev/ttyUSB*; do
    if [ -e "$p" ]; then
      printf '%s\n' "$p"
      return 0
    fi
  done
  return 1
}

# true when the current shell already has the group, a fresh usermod needs a new login.
# grep reads all of its input here, grep -q could stop early and with pipefail the
# broken pipe of tr would turn a match into a failure
in_group_now() {
  id -nG | tr ' ' '\n' | grep -x "$1" >/dev/null
}

# true when the user is in the group in /etc/group, also right after a usermod
in_group_saved() {
  id -nG "$(id -un)" | tr ' ' '\n' | grep -x "$1" >/dev/null
}

# makes a value safe for the right side of a sed s|...|...| command
sed_escape() {
  printf '%s' "$1" | sed -e 's/[\\|&]/\\&/g'
}

# writes the unit template with the fields filled in to the file given as $1
render_unit() {
  local user
  local group
  user="$(id -un)"
  group="$(id -gn)"
  sed -e "s|@USER@|$(sed_escape "$user")|g" \
    -e "s|@GROUP@|$(sed_escape "$group")|g" \
    -e "s|@REPO@|$(sed_escape "$repo")|g" \
    -e "s|@VENV@|$(sed_escape "$venv")|g" \
    "$repo/deploy/brainsolpi.service" >"$1"
}

# installs the filled unit when it differs from the one that is installed
install_unit() {
  local tmp
  tmp="$(mktemp)"
  render_unit "$tmp"
  if [ -f "$unit_file" ] && cmp -s "$tmp" "$unit_file"; then
    rm -f "$tmp"
    info "the service unit is up to date"
    return 0
  fi
  sudo install -m 0644 -o root -g root "$tmp" "$unit_file"
  rm -f "$tmp"
  sudo systemctl daemon-reload
  info "installed $unit_file"
}

# installs the package and its dependencies into the venv, editable so a git pull is enough
install_package() {
  info "installing brainsolpi and its dependencies, this can take a few minutes on a pi 3"
  "$venv/bin/python" -m pip install --disable-pip-version-check --quiet -e "$repo"
  if ! "$venv/bin/brainsolpi" --help >/dev/null 2>&1; then
    fail "the brainsolpi command does not start, see: $venv/bin/brainsolpi --help"
  fi
  info "brainsolpi is installed in $venv"
}
