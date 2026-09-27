# Despliegue — pendientes-bot

Cómo corre este bot 24/7, y por qué cada decisión se tomó así.
Desplegado 2026-09-24 · última actualización 2026-09-27

## Dónde corre

| | |
|---|---|
| Host | `davidagent` — ASUS VivoBook X412F, Ubuntu Server 26.04.1 LTS |
| Usuario | `wabisabi` |
| Ruta | `/home/wabisabi/pendientes-bot` |
| Acceso admin | `ssh wabisabi@100.114.172.75` (Tailscale) o `192.168.1.52` (LAN) |
| Gestor de procesos | servicio systemd de **usuario** `pendientes.service` |
| Zona horaria | `America/Bogota` (el digest sale 08:30 local) |

El Mac ya no es un entorno de ejecución. Solo es donde se edita el código.

## Por qué no necesita puertos abiertos

El bot usa **long polling**: él llama a `api.telegram.org` y pregunta si hay mensajes
nuevos. Telegram nunca inicia una conexión hacia el servidor, así que no hay port
forwarding, ni IP pública, ni regla de firewall, ni reverse proxy.

Tailscale es **solo** la red privada para administrar la máquina. El bot funcionaría
con Tailscale apagado.

## Decisiones y trade-offs

### Infraestructura

| Decisión | Elegido | Descartado | Por qué |
|---|---|---|---|
| Supervisión del proceso | systemd | cron `@reboot`, tmux | Un bot en long polling es un proceso que no debe morir nunca, no una tarea que corre a una hora. Cron *arranca* cosas; systemd las *mantiene vivas*. Daimon sigue en cron con razón: es un script de una vez al día. |
| Alcance del servicio | servicio de **usuario** (`~/.config/systemd/user/`) | servicio de sistema (`/etc/systemd/system/`) | Sin `sudo` para reiniciar a diario; la unidad vive junto al código que ejecuta; el bot lee `~/.env` y no tiene por qué correr como demonio del sistema. Costo: requiere `enable-linger`. |
| Sobrevivir al logout | `loginctl enable-linger wabisabi` | — | Sin esto la sesión del usuario solo existe durante el SSH, así que cerrar la terminal mataría al bot — el problema original con otro disfraz. |
| Contenedor | ninguno | Docker | Principio del V0: mínima infraestructura. Un proceso Python con 9 dependencias no necesita una capa de imagen. |
| venv | reconstruido en el servidor | copiado del Mac | `python-telegram-bot` trae wheels compilados por plataforma. La receta viaja por git; la caja de herramientas se arma en el sitio. |
| Secretos | `scp` a mano, `chmod 600` | commit / gestor de secretos | `.env` está en `.gitignore` por diseño. Dos usuarios y una máquina no justifican una bóveda. |
| Base de datos | `scp` del `pendientes.db` real | DB nueva vacía | 4 pendientes abiertos y 28 resueltos eran estado real que valía la pena conservar. |
| `WorkingDirectory` | fijado en la unidad | dejarlo sin definir | `db.py` usa `DB_PATH = Path("pendientes.db")` — ruta **relativa**. Sin esta línea systemd crearía una base vacía en otro lado y el bot se vería sano mostrando cero pendientes. |
| `RestartSec=10` | 10 s | 0–1 s | 10 s de caída son invisibles para el usuario, mientras que reinicios instantáneos golpearían la API durante una caída. |
| Token del bot | mismo token, copia del Mac apagada | segundo bot de desarrollo | Telegram permite exactamente **un** proceso en long polling por token. Comprobado el 2026-09-27: dos pollers no se resuelven limpiamente — **ambos** reciben `Conflict` y ambos se degradan, alternándose, lo que desde Telegram solo parece que el bot está inestable. |

### Observabilidad y resiliencia (agregado 2026-09-27)

