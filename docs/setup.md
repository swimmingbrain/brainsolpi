# Setting up the Pi

From a blank SD card to the tracker service running on a Raspberry Pi 3B+ or a Raspberry Pi 4. It takes
about half an hour, most of it waiting. You only need the Pi, its power supply and a computer with an SD
card reader. The kit can come later: without a board the service runs the simulation.

The supply matters more than it seems, the Pi powers the UNO and both servos through USB later. A Pi 3B+
takes the official 5.1 V 2.5 A micro USB supply, a Pi 4 the official 5.1 V 3 A USB C supply, or a better one.

The first real install ran on a Pi 3B+ with Raspberry Pi OS Lite 64 bit on the trixie release (Debian 13,
Python 3.13). Bookworm with Python 3.11 works the same way.

## 1. Write the SD card

Install the Raspberry Pi Imager from raspberrypi.com on your computer and start it.

1. Device: Raspberry Pi 3 or Raspberry Pi 4, the one you have.
2. Operating system: Raspberry Pi OS (other), then Raspberry Pi OS Lite (64 bit). Lite has no desktop, the
   Pi runs without a screen.
3. Storage: the SD card.
4. Customisation, say yes when the Imager offers it:
   - host name `brainsol`, so the Pi answers at `brainsol.local`
   - a user name and a password, you log in with them
   - the WiFi: network name, password and your country
   - time zone and keyboard layout
   - SSH on, with password login (or your public key if you have one)
5. Write, then put the card into the Pi and plug in the power supply.

The first boot takes a few minutes, the Pi grows the file system and joins the WiFi.

## 2. Log in

On your computer, in a terminal (PowerShell on Windows, Terminal on macOS and Linux):

```
ssh <user>@brainsol.local
```

Answer `yes` to the question about the fingerprint and type the password. If `brainsol.local` is not found,
look up the IP address of the Pi in your router and use `ssh <user>@<ip>` instead.

## 3. Get the repo onto the Pi

Clone it into your home folder, right where the login puts you:

```
sudo apt update
sudo apt install -y git
git clone https://github.com/swimmingbrain/brainsolpi.git
```

Lite comes without git, so the first two lines are needed. If the Pi cannot reach GitHub, copy the repo
from your computer instead. In the repo folder on your computer:

```
git archive --format=tar.gz --prefix=brainsolpi/ -o brainsolpi.tar.gz HEAD
scp brainsolpi.tar.gz <user>@brainsol.local:
```

and on the Pi:

```
tar -xzf brainsolpi.tar.gz
```

Either way the repo ends up in `~/brainsolpi`. The path must not contain spaces. A copy without git cannot
use `deploy/update.sh` later, see Updating below.

## 4. Install

```
cd ~/brainsolpi
deploy/install.sh
```

Run it as your normal user, it asks for sudo where it needs it. Running it again later is safe. On a Pi 3B+
with a good network it takes about two minutes, most of it for the Python libraries. It walks through these
steps and prints each one:

1. checks the system and installs `python3-venv`, `avrdude` and `git`
2. puts brainsolpi and its libraries into `~/brainsolpi/.venv`
3. links the `brainsolpi` command into `~/.local/bin`
4. adds you to the `dialout` group, so you may use the serial port
5. installs and enables the `brainsolpi` service, it starts at every boot, also when nobody logs in
6. writes sudo rules, so the admin tools can restart the service, reboot and power off the Pi, and the
   commands `flash`, `doctor` and `centre` can stop and start the service, all without a password
7. offers to rename the Pi to `brainsol` if it has another name
8. asks for the admin pin when none is set yet, 4 to 32 characters, you need it to unlock the admin tools
9. offers to flash the bridge firmware when a board is plugged in
10. downloads the web app into `~/brainsolpi/web`, so the Pi serves the page itself
11. starts the service and checks the power supply

The questions in steps 7 to 9 need a terminal, and so does sudo when it wants your password. Without a
terminal, for example when you start the script with
`ssh <user>@brainsol.local 'cd brainsolpi && deploy/install.sh'`, it only runs if sudo needs no password,
otherwise it stops right at the start and says so. When it runs, it takes the safe answer to every question
and goes on: the name stays, nothing is flashed and no pin is set. Set the pin afterwards:

```
~/brainsolpi/.venv/bin/brainsolpi setpin
```

What you should see at the end:

```
done, open one of these addresses in a browser
  http://brainsol.local:8080
  http://192.168.1.50:8080
```

Open one of them on a computer or phone in the same network. The page shows the 3D twin of the tracker.
The chip in the top bar says Live, and in the System tab of the admin tools the driver is simulation as long
as no board is plugged in. With a tunnel there is one more address, a Tailscale address for example, that
is fine.

