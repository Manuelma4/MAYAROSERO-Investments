# Hosting guide: running MAYAROSERO Investments all the time

The app is one Docker container: the engine, the API and the web app together. It has to run
continuously for alerts, the 5-minute scans and the monthly picks to work. The data lives in
`./data` (SQLite file and practice account), so backups are one folder.

## Option A: a computer at home (free)

Any always-on machine works: an old laptop, a mini PC, or a Raspberry Pi 4/5 with 4 GB+.

```
git clone https://github.com/Manuelma4/MAYAROSERO-Investments.git
cd MAYAROSERO-Investments
cp .env.example .env                       # then edit: see docs/ALERTS_SETUP.md and LATER.md
cp config/config.example.yaml config/config.yaml
docker compose up -d --build
```

Open http://localhost:8000 (or http://<the machine's IP>:8000 from your phone on the same Wi-Fi).
Phone: open it in the browser → Share / menu → Add to Home Screen. It installs like an app.

Pros: free, your data stays home. Cons: off when the machine or the internet box is off; reaching it
from outside home needs one of the remote options below.

## Option B: a small cloud server (about €4–6 / month)

A basic VPS with 2 vCPU and 4 GB RAM is enough. Examples: Hetzner Cloud, Scaleway, OVHcloud
(European, cheap) or DigitalOcean. Ubuntu 24.04 is fine.

1. Create the server, add your SSH key, log in: `ssh root@<server-ip>`.
2. Install Docker: `curl -fsSL https://get.docker.com | sh`.
3. Same commands as option A (clone, `.env`, `docker compose up -d --build`).
4. Set an access password before exposing it to the internet. In `.env`:

   ```
   TRADEBOT_API_TOKEN=<a long random string, e.g. from: openssl rand -hex 32>
   TRADEBOT_CORS=https://invest.your-domain.com
   ```

   Then paste the same token once in the app: Settings → Access. Live (real-money) trading refuses
   to start without a strong token.
5. HTTPS with your own domain: point a DNS record (e.g. `invest.your-domain.com`) to the server IP and
   put Caddy in front, which gets the certificate automatically. Add to `docker-compose.yml`:

   ```yaml
     caddy:
       image: caddy:2
       ports: ["80:80", "443:443"]
       command: caddy reverse-proxy --from invest.your-domain.com --to app:8000
       volumes: [caddy_data:/data]
       restart: unless-stopped
   volumes:
     caddy_data:
   ```

   and change the app's `ports: ["8000:8000"]` to `expose: ["8000"]` so it is only reachable through
   HTTPS. `docker compose up -d`.

Note: free Yahoo data can rate-limit busy cloud IP addresses. If prices stop updating on a server,
the paid feed in LATER.md (section 1) fixes it; at home this rarely happens.

## Reaching a home server from anywhere (free)

- Tailscale (simplest): install it on the home machine and on your phone, sign in on both, then open
  `http://<machine-name>:8000`. Private, no ports opened on your internet box.
- Cloudflare Tunnel: gives a public HTTPS address without opening ports; set `TRADEBOT_API_TOKEN` first.

## Day-to-day

| Task | Command |
|---|---|
| See logs | `docker compose logs -f app` |
| Update to the latest version | `git pull && docker compose up -d --build` |
| Restart after editing `.env` | `docker compose up -d --force-recreate` |
| Back up | copy the `data/` folder (and your `.env`) somewhere safe |
| Check alerts work | `docker compose exec app python scripts/test_alerts.py` |
| Check the paid data key | `docker compose exec app python -m tradebot.data.paid AAPL` |
| Emergency: close every position | Settings → Close everything (or stop the app: `docker compose stop`) |

The container restarts by itself after a crash or a reboot (`restart: unless-stopped`).

## Resources

The full S&P 500 scan uses about 1–2 GB of RAM and short CPU bursts every 5 minutes; the daily
predictions run is the heaviest job. 2 vCPU / 4 GB is comfortable; 1 GB machines are too small.
