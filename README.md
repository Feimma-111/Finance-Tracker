# Finance Tracker

Track spending and income, and follow your net worth across cash, stocks, crypto,
and gold with live market prices. You can use it as a **web dashboard** with
charts or as a **terminal app**. Both read and write the same data.

## Web dashboard

**Easiest:** double-click **Finance Tracker.command** in Finder. It starts the server
and opens your browser. Close the Terminal window to stop it. You can drag it to the
Dock.

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
  analyst.py                AI reviews: fact sheet + Ollama client
  assistant.py              AI questions: lookup tools, the tool loop, number check
  importer.py               CSV import: column guessing, parsing, duplicate detection
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
| POST | `/api/import/preview` | read a CSV and show what importing would do |
| POST | `/api/import` | import a CSV's new transactions |
| GET | `/api/reports/categories?month=` | spending per category |
| GET | `/api/reports/monthly` | last 12 months with how unusual each was |
| GET / POST | `/api/holdings` | list / add |
| PATCH / DELETE | `/api/holdings/{id}` | change quantity or value / remove |
| GET | `/api/quotes/{symbol}` | live price (used to check tickers) |
| GET | `/api/net-worth` | value everything; records today's snapshot |
| GET | `/api/net-worth/history` | daily snapshots for the trend chart |
| GET / POST | `/api/recurring` | recurring rules / add one (past occurrences filled in) |
| PATCH / DELETE | `/api/recurring/{id}` | pause, resume, change amount / stop |
| GET / PUT | `/api/settings` | theme; AI address and model |
| PUT | `/api/profile` | rename |
| GET | `/api/ai/status` | is the PC reachable, and which models it has |
| GET / POST | `/api/ai/reviews/{month}` | last saved review / write a new one |
| POST | `/api/ai/ask` | answer a question using lookup tools |

### AI analyst

On the Dashboard, the **AI review** card writes a short review of the selected
month: a headline, what stood out, and ideas. The model runs in
[Ollama](https://ollama.com) on your own PC and is reached over Tailscale, so
your data never goes to a cloud service.

**How it avoids made-up numbers.** Small models describe numbers well but get
arithmetic wrong; in testing, one reported $467 saved when the answer was $167. So
`analyst.py` computes every total, difference, and percentage in Python and gives
the model a fact sheet to describe. It's told never to calculate anything. The
model also has to reply in a fixed JSON format, so the app can display it
reliably. "What the AI was shown" on each review displays that fact sheet.

**When the PC is off**, the card says so and still shows the last saved review.

**Ask a question.** The card's second tab answers questions in plain English,
such as "How much did I spend on food since August?". The model can't see the
database directly. It can only call read-only lookup tools in `assistant.py`:
totals for a date range, spending by category, comparing two periods, monthly
totals and averages, finding transactions, recurring charges, and net worth.
Python runs each lookup and returns exact figures. The model then writes the
answer, and "How I got this" shows every lookup it made. As a final check,
every dollar amount and percentage in the answer is compared with what the
lookups returned. Rounding is allowed; any other number gets a warning. Follow-up
questions ("and in October?") keep the conversation's context. The conversation
isn't saved.

**Setup:**
1. On the PC, install Ollama and run `ollama pull qwen3:14b` (any 8–14B model
   fits a 12 GB GPU).
2. Make Ollama listen on the PC's Tailscale address only, not `0.0.0.0`.
   Ollama has no password, so this keeps it unreachable from your home network.
   Get the address with `tailscale ip -4`, then:
   ```powershell
   setx OLLAMA_HOST "100.x.y.z:11434"
   ```
   Restart Ollama afterwards.
3. If Windows Firewall blocks the port, allow Tailscale addresses only, in an
   Administrator PowerShell:
   ```powershell
   New-NetFirewallRule -DisplayName "Ollama (Tailscale only)" -Direction Inbound -Protocol TCP -LocalPort 11434 -RemoteAddress 100.64.0.0/10 -Action Allow
   ```
4. In the app, open **Settings → AI analyst**, enter `http://100.x.y.z:11434`,
   and choose a model.

### Importing a CSV

To import a CSV, go to **Settings → Import transactions** and choose the file. It can
come from your bank, a spreadsheet, or this app's own export. Importing happens in
two steps:

1. **Preview.** The app guesses which column is which and detects the date
   format, then shows how the first rows will be read and how many rows are
   ready, duplicates, or problems. Every guess can be changed, and the preview
   updates right away.
2. **Import.** The new rows are saved all at once, or not at all if something
   fails.

What the importer handles:

- **Amount layouts:** one signed column (most banks: negative means money out),
  a column where positive means spending (many credit cards), separate debit
  and credit columns, or an expense/income column like this app's export.
- **Dates:** `2026-07-01`, `07/01/2026`, `1/7/26`, `25.10.2026`, `Jul 3, 2026`,
  and more. When dates could be read two ways (03/04), you choose.
- **Duplicates:** rows that are already saved (same date, amount, type, and
  description) are skipped, so importing an overlapping statement is safe. Two
  real $4.50 coffees on the same day still both count.
- **Problem rows** are skipped and listed with their line numbers, for example
  an unreadable amount, a future date, or a zero amount. Amounts written with a
  decimal comma (`42,10`) are rejected rather than read as 4,210.

### Recurring transactions

Choose a **Repeat** option (weekly, every 2 weeks, monthly, yearly) when adding a
transaction. At the start of every request, the server turns any occurrences that
have come due into real transactions, marked ↻. That makes the behavior the same
everywhere:

- On your laptop, they appear when you open the app.
- On an always-on server, they appear as soon as any device checks in.
- If the app was closed for months, it catches up on the next open.

Each occurrence is created exactly once, even if two requests arrive at the same
moment. Monthly rules on the 29th–31st clamp to shorter months without drifting
(Jan 31 → Feb 28 → Mar 31). Pausing and resuming skips the months that were
paused. Stopping a rule keeps the transactions it already created.

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
- [x] Phase 5: AI analyst, with monthly reviews from a local model on your own PC
- [x] Ask questions about your money, answered from exact lookups
- [ ] Next: a login before phone or Raspberry Pi access, and Wake-on-LAN to
  turn the PC on from the app

Ideas not built yet: budgets per category, cost basis and gain/loss for investments, liabilities (loans, credit
cards), and non-USD holdings.