| Decisión | Elegido | Descartado | Por qué |
|---|---|---|---|
| Logging | módulo `logging` → journald | `print`, un archivo de log | `print` no puede llevar nivel ni nombre de logger. journald ya pone timestamp, rota y se consulta por tiempo — un archivo implicaría escribir la rotación. (Daimon usa archivo solo porque cron no se integra con el journal.) |
| Formato del log | `"%(levelname)s %(name)s \| %(message)s"` | incluir timestamp | journald marca cada línea; agregar otro da dos fechas por línea. |
| Nivel de `httpx` | `WARNING` | dejarlo en `INFO` | En `INFO` registra cada petición HTTP — una línea cada pocos segundos, para siempre. apscheduler y `telegram.ext` quedan en `INFO` porque solo hablan al arrancar, y sus líneas confirman que el job del digest quedó registrado. |
| Estilo de llamada | `log.info("x %s", y)` | f-strings | El mensaje solo se construye si ese nivel está habilitado. |
| Qué se registra | pendiente creado, resuelto, ya resuelto, digest enviado, remitente fuera del allowlist | cada mensaje | Una línea por **cambio de estado**, no por evento. La rama "ya estaba resuelto" es la condición de carrera (dos personas tocando el mismo ✅) hecha visible. |
| Posición del log | **después** del `await` que reporta | antes | Una línea escrita antes del envío afirmaría éxito de un envío que falló. Un log que puede mentir es peor que no tener log. |
| Error handler | tres ramas por tipo | un catch-all | `Conflict` → `CRITICAL` (dos pollers: el único error operativo que arruina la confiabilidad en silencio). `NetworkError` → `WARNING` (la librería reintenta sola). Cualquier otro → `ERROR` con traceback. |
| `BadRequest` excluido de la rama de red | `isinstance(err, NetworkError) and not isinstance(err, BadRequest)` | solo `NetworkError` | En python-telegram-bot `BadRequest` **hereda** de `NetworkError`, una rareza histórica. Sin la exclusión, un bug real (chat id malo, mensaje demasiado largo) quedaría archivado como "red inestable" y culparías al router por días. |
| Reintento del digest | 3 intentos, 30 / 60 / 90 s | fallar en el primer error, o reintentar para siempre | Los cortes de DNS observados duran segundos, así que el intento 2 casi seguro gana. En el peor caso se rinde a los ~3 min — un digest tarde, no un día perdido. Intervalos crecientes (backoff) porque golpear una red caída no ayuda. |
| `await asyncio.sleep` | asyncio | `time.sleep` | `time.sleep` congela todo el proceso: por 90 s el bot no responde nada. `asyncio.sleep` le cede el turno al event loop. En código async, cualquier llamada bloqueante es un bot detenido. |
| `drop_pending_updates` | **`False`** | `True` (el original) | Con `True`, los mensajes enviados mientras el bot reinicia se **descartan** — la promesa central del producto ("que nada se olvide") roto por su propio despliegue. Con `False` se convierten en pendientes al arrancar. El replay es seguro porque `resolve_pending` está protegido por `AND state='OPEN'`. Costo: tras una caída larga llega un lote de ítems viejos de golpe — que para este producto es el comportamiento correcto. |

## El archivo de unidad

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

Notas:

- `ExecStart` llama al python del venv por ruta absoluta. No hay `activate` en ninguna parte —
  activar solo reordena el `PATH`, y systemd no tiene shell donde hacerlo.
- `PYTHONUNBUFFERED=1` — sin esto Python almacena la salida en buffer cuando no está conectado
  a una terminal, y los logs llegan tarde y en bloques silenciosos.
- Sin `After=network-online.target`: el loop de reinicio *es* la estrategia de espera de red.

## Operación

Se corre desde cualquier carpeta del servidor — `WorkingDirectory` resuelve la ruta.

```bash
systemctl --user status pendientes          # ¿está vivo?
systemctl --user restart pendientes         # después de cambiar código
systemctl --user stop pendientes            # libera el token para desarrollo local
systemctl --user show pendientes -p NRestarts -p MainPID -p ExecMainStartTimestamp
```