Until a pin is set, nobody can unlock the admin tools, not even with a token from an earlier pin. The end of
the install says so. Everything else, the live view and the numbers, is open to everyone who has the
address.

Log out and in once after the install, then `brainsolpi` works as a command and your own terminal may use
the serial port.

If the web app could not be downloaded, the install goes on and says so. The site may not be published yet
or the Pi may be offline. The tracker runs anyway, add the page later with `deploy/web.sh`, or copy a
`site.zip` of the web app to the Pi and run `deploy/web.sh site.zip`. Until then the address shows a short
text page.

## Try it today with only the Pi

The service starts with `--driver auto`. It looks for a board for 6 s and runs the simulation when none
answers. Everything works on the simulated tracker: the live view, the admin tools, scans, experiments and
sun mode. Unlock the admin tools with the pin, then in the Control tab move the simulated light, or drag the
lamp in the 3D view.

While the simulation runs, the service looks for a board every 3 s. The day the kit arrives, plug the UNO in.
With the bridge firmware on it, the service notices it within a few seconds, says so in the event log and
restarts with the real board.

An UNO straight out of the kit still runs the code it came with and never answers. The service then writes
the bridge firmware to it by itself, with the same avrdude step as `brainsolpi flash`, and restarts with the
board. It only does that for a port that opened fine and stayed silent for several seconds, only for an UNO
R3 with the ATmega16U2 USB chip (USB ids `2341:0043`, `2a03:0043` or `2341:0243`, the Keyestudio board of the
kit is sold as one), once per plug in or start of the service, and never twice for a board it flashed before. A CH340 or FTDI
adapter is never touched, it can sit in front of anything. The event log and the journal say what happens.
The board then starts in hold with its servos off, nothing moves before you centre and calibrate.

To keep the service away from the UNO, stop the service, set `"autoflash": false` in the `serial` part of
`~/.config/brainsolpi/settings.json` and start it again. Then a silent UNO is only reported, flash it with
`brainsolpi flash`. `docs/first-start.md` goes through that day step by step.

On any other computer you can run the whole tracker simulated with `uv run brainsolpi demo`, see the readme.

## The hosted page

`https://sol.swimmingbrain.dev` is the same web app on GitHub Pages. It reaches the Pi only through an
https address, the browser blocks the plain address of the Pi on an https page. `deploy/tunnel.md` sets up a
Cloudflare Tunnel or a Tailscale Funnel for that. Then open
`https://sol.swimmingbrain.dev/?pi=brainsol.<tailnet>.ts.net` with your own address. With a tunnel the
tracker is on the internet as soon as the service runs, so set the admin pin before.

## Updating

```
cd ~/brainsolpi
deploy/update.sh
```

It pulls the new version, installs it, brings the service unit up to date, refreshes the web app and
restarts the service. It needs no password, the sudo rules of the install cover the restart. Only a new
service unit needs sudo with your password, then run it in a terminal. When the bridge firmware changed it says so, then run `brainsolpi flash`. The service
does not write a newer firmware to a board that already answers. A copy without git is updated by copying
the new version over it and running `deploy/install.sh` again.

## Where things live

| what | where |
|---|---|
| settings: tuning, soft limits, site, panel size, calibration, pin hash, `serial.autoflash` | `~/.config/brainsolpi/settings.json` |
| state: last pose of the head and of the sim, mode, admin sessions, the boards the service flashed | `~/.config/brainsolpi/state.json` |
| experiment results | `~/.local/share/brainsolpi/experiments/` |
| recordings | `~/.local/share/brainsolpi/recordings/` |
| the web app served by the Pi | `~/brainsolpi/web/` |
| the service | `/etc/systemd/system/brainsolpi.service` |
| the sudo rules | `/etc/sudoers.d/brainsolpi` |

Useful commands:

```
systemctl status brainsolpi           is it running
journalctl -u brainsolpi -f           the live log, Ctrl+C ends it
journalctl -u brainsolpi -p warning   only the warnings and errors
sudo systemctl restart brainsolpi     start it again
brainsolpi setpin                     a new admin pin
brainsolpi doctor                     check the board, sensors and servos
```

Raspberry Pi OS keeps the journal in memory to spare the SD card, so the log starts empty at every boot and
`journalctl -b -1` finds nothing of the boot before.

The service writes the settings file while it runs, so stop it before you edit the file by hand.
`deploy/uninstall.sh` removes the service, the sudo rules and the command link, and asks before it deletes the
venv, the settings and the data.
