# Finance Tracker

Track spending and income, and follow your net worth across cash, stocks, crypto,
and gold with live market prices. You can use it as a **web dashboard** with
charts or as a **terminal app**. Both read and write the same data.

## Web dashboard

One-time setup, from the project folder:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

```bash
cd frontend && npm install && npm run build && cd ..
```

Then each time:

```bash
.venv/bin/python main.py --web
```

Open **http://127.0.0.1:8000** and stop the server with Ctrl-C. Only your own
computer can connect, so your data isn't exposed to your network.

To browse the API itself, open http://127.0.0.1:8000/docs. It's an interactive page
that FastAPI generates from the code.

### Working on the frontend

`npm run build` makes a finished copy of the site that the Python server serves.
While you're changing React code, run two terminals instead so edits show up
instantly:

```bash
.venv/bin/python main.py --web
```

```bash
cd frontend && npm run dev
```

Then open **http://localhost:5173**. Vite reloads the page on every save and
forwards `/api` requests to the Python server.

## Terminal app

```bash
python3 main.py
```

The terminal app needs only the standard library, so there's nothing to install.
The first run asks your name and creates `data/finance.db`. Every change is saved
the moment you make it.

```bash
python3 main.py --db path/to/other.db      # use a different database file
python3 main.py --import-legacy            # import the old information_save_file
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

```bash
cd frontend && npm run typecheck
```

The API tests are skipped automatically if the web packages aren't installed.

## How it fits together

```
React (browser)  ──HTTP/JSON──>  api.py  ──┐
                                           ├──>  store.py / reports.py / prices.py  ──>  SQLite
Terminal         ──────────────>  cli.py ──┘
```

`api.py` and `cli.py` are two front doors to the same logic. Neither one does any
math or touches the database directly.

```
main.py                     entry point (terminal, or --web)
finance_tracker/
  models.py                 Transaction / Holding dataclasses, money and date parsing
  store.py                  SQLite schema, migrations, and every query
  prices.py                 live prices (Yahoo Finance) with an offline cache
  reports.py                monthly stats, net-worth math (pure functions)
  api.py                    REST API for the web dashboard (FastAPI)
  cli.py                    terminal menus and validated input
  legacy.py                 importer for the original JSON-lines save file
  paths.py                  where files live
frontend/
  src/api.ts                typed client for every API endpoint
  src/pages/                Dashboard, Transactions, Holdings
  src/components/           charts, forms, tables
  src/styles.css            design tokens (light + dark) and layout
tests/                      unit tests, scripted terminal sessions, API tests
legacy/main_v1.py           the original single-file version
```

### API endpoints

| Method | Path | |
|---|---|---|
| GET / POST | `/api/profile` | your name / create profile |
| GET | `/api/summary?month=` | spent, income, net for a month |
| GET | `/api/months` | months with data |
| GET | `/api/categories?kind=` | category names, most used first |
| GET / POST | `/api/transactions` | list / add |
| DELETE | `/api/transactions/{id}` | delete |
| GET | `/api/transactions.csv` | CSV download |
| GET | `/api/reports/categories?month=` | spending per category |
| GET | `/api/reports/monthly` | last 12 months with how unusual each was |
| GET / POST | `/api/holdings` | list / add |
| PATCH / DELETE | `/api/holdings/{id}` | change quantity or value / remove |
| GET | `/api/quotes/{symbol}` | live price (used to check tickers) |
| GET | `/api/net-worth` | value everything; records today's snapshot |
| GET | `/api/net-worth/history` | daily snapshots for the trend chart |

## Design decisions

- **SQLite, not a JSON list.** Data lives on disk, and only what changed gets
  written. Reports run as `GROUP BY` queries inside the database. Category names
  are stored once, and an index on the date keeps lookups fast.
- **Money is integer cents.** Floats can't store most decimal amounts exactly
  (`0.1 + 0.2 != 0.3`). The API takes amounts as text (`"4.50"`) and the
  server parses them, so one set of validation rules covers both interfaces.
- **Dates are ISO strings on disk and `date` objects in code.**
- **One database connection per web request**, always closed afterwards.
- **Prices are cached for 15 minutes.** When offline, the app uses the last known
  price and labels it as stale. A net-worth snapshot is only recorded when every
  holding could be priced.
- **Charts:** ranked bars for categories instead of a pie, because lengths are
  easier to compare than slice angles. Each asset type keeps the same color
  everywhere, and every colored mark has a text label or a "Show as table"
  option, so nothing depends on color alone. Light and dark mode follow your
  system setting.
- **Your data stays out of git.** `data/`, `exports/`, and any `*.db` file are
  gitignored.

## Roadmap

- [x] Phase 1: core loop, input validation, totals
- [x] Phase 2: persistence, user profile, new vs. returning user
- [x] Phase 3: cash, stocks, crypto, and gold with live prices
- [x] Phase 4: web dashboard (React + FastAPI) with charts
- [ ] Phase 5: AI analyst. Still to decide: a local model (e.g. via Ollama) keeps
  financial data on your machine, while a hosted API is easier to set up. Either
  way, it would be a new API endpoint that sends a summary, not raw
  transactions.

Ideas not built yet: recurring transactions (rent, subscriptions), budgets per
category, cost basis and gain/loss for investments, liabilities (loans, credit
cards), and non-USD holdings.
