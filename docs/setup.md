# Setting up the Pi

From a blank SD card to the tracker service running on the Raspberry Pi 3B+. It takes about half an hour,
most of it waiting. You only need the Pi, its power supply and a computer with an SD card reader. The kit
can come later: without a board the service runs the simulation.

## 1. Write the SD card

Install the Raspberry Pi Imager from raspberrypi.com on your computer and start it.

1. Device: Raspberry Pi 3.
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

Once the repo is on GitHub, clone it:

```
sudo apt update
sudo apt install -y git
git clone https://github.com/swimmingbrain/brainsolpi.git
```

Until then, copy it from your computer. In the repo folder on your computer:

```
git archive --format=tar.gz --prefix=brainsolpi/ -o brainsolpi.tar.gz HEAD
scp brainsolpi.tar.gz <user>@brainsol.local:
```

and on the Pi:

```
tar -xzf brainsolpi.tar.gz
```

Either way the repo ends up in `~/brainsolpi`. The path must not contain spaces.

## 4. Install

```
cd ~/brainsolpi
deploy/install.sh
```

Run it as your normal user, it asks for sudo where it needs it. Running it again later is safe. It walks
through these steps and prints each one:

1. checks the system and installs `python3-venv`, `avrdude` and `git`
2. puts brainsolpi and its libraries into `~/brainsolpi/.venv`, this takes a few minutes on a Pi 3
3. links the `brainsolpi` command into `~/.local/bin`
4. adds you to the `dialout` group, so you may use the serial port
5. installs and enables the `brainsolpi` service, it starts at every boot
6. writes sudo rules, so the admin tools can restart the service, reboot and power off the Pi, and the
   commands `flash`, `doctor` and `centre` can stop and start the service, all without a password
7. offers to rename the Pi to `brainsol` if it has another name
8. asks for the admin pin when none is set yet, 4 to 32 characters, you need it to unlock the admin tools
9. offers to flash the bridge firmware when a board is plugged in
10. downloads the web app into `~/brainsolpi/web`, so the Pi serves the page itself
11. starts the service and checks the power supply

What you should see at the end:

```
done, open one of these addresses in a browser
  http://brainsol.local:8080
  http://192.168.1.50:8080
```

Open one of them on a computer or phone in the same network. The page shows the 3D twin of the tracker.
The chip in the top bar says Live, and in the System tab of the admin tools the driver is simulation as long
as no board is plugged in.

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
restarts with the real board. A board without the firmware is left alone, flash it with `brainsolpi flash`.
`docs/first-start.md` goes through that day step by step.

On any other computer you can run the whole tracker simulated with `uv run brainsolpi demo`, see the readme.

## The hosted page

`https://sol.swimmingbrain.dev` is the same web app on GitHub Pages. It reaches the Pi only through an
https address, the browser blocks the plain address of the Pi on an https page. `deploy/tunnel.md` sets up a
Cloudflare Tunnel or a Tailscale Funnel for that.

## Updating

```
cd ~/brainsolpi
deploy/update.sh
```

It pulls the new version, installs it, refreshes the web app and restarts the service. When the bridge
firmware changed it says so, then run `brainsolpi flash`. A copy without git is updated by copying the new
version over it and running `deploy/install.sh` again.

## Where things live

| what | where |
|---|---|
| settings: tuning, soft limits, site, panel size, calibration, pin hash | `~/.config/brainsolpi/settings.json` |
| state: last pose, mode, admin sessions | `~/.config/brainsolpi/state.json` |
| experiment results | `~/.local/share/brainsolpi/experiments/` |
| recordings | `~/.local/share/brainsolpi/recordings/` |
| the web app served by the Pi | `~/brainsolpi/web/` |
| the service | `/etc/systemd/system/brainsolpi.service` |
| the sudo rules | `/etc/sudoers.d/brainsolpi` |

Useful commands:

```
systemctl status brainsolpi        is it running
journalctl -u brainsolpi -f        the live log, Ctrl+C ends it
sudo systemctl restart brainsolpi  start it again
brainsolpi setpin                  a new admin pin
brainsolpi doctor                  check the board, sensors and servos
```

The service writes the settings file while it runs, so stop it before you edit the file by hand.
`deploy/uninstall.sh` removes the service, the sudo rules and the command link, and asks before it deletes the
venv, the settings and the data.
