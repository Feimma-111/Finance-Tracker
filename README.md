# Finance Tracker

A personal finance app that runs on your own computer. Track spending and
income, follow your bank balances and net worth, and see how your stocks,
crypto, and gold are doing with live market prices. An optional AI analyst runs
on a computer you own (through [Ollama](https://ollama.com)), so your data never
goes to a cloud service. Use it as a **web dashboard** with charts, from your
phone over [Tailscale](https://tailscale.com), or as a **terminal app**. All of
them read and write the same data.

It's a learning project: a Python/FastAPI backend over SQLite, a React +
TypeScript frontend, and 160+ tests. No financial data is in this repository;
it lives in a file on your own machine.

**What it does**

- **Spending:** transactions with categories, recurring bills, CSV import, and
  search by name or amount. Charts show where the money went and how this month
  is pacing against last month. Tick a few categories to chart just those, or
  click a slice to see what one category was made of.
- **Money you have:** bank accounts whose balances follow the transactions you
  link to them (your *liquid* total), plus stocks, crypto, and gold priced
  live, with gains since you bought and over any period, Robinhood style.
- **AI analyst:** monthly reviews, a close look at the categories you pick, a
  chat that answers questions from exact lookups, and a description of your
  investments and the market. Every number is computed by the app, never by
  the model.
- **Safety:** a passcode lock, automatic backups, and the database kept outside
  the project folder.

## Web dashboard

**Easiest:** double-click **Finance Tracker.command** in Finder. It starts the server
and opens your browser. Close the Terminal window to stop it. You can drag it to the
Dock.

One-time setup, from the project folder. You need a stable Python 3.15 from
python.org: the big download button, not an "a", "b" or "rc" pre-release. After
installing it, run **Install Certificates.command** in `/Applications/Python 3.15/`
once, so Python trusts HTTPS sites. When a newer 3.15.x comes out, installing it
updates Python in place and the setup below doesn't need redoing.

```bash
python3.15 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Every package in `requirements.txt` is pinned to a version that was at least
two weeks old when chosen, which guards against freshly published malicious
releases.

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

### Passcode

The web app is locked with a 6-digit passcode, which you choose the first time
you open it. Each device then stays signed in for 30 days.

- **Stored safely.** Only a slow, salted PBKDF2 hash of the passcode is kept
  (600,000 rounds). The sign-in cookie is HttpOnly and SameSite=Strict, and the
  database stores only a hash of each session token.
- **Guessing is impractical.** After 5 wrong tries the app locks for 30
  seconds, and the lock doubles with each further miss, up to an hour.
- **Settings → Passcode** lets you change it, which signs out your other
  devices, or **Lock now**.
- **Forgot it?** On the Mac, run `.venv/bin/python main.py --reset-passcode`
  and the app will ask for a new one.
- The terminal app isn't locked: it reads the database file directly, so anyone
  using your Mac could open the file anyway.

### Backups

- **When:** once a day automatically, plus before every CSV import, before every
  restore, and before the database is upgraded to a new schema.
- **How:** copies use SQLite's online backup API, so each one is consistent even
  while the app is writing, and each is checked with `PRAGMA integrity_check`.
- **Where:** a `backups` folder next to the database, holding the newest 30
  daily copies and 10 safety copies. Only your user account can read them.
- **Settings → Backups** has **Back up now** and **Download a copy**. Keep a
  copy somewhere other than this Mac.
- **From the terminal:**
  ```bash
  .venv/bin/python main.py --list-backups
  ```
  ```bash
  .venv/bin/python main.py --restore-backup finance-2026-11-22.db
  ```
  A restore saves your current data first, so it can't lose anything.

### Security, in short

| | |
|---|---|
| Who can reach the app | Only this Mac (`127.0.0.1`), plus your own Tailscale devices through `tailscale serve`. Never turn on `tailscale funnel`, which would make it public. |
| Sign-in | 6-digit passcode stored as a PBKDF2 hash, with a lockout after wrong guesses. Sessions use HttpOnly, SameSite=Strict cookies. |
| Data on disk | One SQLite file, readable only by your user account, on a FileVault-encrypted disk. It's never committed to git. |
| What leaves your devices | Ticker symbols go to Yahoo for prices and news headlines. Nothing else: the AI runs on your own PC over Tailscale. |
| Web attacks | Every query is parameterized, so SQL injection isn't possible. React escapes all text, including AI answers and imported CSVs. The SameSite cookies and JSON-only API block cross-site requests. |

### On your phone

The app runs on your Mac, and your phone opens it over Tailscale, so it isn't on
the public internet and only your own devices can reach it.

1. In the Tailscale admin console, under **DNS**, turn on **HTTPS
   Certificates**. This is a one-time setting.
2. On the Mac, while the app is running:
   ```bash
   /Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg 8000
   ```
   This gives the app a private HTTPS address,
   `https://<your-mac>.<tailnet>.ts.net`, that only your Tailscale devices can
   open. Undo it with `tailscale serve reset`.
3. On the phone, with Tailscale on, open that address. Then use **Add to Home
   screen** (on Android, Chrome's ⋮ menu → *Install app*; on iPhone, Safari's
   Share → *Add to Home Screen*). It opens full-screen with its own icon and a
   bottom tab bar, like an app.

The Mac has to be awake with the app running. An always-on Raspberry Pi would
remove that requirement. [docs/raspberry-pi.md](docs/raspberry-pi.md) is a
step-by-step plan for that move.

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
For live prices there, Python needs its certificates installed; see the setup
step above.
The first run asks your name and creates the database. Every change is saved the
moment you make it.

### Where your data lives

Your data is in your account's application-data folder, outside the project:

| | |
|---|---|
| macOS | `~/Library/Application Support/Finance Tracker/finance.db` |
| Linux (e.g. a Raspberry Pi) | `~/.local/share/finance-tracker/finance.db` |
| Windows | `%APPDATA%\Finance Tracker\finance.db` |

This location means deleting or re-cloning the project, or running
`git clean -xdf`, can't touch your data. It also keeps the file out of synced
folders such as iCloud Desktop & Documents, where syncing a database while it's
in use can corrupt it. Older versions kept the database in the project's
`data/` folder. The first time a newer version starts, it moves the database
for you: it copies and verifies it, compares every table, and keeps the old
file as `data/finance.db.moved` until you delete it. To use a different file,
set `FINANCE_TRACKER_DB` or pass `--db`.

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
  reports.py                monthly stats, net-worth math, purchase grouping (pure functions)
  portfolio.py              investment gains, chart series, cash account balances (pure functions)
  api.py                    REST API for the web dashboard (FastAPI)
  auth.py                   passcode hashing, sessions, lockout
  backup.py                 daily backups, safety copies, restore
  analyst.py                AI reviews: fact sheet + Ollama client
  assistant.py              AI questions: lookup tools, the tool loop, number check
  importer.py               CSV import: column guessing, parsing, duplicate detection
  cli.py                    terminal menus and validated input
  legacy.py                 importer for the original JSON-lines save file
  paths.py                  where files live (per-OS data folder)
  relocate.py               one-time move of old data out of the project
frontend/
  src/api.ts                typed client for every API endpoint
  src/pages/                Dashboard, Transactions, Holdings
  src/components/           charts, forms, tables, AI panels
  src/search.ts             transaction search (names, amounts, ranges)
  src/styles.css            design tokens (light + dark) and layout
tests/                      unit tests, scripted terminal sessions, API tests
legacy/main_v1.py           the original single-file version
docs/raspberry-pi.md        plan for running it on an always-on Raspberry Pi
deploy/                     systemd service and backup-pull script for the Pi
```

### API endpoints

Every endpoint except `/api/auth/...` requires a signed-in session.

| Method | Path | |
|---|---|---|
| GET | `/api/auth/status` | is a passcode set? is this browser signed in? |
| POST | `/api/auth/setup` · `/login` · `/logout` · `/change` | choose, sign in, lock, change the passcode |
| GET / POST | `/api/profile` | your name / create profile |
| GET | `/api/summary?month=` | spent, income, net for a month |
| GET | `/api/months` | months with data |
| GET | `/api/categories?kind=` | category names, most used first |
| GET / POST | `/api/transactions` | list / add |
| GET / PATCH / DELETE | `/api/transactions/{id}` | one (with how many share its description) / edit, optionally recategorizing matching ones / delete |
| GET | `/api/transactions.csv` | CSV download |
| POST | `/api/import/preview` | read a CSV and show what importing would do |
| POST | `/api/import` | import a CSV's new transactions |
| GET | `/api/reports/categories?month=` | spending per category |
| GET | `/api/reports/monthly` | last 12 months with how unusual each was |
| GET | `/api/reports/pace?month=&category=` | running total through a month vs. the month before (optionally only some categories) |
| GET | `/api/reports/purchases?category=&month=` | one category's spending, grouped by purchase |
| GET / POST | `/api/holdings` | list / add |
| PATCH / DELETE | `/api/holdings/{id}` | change name, symbol, quantity, value, purchase date, or price paid / remove |
| GET | `/api/quotes/{symbol}` | live price (used to check tickers) |
| GET | `/api/net-worth` | value everything (cash accounts with their linked transactions), liquid total; records today's snapshot |
| GET | `/api/portfolio?period=` | investment gains since buying, over 1W–All, and today, plus the chart |
| GET | `/api/net-worth/history` | daily snapshots for the trend chart |
| GET / POST | `/api/recurring` | recurring rules / add one (past occurrences filled in) |
| PATCH / DELETE | `/api/recurring/{id}` | pause, resume, change amount / stop |
| GET / PUT | `/api/settings` | theme; AI address and model |
| PUT | `/api/profile` | rename |
| GET | `/api/ai/status` | is the PC reachable, and which models it has |
| GET / POST | `/api/ai/reviews/{month}` | last saved review / write a new one |
| POST | `/api/ai/ask` | answer a question using lookup tools (optionally a follow-up on a category analysis) |
| POST | `/api/ai/focus` | review only the chosen categories (not saved) |
| GET | `/api/ai/changed` | when the data reviews are based on last changed |
| POST | `/api/ai/holdings` | describe your investments and the market (not saved) |

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
If any transactions or covered expenses change after a review was written, the
review says so and offers to write a new one.

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
is kept in the browser's session storage, so it survives switching tabs, pages,
and reloads, and it's gone when the browser tab closes. It's never written to the
database.

**Look at just some categories.** In **Spending by category**, every category
starts ticked. Untick the ones to leave out, or press **All** to tick or untick
everything at once. The pie or bars then show only the ticked categories, with
their total and share of the month. Clicking a slice, a bar, or a legend row
ticks just that category ("Other" ticks everything in it). With one category
ticked, the chart breaks it down by purchase (Boba ×3, Lunch ×2, ...). The panel
beside the chart, **AI on these categories**, looks at only the ticked ones. It names the purchases that drove
the spending (for example, "3 boba runs, $87.81"), describes the trend, and
gives ideas for those purchases. Under the chart, the same running-total line
as the top of the Home screen shows just the ticked categories against last
month, so one big bill elsewhere (tuition, say) doesn't hide the trend. Below
the analysis you can **ask follow-up questions**: the server rebuilds the same
fact sheet and gives it to the model as context, along with the lookup tools,
and numbers from either count as checked. Its fact sheet (`focus_facts` in
`analyst.py`) contains nothing about the other categories, so the model can't
wander into reviewing the whole month. Comparisons such as "higher than any of
the previous 6 months" or "up 2 months in a row" are worked out in Python too,
because in testing the model misread rows of monthly numbers. Like the chat,
these analyses are kept for the browser session only. Your ticked categories
are remembered on each device.

**Expenses someone else covers.** In **Settings → Covered by someone else**, tick
categories you don't pay for yourself, such as rent a family member pays or
costs an employer reimburses, and say who covers them. These categories still count in your totals,
but:

- The review's fact sheet marks them `[covered]` and adds **spending you
  control**, with its own average and comparison, all computed in Python.
- Lookup results include `covered_by_others` and `spending_you_control`.
- The model is told never to suggest cutting covered costs, and to judge your
  month on the spending you control.

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

### Your money: bank accounts and investments

**Liquid (cash accounts).** Add each bank account as a *Cash* holding with the
balance your bank shows today. When you add a transaction, choose which account
it was **paid from** (or **paid into**, for income). The last account you used
is picked for you, and categories someone else covers default to *Not from my
accounts*. Each account's balance is the one you entered plus the linked
income, minus the linked expenses, since then. Your **liquid** total (every
cash account together) is on the Holdings page and the Home screen.
Transactions dated before the day you entered the balance are assumed to be in
it already; ones dated in the future count once their day comes. When your
bank and the app drift apart, enter the bank's number again and it starts over
from there.

**Investments.** For stocks, crypto, and gold, add **when you bought it** and
the **average price you paid**. The Holdings page then shows, like Robinhood:

- the value, and a chart of it over **1W, 1M, 3M, YTD, 1Y**, or **All**
- the change over that period, **today's** change, and the **gain since you
  bought**, in dollars and percent, for each investment and all together

Daily closing prices come from Yahoo and are saved, refreshing at most every 12
hours. If you bought during the period, the gain counts from what you paid.
Each holding has one purchase date and an average cost, like Robinhood's
*average cost*. If you bought more later, enter your average price and the
first date; gains for periods before the later purchase then treat it as held
all along.

**AI on your investments** (Holdings page). The app works out each
investment's gains over a day, week, month, 3 months, and a year. It also adds
the S&P 500's and Nasdaq's moves (plus Bitcoin or gold if you hold them) and
this week's Yahoo Finance headlines about your holdings. The model describes
what's going on from those facts. It's told never to recommend buying, selling,
or holding anything, and never to predict prices. The headlines are labeled as
third-party text, and the model is told not to follow instructions inside them.
Like the other AI panels, results last for the browser session.

### Searching transactions

The search box on the Transactions page matches every word you type:

| Type | Finds |
|---|---|
| `coffee` | name or category contains "coffee" |
| `12` | $12.00 to $12.99 |
| `12.5` / `12.50` | $12.50 to $12.59 / exactly $12.50 |
| `>100`, `<=20` | more than $100, $20 or less |
| `50-100` | between $50 and $100 |
| `boba >5` | boba purchases over $5 |

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
moment. You can also turn an existing transaction into a recurring one: open it
and choose **Repeats**. Later charges you already have, with the same name and
within a few days of each expected date, are linked to the rule instead of
duplicated. Filling in any missing past charges is optional. Monthly rules on the 29th–31st clamp to shorter months without drifting
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
- **Design:** an Apple-style base with a layout modeled on Rocket Money.
  - Apple-style base: system grays with grouped white cards (true black in dark
    mode), Apple blue, filled input fields, a frosted top bar, segmented
    controls, and rounded rectangles instead of pill shapes.
  - Home screen: spending this month and how it compares with the same point
    last month, a running-total chart against last month, net worth, upcoming
    bills, and recent activity.
  - Every category has an icon chosen by keyword, shown on a tinted tile.
    Transactions are grouped by day and can be searched.
  - On phones, an iOS-style tab bar replaces the top navigation, and **+ Add**
    opens a sheet.
  - Every color is a CSS variable in `styles.css`. The app icon, a white "$" on
    Apple blue, is drawn by `frontend/scripts/make_icons.py`.
- **Editing:** click any transaction or holding to edit it in a sheet, which
  also holds Delete or Remove. When you change a transaction's category, the
  sheet offers to move every other transaction with the same description, which
  is handy for cleaning up imports.
- **Charts:** spending by category is a donut, with a switch to ranked bars,
  which are better for comparing similar amounts. Your five biggest categories
  of all time get the five colors, everything else is "Other", and covered
  costs form one gray "Covered" slice that you can hide. Slices keep a fixed
  order, so the colors that sit next to each other are the ones that passed the
  colorblind check, and a category doesn't jump around between months. Apple's
  own palette failed that check, because its yellow is too pale and its green
  and orange look alike to colorblind viewers. Each asset type keeps the same color
  everywhere, and every colored mark has a text label or a "Show as table"
  option, so nothing depends on color alone. Light and dark mode follow your
  system setting.
- **Your data stays out of git.** It lives outside the project, and `data/`,
  `exports/`, and any `*.db` file are gitignored as an extra guard.

## Roadmap

- [x] Phase 1: core loop, input validation, totals
- [x] Phase 2: persistence, user profile, new vs. returning user
- [x] Phase 3: cash, stocks, crypto, and gold with live prices
- [x] Phase 4: web dashboard (React + FastAPI) with charts
- [x] Phase 5: AI analyst, with monthly reviews from a local model on your own PC
- [x] Ask questions about your money, answered from exact lookups
- [x] Passcode lock, and phone access over Tailscale
- [x] Automatic backups; data moved out of the project and out of iCloud sync
- [x] Category focus with its own AI analysis, chart, and follow-up chat
- [x] Bank accounts that follow transactions (liquid total); investment gains
      over any period; AI on investments and the market
- [ ] Next: move to an always-on Raspberry Pi ([plan](docs/raspberry-pi.md))
- [ ] Later: Wake-on-LAN to turn the PC on from the app

Ideas not built yet: money in more than one currency (and a travel mode that
converts at today's rates), budgets per category, separate purchase lots per
investment, and liabilities (loans, credit cards).