Leer logs:

```bash
journalctl --user -u pendientes -f              # feed en vivo; Ctrl+C sale del feed, no del bot
journalctl --user -u pendientes -n 20 --no-pager
journalctl --user -u pendientes --since today | grep -i digest
journalctl --user -u pendientes --since "2 days ago" | grep -iE "intento|NO enviado|red inestable|CRITICAL"
```

`-f` sigue el log y nunca devuelve el prompt — eso no es que esté colgado. Sin `--no-pager`,
`journalctl` abre un paginador del que se sale con `q`, la otra forma en que parece trabado.

## Cómo subir un cambio

El código se edita en el Mac, nunca en el servidor. El servidor solo hace pull.

```bash
# Mac
.venv/bin/python3 -m py_compile bot.py && echo "sintaxis OK"
git add -A && git commit -m "..." && git push

# servidor
cd ~/pendientes-bot && git pull
systemctl --user restart pendientes
journalctl --user -u pendientes -n 10 --no-pager
```

Si cambió una dependencia: `source .venv/bin/activate && pip install -r requirements.txt`

`py_compile` parsea el archivo sin ejecutarlo — no arranca el bot ni usa el token. Es la
única prueba local disponible ahora, porque el servidor tiene el token. Verifica la
gramática, **no el significado**: un `import` borrado compila igual y falla en runtime.

Los commits se pueden corregir con `--amend` libremente antes del push, nunca después — un
commit ya empujado puede estar en el servidor, y reescribirlo crea dos historias que no
coinciden.

## Registro de verificación

| Prueba | Resultado |
|---|---|
| Corrida continua | 3 días en un solo proceso (PID 66977, Sep 24 12:08 → Sep 27), `NRestarts=0`, con seis cortes de DNS y un `Bad Gateway` |
| Mundo real | Digest entregado 08:30 el 25, 26 y 27 de sep; `/lista` respondió desde fuera de la casa con el Mac cerrado |
| Caída (`kill -9`) | PID 66977 → 122163 en menos de 12 s, `NRestarts=1`, siguió `active` |
| Reinicio | Volvió como PID 1606 con `Users logged in: 0` — linger confirmado |
| Servicio vecino | La entrada de cron de Daimon (7am) sobrevivió al reinicio |
| Logging (9a) | `pendiente #48 creado`, `#48 resuelto`, `digest enviado con 13 pendientes abiertos` — los cuatro tipos de evento observados en vivo |
| Error handler (9b) | Conflict forzado a propósito arrancando un segundo poller en el Mac: `CRITICAL` registrado en **ambos** lados, 6 conflictos en 40 s |
| Reintento del digest (9c) | Camino de éxito comprobado con `/digest` (un mensaje, una línea de log). El reintento en sí no está comprobado — necesita una falla de red en el momento exacto del envío |

## Debilidades conocidas

1. **Sin backup de la base.** `pendientes.db` existe en un solo lugar, en un portátil con el
   teclado muerto. Un `sqlite3 .backup` programado es el arreglo barato. **Máxima prioridad.**
2. **Caídas de DNS de noche.** Seis eventos `Temporary failure in name resolution` (errno -3)
   entre el 24 y el 26 de sep, casi todos entre 20:00 y 05:00 — probablemente ahorro de
   energía del WiFi Intel o renovación de lease del router. El loop interno de la librería los
   absorbe (el proceso nunca murió) y ahora el digest reintenta, así que está monitoreado más
   que arreglado.
3. **El reintento del digest no está comprobado** en producción. Buscar `intento` en el log
   después del próximo corte.
4. **Sin llave SSH** — cada `ssh`/`scp` pide contraseña, y un prompt de contraseña se traga en
   silencio todo lo que se pegue después. `ssh-copy-id` lo resuelve.
5. **23 actualizaciones del sistema pendientes** en el host al 27 de sep.
