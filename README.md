# Finance Tracker

A terminal app for tracking spending and income, and for following your net worth
across cash, stocks, crypto, and gold with live market prices.

It uses only the Python standard library, so there's nothing to install.

## Run it

```bash
python3 main.py
```

On the first run it asks your name and creates `data/finance.db`. On later runs it
welcomes you back. Every change is saved the moment you make it, so there's no
save step.

Options:

```bash
python3 main.py --db path/to/other.db      # use a different database file
python3 main.py --import-legacy            # import the old information_save_file
```

## Run the tests

```bash
python3 -m unittest discover -s tests -t .
```

## What it does

| Menu | |
|---|---|
| Add a transaction | Expense or income, with amount, category, and date. Pick a category you've used before by number; new names are confirmed so typos don't split a category in two. |
| Recent transactions | The last 25 entries. Enter an ID to delete one. |
| Spending by category | All time or a single month, with share-of-total bars and income vs. net. |
| Monthly spending | The last 12 months. Each month is flagged when it's more than 1 standard deviation from your average. The current month is marked *in progress* and left out of the average. |
| Net worth | Values every holding at live prices, totals them, and records a daily snapshot. |
| Manage holdings | Add, update, or remove cash accounts, stocks/ETFs, crypto, gold (troy ounces), or other items you value by hand. |
| Export to CSV | Writes all transactions to `exports/` so you can open them in a spreadsheet. |

## Layout

```
main.py                     entry point
finance_tracker/
  models.py                 Transaction / Holding dataclasses, money and date parsing
  store.py                  SQLite schema, migrations, and every query
  prices.py                 live prices (Yahoo Finance) with an offline cache
  reports.py                monthly stats, net-worth math, text bars (pure functions)
  cli.py                    menus and validated input; the only file that prints
  legacy.py                 importer for the original JSON-lines save file
tests/                      unit tests plus scripted end-to-end terminal sessions
legacy/main_v1.py           the original single-file version
```

## Design decisions

- **SQLite, not a JSON list.** The old version kept everything in a list in memory
  and rewrote the whole file on every save. SQLite keeps data on disk and writes
  only what changed. Reports run as `GROUP BY` queries inside the database.
  Category names are stored once, and an index on the date keeps lookups fast as
  history grows.
- **Money is integer cents.** Floats can't store most decimal amounts exactly
  (`0.1 + 0.2 != 0.3`). Cents are exact.
- **Dates are ISO strings on disk and `date` objects in code.** ISO strings sort
  correctly as text. Conversion happens only at the storage boundary.
- **Prices are cached for 15 minutes.** If the price service is down or you're
  offline, the app uses the last known price and labels it as stale instead of
  crashing. A net-worth snapshot is only recorded when every holding could be
  priced, so outages don't distort your history.
- **Swappable price source.** Yahoo's endpoint is free but unofficial. Anything
  with a `fetch(symbol) -> (price, currency)` method can replace it.
- **Schema migrations.** `PRAGMA user_version` tracks the schema version. Future
  changes are added as new entries in `MIGRATIONS`, so existing data upgrades in
  place.
- **Your data stays out of git.** `data/`, `exports/`, and any `*.db` file are
  gitignored.

## Roadmap

- [x] Phase 1: core loop, input validation, totals
- [x] Phase 2: persistence, user profile, new vs. returning user
- [x] Phase 3: cash, stocks, crypto, and gold with live prices
- [ ] Phase 4: graphical interface (web dashboard with pie and line charts).
  `store.py` and `reports.py` already return plain data, so a dashboard only
  needs a new front end. `net_worth_history()` is ready for a line chart.
- [ ] Phase 5: AI analyst. Still to decide: a local model (e.g. via Ollama) keeps
  financial data on your machine, while a hosted API is easier to set up. Either
  way, send a summary, not raw transactions.

Ideas not built yet: recurring transactions (rent, subscriptions), budgets per
category, cost basis and gain/loss for investments, liabilities (loans, credit
cards), and non-USD holdings.
