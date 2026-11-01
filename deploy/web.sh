#!/usr/bin/env bash
# puts the built brainsol web app into web/ in the repo, so the pi serves the page itself
#
# usage: deploy/web.sh                 downloads the site from sol.swimmingbrain.dev
#        deploy/web.sh site.zip        takes a zip you copied to the pi
#        deploy/web.sh path/to/build   takes a folder, the build/ of the brainsol repo for example
#        deploy/web.sh --url URL       downloads the zip from another address
#        deploy/web.sh --no-restart    leaves the service alone, the caller restarts it
# exit code 0 when the new copy is in place, 2 when the download failed, 1 for anything else.
# the old copy stays as it is until the new one passed every check
set -euo pipefail

# shellcheck source=deploy/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

default_url="https://sol.swimmingbrain.dev/site.zip"
url=""
source_path=""
restart=1

usage() {
  printf 'usage: deploy/web.sh [--url URL] [--no-restart] [site.zip | folder]\n' >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --url)
      [ "$#" -ge 2 ] || usage
      url="$2"
      shift 2
      ;;
    --no-restart)
      restart=0
      shift
      ;;
    -h | --help) usage ;;
    -*) usage ;;
    *)
      [ -z "$source_path" ] || usage
      source_path="$1"
      shift
      ;;
  esac
done
if [ -n "$url" ] && [ -n "$source_path" ]; then
  fail "give either --url or a zip or folder, not both"
fi

web_dir="$repo/web"
command -v python3 >/dev/null 2>&1 || fail "python3 is missing, it unpacks the zip"
if [ -e "$web_dir" ] && { [ -L "$web_dir" ] || [ ! -d "$web_dir" ]; }; then
  fail "$web_dir is not a plain folder, move it away first"
fi

# the new copy is built next to the old one, so the swap at the end is a rename on one disk
work="$(mktemp -d "$repo/.web-tmp.XXXXXX")"
cleanup() {
  rm -rf "$work"
}
trap cleanup EXIT
new="$work/new"
mkdir "$new"

unpack() {
  # python3 -I ignores the folder it runs in and the environment, the zip is not trusted
  python3 -I - "$1" "$new" <<'PY'
import os
import shutil
import stat
import sys
import zipfile

src, dest = sys.argv[1], sys.argv[2]
# a built brainsol site is a few megabytes, anything far bigger is not it
MAX_BYTES = 200 * 1024 * 1024
MAX_FILES = 20000

try:
    z = zipfile.ZipFile(src)
except (OSError, zipfile.BadZipFile) as e:
    sys.exit(f"not a zip file: {e}")
with z:
    infos = z.infolist()
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_BYTES:
        sys.exit("the zip is far too big for the web app")
    bad = z.testzip()
    if bad is not None:
        sys.exit(f"the zip is damaged at {bad}")
    files = []
    for i in infos:
        name = i.filename.replace("\\", "/")
        parts = [p for p in name.split("/") if p]
        if name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
            sys.exit(f"the zip holds an unsafe path: {name}")
        if stat.S_ISLNK(i.external_attr >> 16):
            sys.exit(f"the zip holds a link: {name}")
        if not i.is_dir() and parts:
            files.append((parts, i))
    # a zip of the build folder itself has that folder on top, its content is the site
    strip = 0
    tops = {parts[0] for parts, _ in files}
    if ["index.html"] not in [parts for parts, _ in files] and len(tops) == 1:
        strip = 1
    for parts, i in files:
        rel = parts[strip:]
        if not rel:
            continue
        out = os.path.join(dest, *rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with z.open(i) as r, open(out, "wb") as w:
            shutil.copyfileobj(r, w)
print(f"  files unpacked: {len(files)}")
PY
}

if [ -n "$source_path" ] && [ -d "$source_path" ]; then
  src_real="$(cd "$source_path" && pwd -P)"
  if [ -d "$web_dir" ] && [ "$src_real" = "$(cd "$web_dir" && pwd -P)" ]; then
    fail "$source_path is the web folder itself, give the folder of a new build"
  fi
  info "copying the web app from $src_real"
  cp -R "$src_real/." "$new/"
elif [ -n "$source_path" ]; then
  [ -f "$source_path" ] || fail "no such file or folder: $source_path"
  info "unpacking $source_path"
  unpack "$source_path" || fail "$source_path is not a usable zip of the web app"
else
  command -v curl >/dev/null 2>&1 || fail "curl is missing, install it with: sudo apt install curl"
  url="${url:-$default_url}"
  info "downloading $url"
  if ! curl -fsSL --retry 2 --connect-timeout 10 --max-time 300 -o "$work/site.zip" "$url"; then
    printf '  the download from %s did not work, the web folder is unchanged\n' "$url" >&2
    exit 2
  fi
  unpack "$work/site.zip" || fail "the download from $url is not a usable zip of the web app"
fi

# a page of some other site would load, but nothing would talk to the tracker
[ -f "$new/index.html" ] || fail "there is no index.html at the top of the new copy, that is not a built web app"
grep -qi brainsol "$new/index.html" || fail "the index.html of the new copy is not the brainsol web app"

# swap: the old copy moves aside first and comes back if the new one cannot take its place
old="$work/old"
if [ -d "$web_dir" ]; then
  mv "$web_dir" "$old"
fi
if ! mv "$new" "$web_dir"; then
  if [ -d "$old" ]; then
    mv "$old" "$web_dir"
  fi
  fail "could not move the new copy into $web_dir, the old one is back"
fi
info "the web app is in $web_dir"

# the service looks for the web folder when it starts, so a running one starts again
if [ "$restart" = 1 ] && command -v systemctl >/dev/null 2>&1 &&
  systemctl is-active --quiet brainsolpi.service 2>/dev/null; then
  info "restarting the brainsolpi service so it serves the new copy"
  sudo systemctl restart brainsolpi.service || warn "the restart did not work, run: sudo systemctl restart brainsolpi"
fi
info "open http://$(hostname).local:$http_port in a browser on the same network"
