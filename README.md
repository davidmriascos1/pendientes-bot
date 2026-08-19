# Pendientes Bot

*English · [Español](README.es.md)*

A Telegram bot that keeps agreements between two people alive — money
owed, chores, favors — until someone confirms they were done.

## What it is not

Not an expense tracker. No categories, no budgets, no balances, no
dashboards. The goal isn't knowing how much we spent; it's making sure
something that requires an action doesn't fall out of our attention
until it's resolved.

The core principle: **a reminder doesn't disappear because the due date
passed. It disappears because a human confirmed the action was done.**

## How it works

    Create  ->  Remind  ->  Close

- You write a normal message in the group and it becomes a pending item
- Every morning at 8:30 a digest arrives with everything still open
- One button per item marks it resolved

## Stack

- Python 3.14
- python-telegram-bot (long polling)
- SQLite with raw SQL (no ORM)
- JobQueue / APScheduler for the daily digest

No web framework, no remote database, no Docker. Two users and ~20 open
items don't justify more infrastructure.

## State machine

    DRAFT -> OPEN -> RESOLVED
                  -> ARCHIVED

State lives in the `state` column. Resolving uses a SQL guard
(`WHERE id = ? AND state = 'OPEN'`), so an item can't be resolved twice
even if both people tap the button at the same moment.

## Running it

    git clone https://github.com/davidmriascos1/pendientes-bot
    cd pendientes-bot
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    ./run.sh

You'll need a bot created via @BotFather with privacy mode **disabled**
(`/setprivacy` -> Disable), or the bot won't see ordinary group messages.

## Status

V0 working. Not yet built: due dates, reminder cadences, multi-group
support, deployment.
