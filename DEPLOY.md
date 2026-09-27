# Deployment — pendientes-bot

How this bot runs 24/7, and why each decision was made that way.
Deployed 2026-09-24 · verified 2026-09-27

## Where it runs

| | |
|---|---|
| Host | `davidagent` — ASUS VivoBook X412F, Ubuntu Server 26.04.1 LTS |
| User | `wabisabi` |
| Path | `/home/wabisabi/pendientes-bot` |
| Admin access | `ssh wabisabi@100.114.172.75` (Tailscale) or `192.168.1.52` (LAN) |
| Process manager | systemd **user** service `pendientes.service` |
| Timezone | `America/Bogota` (digest fires 08:30 local) |

The Mac is no longer a runtime. It is only where the code is edited.

## Why it needs no open ports

The bot uses **long polling**: it calls out to `api.telegram.org` and asks for new
messages. Telegram never initiates a connection to the server, so there is no port
forwarding, no public IP, no firewall rule, and no reverse proxy.

Tailscale is **only** the private network used to administer the box. The bot would
work with Tailscale switched off.

## Decisions and trade-offs

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| Process supervision | systemd | cron `@reboot`, tmux | A long-polling bot is a process that must never die, not a task that runs at a time. Cron starts things; systemd *keeps them alive*. Daimon legitimately stays on cron because it is a once-a-day script. |
| Service scope | **user** service (`~/.config/systemd/user/`) | system service (`/etc/systemd/system/`) | No `sudo` for daily restarts; the unit lives next to the code it runs; the bot reads `~/.env` and has no business running as a system daemon. Cost: needs `enable-linger`. |
| Survive logout | `loginctl enable-linger wabisabi` | — | Without it the user session only exists during SSH, so closing the terminal would kill the bot — the original problem in a new costume. |
| Container | none | Docker | V0 principle: minimum infrastructure. One Python process with 9 dependencies does not need an image layer. |
| venv | rebuilt on the server | copied from the Mac | `python-telegram-bot` pulls compiled wheels built per-platform. The recipe travels via git; the toolbox is built on site. |
| Secrets | `scp` by hand, `chmod 600` | committed / a secrets manager | `.env` is gitignored by design. Two users and one machine do not justify a vault. |
| Database | `scp`'d the live `pendientes.db` | fresh empty DB | 4 open and 28 resolved pendings were real state worth keeping. |
| `WorkingDirectory` | pinned in the unit | leave unset | `db.py` uses `DB_PATH = Path("pendientes.db")` — a **relative** path. Without this line systemd would create a new empty database elsewhere and the bot would look healthy while showing zero pendings. |
| `RestartSec=10` | 10 s | 0–1 s | Telegram queues undelivered updates ~24 h, so 10 s of downtime is invisible to users, while instant restarts would hammer the API during an outage. |
| Bot token | same token, Mac copy stopped | second dev bot | Telegram allows exactly **one** long-polling process per token. Two pollers produce `Conflict: terminated by other getUpdates request` and silently unreliable reminders. |

## The unit file

`~/.config/systemd/user/pendientes.service`

```ini
[Unit]
Description=Pendientes bot (Telegram)

[Service]
Type=simple
WorkingDirectory=/home/wabisabi/pendientes-bot
ExecStart=/home/wabisabi/pendientes-bot/.venv/bin/python3 bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

Notes:

- `ExecStart` calls the venv's python by absolute path. There is no `activate` anywhere —
  activating only reorders `PATH`, and systemd has no shell to do it in.
- `PYTHONUNBUFFERED=1` — without it Python buffers output when not attached to a terminal,
  so logs arrive in late silent chunks.
- No `After=network-online.target`: the restart loop *is* the network-readiness strategy.

## Operating it

Run from anywhere on the server — `WorkingDirectory` handles the path.

```bash
systemctl --user status pendientes          # is it alive
systemctl --user restart pendientes         # after a code change
systemctl --user stop pendientes            # frees the token for local dev
journalctl --user -u pendientes -f          # follow logs live
journalctl --user -u pendientes --since today
systemctl --user show pendientes -p NRestarts -p MainPID -p ExecMainStartTimestamp
```

## Shipping a change

Code is edited on the Mac, never on the server. The server only pulls.

```bash
# Mac
git add -A && git commit -m "..." && git push

# server
cd ~/pendientes-bot && git pull
systemctl --user restart pendientes
journalctl --user -u pendientes -n 20
```

If a dependency changed:

```bash
source .venv/bin/activate && pip install -r requirements.txt
```

## Verification record

| Test | Result |
|---|---|
| Continuous run | 3 days on one process (PID 66977, Sep 24 12:08 → Sep 27), `NRestarts=0` |
| Real-world | Daily digest delivered 08:30 on Sep 25, 26, 27; `/lista` answered from outside the home network with the Mac closed |
| Crash (`kill -9`) | PID 66977 → 122163 in under 12 s, `NRestarts=1`, stayed `active` |
| Reboot | Came back as PID 1606 with `Users logged in: 0` — linger confirmed |
| Sibling service | Daimon's 7am cron entry survived the reboot |

## Known weaknesses

1. **The bot is nearly silent.** In three days it logged only two lines, both at startup.
   Nothing is written when a pending is saved, resolved, or when the digest fires — so the
   logs can prove the *process* was alive but not that it did its *job*. Only Telegram can.
   Biggest gap; fix first.
2. **No error handler registered.** `python-telegram-bot` warns `No error handlers are
   registered`, so a 2-second network blip dumps a full traceback. Adding one turns each
   blip into a single readable line.
3. **DNS drops at night.** Six `Temporary failure in name resolution` (errno -3) events
   between Sep 24–26, mostly 20:00–05:00 — likely WiFi power-saving on the Intel card or
   router lease renewal. The library's internal retry loop absorbed all of them (the
   process never died), so this is cosmetic until proven otherwise.
4. **No DB backup.** `pendientes.db` exists in exactly one place. A `sqlite3 .backup`
   on a timer is the cheap fix.
5. **23 pending OS updates** on the host as of Sep 27.
