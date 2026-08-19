# Bot de Pendientes

*[English](README.md) · Español*

Bot de Telegram que mantiene vivos los acuerdos entre dos personas
—platas prestadas, tareas, favores— hasta que alguien confirma que se
hicieron.

## Qué NO es

No es un rastreador de gastos. No hay categorías, presupuestos, balances
ni dashboards. El objetivo no es saber cuánto gastamos, sino que algo que
requiere una acción no desaparezca de nuestra atención hasta resolverse.

El principio central: **un recordatorio no desaparece porque pasó la
fecha, sino porque un humano confirmó que la acción terminó.**

## Cómo funciona

    Registrar  ->  Recordar  ->  Cerrar

- Escribes un mensaje normal en el grupo y se guarda como pendiente
- Cada mañana a las 8:30 llega un resumen con todo lo abierto
- Un botón por pendiente lo marca como resuelto

## Stack

- Python 3.14
- python-telegram-bot (long polling)
- SQLite con SQL crudo (sin ORM)
- JobQueue / APScheduler para el resumen diario

Sin framework web, sin base de datos remota, sin Docker. Dos usuarios y
~20 pendientes activos no justifican más infraestructura.

## Máquina de estados

    DRAFT -> OPEN -> RESOLVED
                  -> ARCHIVED

El estado vive en la columna `state`. Resolver usa una guarda SQL
(`WHERE id = ? AND state = 'OPEN'`), así que un pendiente no se puede
resolver dos veces aunque las dos personas toquen el botón a la vez.

## Correrlo

    git clone https://github.com/davidmriascos1/pendientes-bot
    cd pendientes-bot
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    ./run.sh

Necesitas un bot creado con @BotFather y el privacy mode desactivado
(`/setprivacy` -> Disable), o el bot no verá los mensajes normales del
grupo.

## Estado actual

V0 funcionando. Falta: fechas límite, cadencias de recordatorio,
soporte multi-grupo y despliegue.
