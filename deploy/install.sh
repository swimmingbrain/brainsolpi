#!/usr/bin/env bash
# sets up brainsol on a raspberry pi 3b+ or 4 with raspberry pi os bookworm or newer, it ran first on trixie
#
# run it once from the cloned repo as your normal user, it calls sudo where it needs to:
#   cd ~/brainsolpi && deploy/install.sh
# running it again is safe, every step looks at what is already there first
set -euo pipefail

# shellcheck source=deploy/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

step "checking the system"
if [ "$(id -u)" = 0 ]; then
  fail "run this as your normal user, not with sudo. the service runs as the user who installs it"
fi
command -v apt-get >/dev/null 2>&1 || fail "this script needs a debian based system like raspberry pi os"
command -v sudo >/dev/null 2>&1 || fail "sudo is missing"
command -v systemctl >/dev/null 2>&1 || fail "systemd is missing"
case "$repo" in
  *[[:space:]]*) fail "the repo path has a space in it, move the repo to a path without spaces: $repo" ;;
esac
[ -f "$repo/pyproject.toml" ] || fail "no pyproject.toml in $repo, run the script from inside the cloned repo"
info "repo: $repo"
info "user: $(id -un)"
# ask for the password once up front, so the questions later are not mixed with sudo prompts
need_sudo "the install"

step "installing system packages"
packages="python3 python3-venv avrdude git"
missing=""
for p in $packages; do
  if ! dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep "install ok installed" >/dev/null; then
    missing="$missing $p"
  fi
done
if [ -n "$missing" ]; then
  info "installing:$missing"
  sudo apt-get update
  # none of these packages asks anything, and without a terminal debconf would complain about
  # every frontend it tries
  # shellcheck disable=SC2086
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y $missing
else
  info "all there: $packages"
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  fail "brainsolpi needs python 3.11 or newer, this system has $(python3 --version 2>&1)"
fi

step "setting up the python environment"
# pip on raspberry pi os refuses to touch the system python, so everything goes into a venv
if [ ! -x "$venv/bin/python" ]; then
  python3 -m venv "$venv"
  info "created $venv"
else
  info "using $venv"
fi
install_package

step "putting the brainsolpi command on the path"
if [ -e "$command_link" ] && [ ! -L "$command_link" ]; then
  warn "$command_link is a file of something else, left alone. use $venv/bin/brainsolpi instead"
else
  mkdir -p "$(dirname "$command_link")"
  ln -sfn "$venv/bin/brainsolpi" "$command_link"
  info "linked $command_link, after the next login brainsolpi works as a command"
fi

step "giving $(id -un) access to the serial port"
if in_group_saved dialout; then
  info "already in the dialout group"
else
  sudo usermod -aG dialout "$(id -un)"
  info "added to the dialout group, the service has it at once, a terminal after the next login"
fi

step "installing the service"
install_unit
sudo systemctl enable --quiet brainsolpi.service
info "brainsolpi starts at boot"

step "allowing restart, stop and start of the service, reboot and power off without a password"
user="$(id -un)"
case "$user" in
  [![:lower:]_]* | *[![:lower:][:digit:]_-]*)
    fail "the user name $user has unusual characters, write $sudoers_file by hand"
    ;;
esac
systemctl_path="$(command -v systemctl)"
rules="$(mktemp)"
cat >"$rules" <<RULES
# written by deploy/install.sh of brainsol, removed by deploy/uninstall.sh
# the admin panel may restart the tracker service, reboot or power off the pi.
# brainsolpi flash, doctor and centre and firmware/flash.sh stop the service while they
# need the board and start it again. nothing else runs without a password
Cmnd_Alias BRAINSOLPI_POWER = $systemctl_path reboot, $systemctl_path poweroff
Cmnd_Alias BRAINSOLPI_UNIT = $systemctl_path restart brainsolpi, $systemctl_path restart brainsolpi.service, $systemctl_path stop brainsolpi, $systemctl_path stop brainsolpi.service, $systemctl_path start brainsolpi, $systemctl_path start brainsolpi.service
$user ALL=(root) NOPASSWD: BRAINSOLPI_POWER, BRAINSOLPI_UNIT
RULES
# a broken file in sudoers.d can lock sudo for everyone, so the new rules are checked
# before they go live. the staging name has a dot in it, sudo never reads such files
staging="$(sudo mktemp /etc/sudoers.d/.brainsolpi.XXXXXX)"
sudo install -m 0440 -o root -g root "$rules" "$staging"
rm -f "$rules"
if ! sudo visudo -c -f "$staging"; then
  sudo rm -f "$staging"
  fail "the sudo rules did not pass visudo -c, nothing was changed"
fi
if sudo cmp -s "$staging" "$sudoers_file"; then
  sudo rm -f "$staging"
  info "the sudo rules are up to date"
else
  sudo mv -f "$staging" "$sudoers_file"
  info "installed $sudoers_file"
