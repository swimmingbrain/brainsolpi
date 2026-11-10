# Reaching the Pi from the public page

The web app lives at `https://sol.swimmingbrain.dev` on GitHub Pages. To show the real tracker
instead of the simulation it needs a connection to the `brainsolpi` service on the Pi, which
listens on port 8080 (HTTP for `/api` and a WebSocket on `/ws`). This page shows three ways to get
there, from the best one for the talk to the simplest one.

| way | address for the app | needs |
|---|---|---|
| Cloudflare Tunnel | `solpi.swimmingbrain.dev` | the Cloudflare account that holds the `swimmingbrain.dev` DNS |
| Tailscale Funnel | `brainsol.<tailnet>.ts.net` | a free Tailscale account, no DNS changes |
| same network only | open `http://brainsol.local:8080` directly | nothing |

## Why the public page cannot just use the IP address

The public page is loaded over https. A page that came over https may only open secure
connections, that means `https://` and `wss://`. An address like `ws://192.168.1.50:8080` is not
secure, so the browser blocks the connection before it even leaves the laptop. This is called
mixed content, and no setting in the page can allow it. A bare IP address in the home network also
cannot get a normal https certificate.

So the Pi needs a real name with a real certificate in front of it. A tunnel gives exactly that:
the browser talks https and wss to Cloudflare or Tailscale, and they pass the traffic through an
outgoing connection from the Pi to port 8080. No port on the router has to be opened, and it also
works on a guest network or a phone hotspot at the venue.

In the app, an address without a scheme means `wss://` on the https page. So after the setup
below, open:

```
https://sol.swimmingbrain.dev/?pi=solpi.swimmingbrain.dev
```

## Way 1: Cloudflare Tunnel (the main path)

The domain `swimmingbrain.dev` already has its DNS at Cloudflare, so a named tunnel can put the Pi
at `solpi.swimmingbrain.dev`. Cloudflare passes WebSockets through a tunnel on every plan without
extra settings.

All commands run on the Pi as your normal user unless they say `sudo`.

### 1. Install cloudflared

From the Cloudflare package repository, as given in the Cloudflare docs:

```
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install cloudflared
```

Check it with `cloudflared --version`.

### 2. Log in and create the tunnel

```
cloudflared tunnel login
```

On a Pi without a screen this prints a link. Open it on any computer, log in to Cloudflare and
pick `swimmingbrain.dev`. The Pi then gets `~/.cloudflared/cert.pem`.

```
cloudflared tunnel create brainsol
```

This prints the tunnel id (a long UUID) and writes the secret of the tunnel to
`~/.cloudflared/<tunnel id>.json`. `cloudflared tunnel list` shows it again later.

### 3. Write the config

```
cp deploy/cloudflared.yml ~/.cloudflared/config.yml
nano ~/.cloudflared/config.yml
```

Put the tunnel id in both places that say `TUNNEL_ID` and your user name where it says `USER`.
The rules send `solpi.swimmingbrain.dev` to `http://localhost:8080` and answer everything else
with 404. Check the file:

```
cloudflared tunnel ingress validate
cloudflared tunnel ingress rule https://solpi.swimmingbrain.dev
```

### 4. Point the name at the tunnel

```
cloudflared tunnel route dns brainsol solpi.swimmingbrain.dev
```

This adds a CNAME record for `solpi` in the Cloudflare DNS that points to the tunnel.

### 5. Try it by hand

```
cloudflared tunnel run brainsol
```

Leave it running and open `https://solpi.swimmingbrain.dev/healthz` on your phone (mobile data,
not the home network, makes it a real test). It should say `ok`. Stop the tunnel with Ctrl+C.

### 6. Run it as a service

```
sudo cloudflared --config /home/$USER/.cloudflared/config.yml service install
systemctl status cloudflared
```

The service install copies the config to `/etc/cloudflared/config.yml`, creates the
`cloudflared` systemd service, enables it and starts it. From now on the tunnel comes up at every
boot, before or after the tracker, it does not matter. To change the config later, edit
`/etc/cloudflared/config.yml` and run `sudo systemctl restart cloudflared`.

### 7. Use it

Open `https://sol.swimmingbrain.dev/?pi=solpi.swimmingbrain.dev`. The source chip in the top bar
switches to live. The app remembers the address, so the next visit connects by itself.

If the page stays on the simulation: check that the WebSockets switch in the Cloudflare dashboard
(the Network page of `swimmingbrain.dev`) is on, and look at `journalctl -u cloudflared -n 50` and
`journalctl -u brainsolpi -n 50` on the Pi.

### Removing it

```
sudo cloudflared service uninstall
cloudflared tunnel delete brainsol
```

Then delete the `solpi` CNAME record in the Cloudflare dashboard.

## Way 2: Tailscale Funnel (no DNS work)

Funnel publishes a port of the Pi on the internet under a name of your tailnet, with a
certificate that Tailscale takes care of. It needs a free Tailscale account but no change to the
DNS of `swimmingbrain.dev`.

```
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

`tailscale up` prints a link, open it and log in. Then publish the tracker:

```
sudo tailscale funnel --bg 8080
```

Funnel needs HTTPS certificates, MagicDNS and the funnel attribute in the access policy of the
tailnet. When something is missing the first time, the command says so and prints a link to allow
it, and the command line sets up the certificates and the policy for you. With `--bg` the funnel
stays on, also after a reboot. It answers at
`https://brainsol.<tailnet>.ts.net` on port 443 and passes everything, WebSockets included, to
`http://127.0.0.1:8080`. Funnel can only listen on the ports 443, 8443 and 10000, so the public
address has no `:8080` in it.

```
tailscale funnel status
```

shows the exact address. In the app open
`https://sol.swimmingbrain.dev/?pi=brainsol.<tailnet>.ts.net` with your own tailnet name.

From now on the tracker is on the internet whenever the service runs, also right after a boot. The live
view is meant to be public, the admin tools are not: set the pin with `brainsolpi setpin` first. Without a
pin nobody can unlock them at all.

To switch it off again: `sudo tailscale funnel reset`.

## Way 3: same network only

When the laptop or phone is in the same network as the Pi, skip the public page and open the page
that the Pi serves itself:

```
http://brainsol.local:8080
```

The Pi serves this page from `web/` in the repo. `deploy/install.sh` and `deploy/update.sh` download the
built web app there, `deploy/web.sh` does it by hand, also from a `site.zip` you copied over. Without it the
address shows a short text page.

This page is plain http, so it may talk to the Pi with `ws://` and nothing gets blocked. If
`brainsol.local` does not resolve (some Android phones do not support `.local` names), use the IP
address that `deploy/install.sh` printed at the end, or find it with `hostname -I` on the Pi:
`http://192.168.1.50:8080` for example.

Do not put such an address into the public https page, that is exactly the mixed content case
from above.

## Official docs

- Cloudflare, create a locally managed tunnel:
  https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/local-management/create-local-tunnel/
- Cloudflare, configuration file and ingress rules:
  https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/
- Cloudflare, run the tunnel as a Linux service:
  https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/linux/
- Cloudflare, cloudflared downloads and the package repository:
  https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/ and https://pkg.cloudflare.com/
- Cloudflare, WebSockets: https://developers.cloudflare.com/network/websockets/
- Tailscale, install on Linux: https://tailscale.com/kb/1031/install-linux
- Tailscale Funnel: https://tailscale.com/kb/1223/funnel
- Tailscale, the `tailscale funnel` command: https://tailscale.com/kb/1311/tailscale-funnel
- MDN, mixed content: https://developer.mozilla.org/en-US/docs/Web/Security/Mixed_content
