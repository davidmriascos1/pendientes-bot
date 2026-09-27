# Deployment — pendientes-bot

How this bot runs 24/7, and why each decision was made that way.
Deployed 2026-09-24 · last updated 2026-09-27

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

### Infrastructure

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
| `RestartSec=10` | 10 s | 0–1 s | 10 s of downtime is invisible to users, while instant restarts would hammer the API during an outage. |
| Bot token | same token, Mac copy stopped | second dev bot | Telegram allows exactly **one** long-polling process per token. Proven on 2026-09-27: two pollers do not resolve cleanly — **both** get `Conflict` and both degrade, alternating, which from Telegram just looks like flakiness. |

### Observability and resilience (added 2026-09-27)

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| Logging | `logging` module → journald | `print`, a log file | `print` cannot carry a level or a logger name. journald already timestamps, rotates and is queryable by time — a file would mean writing rotation code. (Daimon uses a file only because cron has no journal integration.) |
| Log format | `"%(levelname)s %(name)s \| %(message)s"` | include a timestamp | journald stamps every line; adding one gives two dates per line. |
| `httpx` level | `WARNING` | leave at `INFO` | At `INFO` it logs every HTTP request — a line every few seconds, forever. apscheduler and `telegram.ext` stay at `INFO` because they only speak at startup, and their lines confirm the digest job was registered. |
| Log call style | `log.info("x %s", y)` | f-strings | The message is only formatted if that level is enabled. |
| What gets logged | pending created, resolved, already-resolved, digest sent, non-allowlisted sender | every message | One line per **state change**, not per event. The already-resolved branch is the race condition (two people tapping the same ✅) made visible. |
| Log position | **after** the `await` it reports | before | A line written before the send would claim success for a send that failed. A log that can lie is worse than no log. |
| Error handler | three branches by type | one catch-all | `Conflict` → `CRITICAL` (two pollers: the one operational error that silently ruins reliability). `NetworkError` → `WARNING` (the library retries by itself). Anything else → `ERROR` with traceback. |
| `BadRequest` excluded from the network branch | `isinstance(err, NetworkError) and not isinstance(err, BadRequest)` | match `NetworkError` alone | In python-telegram-bot `BadRequest` **subclasses** `NetworkError`, a historical quirk. Without the exclusion, a genuine bug (bad chat ID, over-length message) would be filed as "unstable network" and you would blame the router for days. |
| Digest retry | 3 attempts, 30 / 60 / 90 s | fail on first error, or retry forever | The observed DNS blips last seconds, so attempt 2 almost certainly wins. Worst case it gives up after ~3 min — a late digest, not a lost day. Growing gaps (backoff) because hammering a down network helps nobody. |
| `await asyncio.sleep` | asyncio | `time.sleep` | `time.sleep` freezes the whole process: for 90 s the bot would answer nothing. `asyncio.sleep` yields to the event loop. In async code any blocking call is a stalled bot. |
| `drop_pending_updates` | **`False`** | `True` (the original) | With `True`, messages sent while the bot restarts are **discarded** — the product's entire promise ("nothing gets forgotten") broken by its own deploy. With `False` they become pendings on startup. Replay is safe because `resolve_pending` is guarded by `AND state='OPEN'`. Cost: after a long outage, a batch of older items arrives at once — which for this product is the correct behaviour. |

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
systemctl --user show pendientes -p NRestarts -p MainPID -p ExecMainStartTimestamp
```

Reading logs:

```bash
journalctl --user -u pendientes -f              # live feed; Ctrl+C leaves the feed, not the bot
journalctl --user -u pendientes -n 20 --no-pager
journalctl --user -u pendientes --since today | grep -i digest
journalctl --user -u pendientes --since "2 days ago" | grep -iE "intento|NO enviado|red inestable|CRITICAL"
```

`-f` follows and never returns a prompt — that is not hanging. Without `--no-pager`,
`journalctl` opens a pager you quit with `q`, which is the other way it looks stuck.

## Shipping a change

Code is edited on the Mac, never on the server. The server only pulls.

```bash
# Mac
.venv/bin/python3 -m py_compile bot.py && echo "sintaxis OK"
git add -A && git commit -m "..." && git push

# server
cd ~/pendientes-bot && git pull
systemctl --user restart pendientes
journalctl --user -u pendientes -n 10 --no-pager
```

If a dependency changed: `source .venv/bin/activate && pip install -r requirements.txt`

`py_compile` parses the file without running it — no bot starts, no token used. It is the
only local test available now, since the server holds the token. It catches grammar, **not
meaning**: a deleted `import` line still compiles and then fails at runtime.

Amend commits freely before pushing, never after — a pushed commit may already be on the
server, and rewriting it forces a history the two sides disagree about.

## Verification record

| Test | Result |
|---|---|
| Continuous run | 3 days on one process (PID 66977, Sep 24 12:08 → Sep 27), `NRestarts=0`, through six DNS blips and one `Bad Gateway` |
| Real-world | Digest delivered 08:30 on Sep 25, 26, 27; `/lista` answered from outside the home network with the Mac closed |
| Crash (`kill -9`) | PID 66977 → 122163 in under 12 s, `NRestarts=1`, stayed `active` |
| Reboot | Came back as PID 1606 with `Users logged in: 0` — linger confirmed |
| Sibling service | Daimon's 7am cron entry survived the reboot |
| Logging (9a) | `pendiente #48 creado`, `#48 resuelto`, `digest enviado con 13 pendientes abiertos` — all four event types observed live |
| Error handler (9b) | Conflict forced deliberately by starting a second poller on the Mac: `CRITICAL` logged on **both** sides, 6 conflicts in 40 s |
| Digest retry (9c) | Success path proven via `/digest` (one message, one log line). The retry path itself is unproven — it needs a network failure at the exact moment of sending |

## Known weaknesses

1. **No DB backup.** `pendientes.db` exists in exactly one place, on a laptop with a dead
   keyboard. A `sqlite3 .backup` on a cron timer is the cheap fix. **Highest priority.**
2. **DNS drops at night.** Six `Temporary failure in name resolution` (errno -3) events
   Sep 24–26, mostly 20:00–05:00 — likely WiFi power-saving on the Intel card or router
   lease renewal. The library's internal retry loop absorbs them (the process never died)
   and the digest now retries, so this is monitored rather than fixed.
3. **The digest retry is unproven** in production. Grep for `intento` after the next blip.
4. **No SSH key** — every `ssh`/`scp` asks for a password, and a password prompt silently
   swallows anything pasted after it. `ssh-copy-id` fixes it.
5. **23 pending OS updates** on the host as of Sep 27.