fi
# the whole configuration must still be fine, else our file goes again
if ! sudo visudo -c >/dev/null; then
  sudo rm -f "$sudoers_file"
  fail "sudo did not accept the new rules, $sudoers_file was removed again"
fi

step "network name"
old_name="$(hostname)"
if [ "$old_name" = brainsol ]; then
  info "the pi is already called brainsol, it answers at brainsol.local"
elif ask "rename this pi from $old_name to brainsol, so it answers at brainsol.local?" y; then
  # both names on the local line first, so sudo can resolve the name at every moment
  if grep -q '^127\.0\.1\.1' /etc/hosts; then
    sudo sed -i "s/^127\.0\.1\.1.*/127.0.1.1\tbrainsol $old_name/" /etc/hosts
  else
    printf '127.0.1.1\tbrainsol %s\n' "$old_name" | sudo tee -a /etc/hosts >/dev/null
  fi
  sudo hostnamectl set-hostname brainsol
  sudo sed -i 's/^127\.0\.1\.1.*/127.0.1.1\tbrainsol/' /etc/hosts
  # newer images set the name with cloud-init at boot, this tells it to keep ours
  if [ -d /etc/cloud/cloud.cfg.d ]; then
    printf '# written by deploy/install.sh of brainsol, keeps the host name brainsol\npreserve_hostname: true\n' |
      sudo tee /etc/cloud/cloud.cfg.d/99-brainsol-hostname.cfg >/dev/null
  fi
  # avahi announces the .local name in the network
  if systemctl is-active --quiet avahi-daemon; then
    sudo systemctl restart avahi-daemon
  fi
  info "renamed to brainsol, after the next reboot every program uses the new name"
else
  info "keeping the name $old_name, it answers at $old_name.local"
fi
if ! systemctl is-active --quiet avahi-daemon; then
  warn "avahi-daemon does not run, so .local names will not work. install it with: sudo apt install avahi-daemon"
fi

step "admin pin"
# the package itself knows whether a pin is stored, a config folder alone says nothing
if "$venv/bin/brainsolpi" setpin --check >/dev/null 2>&1; then
  has_pin=1
else
  has_pin=0
fi
if [ ! -t 0 ]; then
  if [ "$has_pin" = 1 ]; then
    info "an admin pin is set, change it later with: $venv/bin/brainsolpi setpin"
  else
    info "no terminal to type into, set the pin later with: $venv/bin/brainsolpi setpin"
  fi
else
  if [ "$has_pin" = 1 ]; then
    question="an admin pin is set. change it?"
    default=n
  else
    question="no admin pin is set yet. set it now?"
    default=y
  fi
  if ask "$question" "$default"; then
    if ! "$venv/bin/brainsolpi" setpin; then
      warn "the pin was not set, do it later with: $venv/bin/brainsolpi setpin"
    fi
  else
    info "pin unchanged"
  fi
fi

step "bridge firmware"
if port="$(find_board_port)"; then
  info "found a board on $port"
  if ask "flash the bridge firmware to it now?" y; then
    if in_group_now dialout; then
      "$repo/firmware/flash.sh" "$port" || warn "flashing failed, try again later with: firmware/flash.sh"
    else
      # this login does not have the dialout group yet, sg lends it to one command
      sg dialout -c "$(printf '%q ' "$repo/firmware/flash.sh" "$port")" ||
        warn "flashing failed, try again later with: firmware/flash.sh"
    fi
  else
    info "not flashed, do it later with: firmware/flash.sh"
  fi
else
  info "no board plugged in. plug the uno in later and run: firmware/flash.sh"
fi

step "web app"
install_web

step "starting the service"
sudo systemctl restart brainsolpi.service
# give it a moment, a crash right at the start shows up as not active
sleep 3
if systemctl is-active --quiet brainsolpi.service; then
  info "brainsolpi is running"
else
  warn "brainsolpi does not run, look at the log: journalctl -u brainsolpi -n 50"
fi

step "power supply"
check_power

step "done, open one of these addresses in a browser"
name="$(hostname)"
info "http://$name.local:$http_port"
for ip in $(hostname -I 2>/dev/null || true); do
  case "$ip" in
    *:*) ;;
    *) info "http://$ip:$http_port" ;;
  esac
done
if [ ! -f "$repo/web/index.html" ]; then
  info "without the web app these show a short text page, deploy/web.sh puts the app in place"
fi
info ""
info "the public page https://sol.swimmingbrain.dev needs a tunnel to reach the pi, see deploy/tunnel.md"
info "live log of the service: journalctl -u brainsolpi -f"
if ! "$venv/bin/brainsolpi" setpin --check >/dev/null 2>&1; then
  info "no admin pin yet, the admin tools stay locked for everyone until you run: $venv/bin/brainsolpi setpin"
fi
if ! in_group_now dialout; then
  info "log out and in once, then your own terminal may use the serial port too"
fi
case ":$PATH:" in
  *":$(dirname "$command_link"):"*) ;;
  *) info "after the next login brainsolpi works as a command, until then use $venv/bin/brainsolpi" ;;
esac
