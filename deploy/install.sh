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
packages="python3 python3-venv python3-pip avrdude git"
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
