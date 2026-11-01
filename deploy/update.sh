#!/usr/bin/env bash
# brings an installed brainsol up to date: git pull, reinstall the package, fetch the web app,
# restart the service
#
# usage: cd ~/brainsolpi && deploy/update.sh
set -euo pipefail

# shellcheck source=deploy/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# everything sits in a function, so bash has read the whole script before git pull
# may change this very file
main() {
  if [ "$(id -u)" = 0 ]; then
    fail "run this as your normal user, not with sudo"
  fi
  [ -x "$venv/bin/python" ] || fail "there is no venv in $venv, run deploy/install.sh first"

  step "fetching the new version"
  cd "$repo"
  local before
  local after
  before="$(git rev-parse HEAD)"
  git pull --ff-only || fail "git pull did not work, maybe there are local changes, see: git status"
  after="$(git rev-parse HEAD)"
  if [ "$before" = "$after" ]; then
    info "already up to date"
  else
    info "now at $(git log -1 --format='%h %s')"
  fi

  step "reinstalling the package"
  install_package

  step "checking the service unit"
  install_unit

  step "updating the web app"
  install_web

  step "restarting the service"
  sudo systemctl restart brainsolpi.service
  sleep 3
  if systemctl is-active --quiet brainsolpi.service; then
    info "brainsolpi is running"
  else
    warn "brainsolpi does not run, look at the log: journalctl -u brainsolpi -n 50"
  fi

  if [ "$before" != "$after" ] && ! git diff --quiet "$before" "$after" -- firmware/brainsol_bridge.hex; then
    step "the bridge firmware changed"
    info "flash it to the uno with: firmware/flash.sh"
  fi
}

main "$@"
