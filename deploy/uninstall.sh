#!/usr/bin/env bash
# removes what deploy/install.sh set up: the service, the sudo rules and, if you want, the venv.
# settings and data stay unless you say otherwise
#
# usage: cd ~/brainsolpi && deploy/uninstall.sh
set -euo pipefail

# shellcheck source=deploy/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ "$(id -u)" = 0 ]; then
  fail "run this as your normal user, not with sudo"
fi
sudo -v

step "service"
if [ -f "$unit_file" ]; then
  sudo systemctl disable --now --quiet brainsolpi.service || true
  sudo rm -f "$unit_file"
  sudo systemctl daemon-reload
  sudo systemctl reset-failed brainsolpi.service 2>/dev/null || true
  info "stopped, disabled and removed"
else
  info "no service installed"
fi

step "sudo rules"
# sudoers.d is not readable for normal users, so even the test needs sudo
if sudo test -e "$sudoers_file"; then
  sudo rm -f "$sudoers_file"
  info "removed $sudoers_file"
else
  info "none installed"
fi

step "python environment"
case "$venv" in
  */.venv) ;;
  *) fail "unexpected venv path $venv, nothing deleted" ;;
esac
if [ -d "$venv" ]; then
  if ask "delete the venv in $venv?" y; then
    rm -rf "$venv"
    info "deleted"
  else
    info "kept"
  fi
else
  info "no venv"
fi

step "settings and data"
for dir in "$HOME/.config/brainsolpi" "$HOME/.local/share/brainsolpi"; do
  if [ -d "$dir" ]; then
    if ask "delete $dir? the pin, the settings, the calibration and the recordings live there" n; then
      rm -rf "$dir"
      info "deleted $dir"
    else
      info "kept $dir"
    fi
  fi
done

step "left as they are"
info "the apt packages python3-venv, avrdude and git"
info "the dialout group membership, remove it with: sudo gpasswd -d $(id -un) dialout"
info "the host name $(hostname), change it with: sudo hostnamectl set-hostname <name>"
info "  and fix the 127.0.1.1 line in /etc/hosts to match"
info "the firmware on the uno and the repo itself"
info "a cloudflare tunnel or a tailscale funnel, deploy/tunnel.md says how to remove them"
