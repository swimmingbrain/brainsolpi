#!/usr/bin/env bash
# sets up brainsol on a raspberry pi with raspberry pi os bookworm or newer
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
sudo -v

step "installing system packages"
packages="python3 python3-venv avrdude git"
missing=""
for p in $packages; do
  if ! dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed"; then
    missing="$missing $p"
  fi
done
if [ -n "$missing" ]; then
  info "installing:$missing"
  sudo apt-get update
  # shellcheck disable=SC2086
  sudo apt-get install -y $missing
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

step "giving $(id -un) access to the serial port"
if id -nG "$(id -un)" | tr ' ' '\n' | grep -qx dialout; then
  info "already in the dialout group"
else
  sudo usermod -aG dialout "$(id -un)"
  info "added to the dialout group, the service has it at once, a terminal after the next login"
fi

step "installing the service"
install_unit
sudo systemctl enable --quiet brainsolpi.service
info "brainsolpi starts at boot"

step "allowing the service to restart itself, reboot and power off without a password"
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
# nothing else runs without a password
Cmnd_Alias BRAINSOLPI_CMDS = $systemctl_path reboot, $systemctl_path poweroff, $systemctl_path restart brainsolpi, $systemctl_path restart brainsolpi.service
$user ALL=(root) NOPASSWD: BRAINSOLPI_CMDS
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
