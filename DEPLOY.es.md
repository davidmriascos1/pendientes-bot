# Despliegue — pendientes-bot

Cómo corre este bot 24/7, y por qué cada decisión se tomó así.
Desplegado 2026-09-24 · verificado 2026-09-27

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
| `RestartSec=10` | 10 s | 0–1 s | Telegram guarda los updates no entregados ~24 h, así que 10 s de caída son invisibles para el usuario, mientras que reinicios instantáneos golpearían la API durante una caída. |
| Token del bot | mismo token, copia del Mac apagada | segundo bot de desarrollo | Telegram permite exactamente **un** proceso en long polling por token. Dos producen `Conflict: terminated by other getUpdates request` y recordatorios silenciosamente poco confiables. |

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
journalctl --user -u pendientes -f          # ver logs en vivo
journalctl --user -u pendientes --since today
systemctl --user show pendientes -p NRestarts -p MainPID -p ExecMainStartTimestamp
```

## Cómo subir un cambio

El código se edita en el Mac, nunca en el servidor. El servidor solo hace pull.

```bash
# Mac
git add -A && git commit -m "..." && git push

# servidor
cd ~/pendientes-bot && git pull
systemctl --user restart pendientes
journalctl --user -u pendientes -n 20
```

Si cambió una dependencia:

```bash
source .venv/bin/activate && pip install -r requirements.txt
```

## Registro de verificación

| Prueba | Resultado |
|---|---|
| Corrida continua | 3 días en un solo proceso (PID 66977, Sep 24 12:08 → Sep 27), `NRestarts=0` |
| Mundo real | Digest diario entregado 08:30 el 25, 26 y 27 de sep; `/lista` respondió desde fuera de la casa con el Mac cerrado |
| Caída (`kill -9`) | PID 66977 → 122163 en menos de 12 s, `NRestarts=1`, siguió `active` |
| Reinicio | Volvió como PID 1606 con `Users logged in: 0` — linger confirmado |
| Servicio vecino | La entrada de cron de Daimon (7am) sobrevivió al reinicio |

## Debilidades conocidas

1. **El bot es casi mudo.** En tres días registró solo dos líneas, ambas al arrancar.
   No escribe nada cuando se guarda o resuelve un pendiente, ni cuando sale el digest — así
   que los logs prueban que el *proceso* estaba vivo, pero no que hizo su *trabajo*. Solo
   Telegram puede. Es la brecha más grande; se arregla primero.
2. **Sin error handler registrado.** `python-telegram-bot` advierte `No error handlers are
   registered`, así que un corte de red de 2 segundos vuelca un traceback completo. Agregar
   uno convierte cada corte en una línea legible.
3. **Caídas de DNS de noche.** Seis eventos `Temporary failure in name resolution` (errno -3)
   entre el 24 y el 26 de sep, casi todos entre 20:00 y 05:00 — probablemente ahorro de
   energía del WiFi Intel o renovación de lease del router. El loop interno de la librería
   los absorbió todos (el proceso nunca murió), así que es cosmético hasta que se demuestre
   lo contrario.
4. **Sin backup de la base.** `pendientes.db` existe en un solo lugar. Un `sqlite3 .backup`
   programado es el arreglo barato.
5. **23 actualizaciones del sistema pendientes** en el host al 27 de sep.
