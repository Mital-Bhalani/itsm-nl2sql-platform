# NL2SQL Platform over ITSM Ticket Data

Welcome. Over four days we build **one** piece of software together: a system where a
service manager can ask a plain-English question about IT Service Management (ITSM)
tickets — for example, *"which assignment groups breached SLA most last month?"* — and
get a clear answer back, with the SQL it ran shown for trust, executed **safely**.

You will **build this platform using Claude Code** across the week. That is the skill this
program is really about: directing an AI coding assistant to build real software.

## What we'll do on Day 1

Day 1 is the gentle on-ramp — the goal is a shared starting point and confidence, not
clever code. Together we will:

- Get set up with Claude Code and the project.
- Stand up the **ITSM ticket database** and load realistic sample data.
- Use Claude Code to **explore the database** and explain the tables in plain English.
- Try the **simplest possible "question → SQL"** approach — and see, first-hand, exactly
  where it falls short (wrong answers, unsafe queries, exposed private data).
- Write down **why** it fell short. That list is what the rest of the week is built to fix.

By the end of the day you'll understand the shape of the problem and why the "obvious"
approach isn't good enough — which is what makes everything we build next worth building.

## Project structure

```
.
├── README.md         # you are here — the project overview
├── db/               # the ITSM ticket database: schema.sql + seed.py (builds the sample data)
├── semantics/        # the "meaning" layer for the data: build_catalog.py
├── agent/            # questions → SQL: naive_spike.py now, the full agent later in the week
├── api/              # the service that exposes it over HTTP       (later in the week)
├── ui/               # the screen a service manager would use      (later in the week)
└── evals/            # how we measure whether the answers are right (later in the week)
```

Each folder fills in as the week progresses. Your facilitator will walk you through each
part live — just follow along on the shared screen.

## Building the database

```
python db/seed.py                   # creates db/tickets.sqlite with the sample tickets
python semantics/build_catalog.py   # adds the "meaning" layer; run it after every seed
```

## What you need

- A laptop with **Claude Code** installed and working.
- That's it for now — your facilitator will guide you through everything else in the room.
