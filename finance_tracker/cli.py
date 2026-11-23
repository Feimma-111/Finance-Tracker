"""Terminal interface: menus, validated input, and formatted output.

All user interaction lives here; the rest of the package never calls input()
or print(). ``App`` takes its input and print functions as parameters so tests
can drive a whole session with scripted answers, and so a future interface
(Phase 4) can reuse the store, prices, and reports without this file.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional, Sequence, TypeVar

from . import reports
from .legacy import LEGACY_META_KEY, import_legacy_file
from .models import (
    GOLD_SYMBOL,
    AssetType,
    Holding,
    Kind,
    Transaction,
    cents_to_plain,
    format_money,
    month_of,
    parse_date,
    parse_money,
    parse_month,
)
from .paths import EXPORT_DIR, LEGACY_FILE, database_path
from .prices import PriceService, PriceUnavailable, YahooPriceProvider
from .store import Store

MAX_CATEGORY_CHOICES = 12

ASSET_HINTS = {
    AssetType.CASH: "bank accounts, savings, cash on hand",
    AssetType.STOCK: "shares or ETFs by ticker, e.g. AAPL, VOO",
    AssetType.CRYPTO: "by Yahoo symbol, e.g. BTC-USD, ETH-USD",
    AssetType.GOLD: "troy ounces, priced live",
    AssetType.OTHER: "anything you value by hand: car, collectibles",
}

T = TypeVar("T")


class Quit(Exception):
    """The user closed input (Ctrl-D) or interrupted (Ctrl-C)."""


class App:
    def __init__(
        self,
        store: Store,
        prices: PriceService,
        *,
        input_fn: Callable[[str], str] = input,
        print_fn: Callable[[str], None] = print,
        today: Callable[[], date] = date.today,
        legacy_path: Path = LEGACY_FILE,
        export_dir: Path = EXPORT_DIR,
    ) -> None:
        self.store = store
        self.prices = prices
        self.input_fn = input_fn
        self.print_fn = print_fn
        self.today = today
        self.legacy_path = Path(legacy_path)
        self.export_dir = Path(export_dir)

    # ============================================================ main loop

    def run(self) -> None:
        try:
            self._greet()
            self._menu_loop()
        except (Quit, KeyboardInterrupt):
            self.out("")
        self.out("Goodbye! Everything is already saved.")

    def _menu_loop(self) -> None:
        actions = [
            ("Add a transaction", self.add_transaction),
            ("Recent transactions", self.show_transactions),
            ("Spending by category", self.show_categories),
            ("Monthly spending", self.show_monthly),
            ("Net worth", self.show_net_worth),
            ("Manage holdings", self.manage_holdings),
            ("Export transactions to CSV", self.export_csv),
        ]
        while True:
            self.out("")
            for number, (label, _) in enumerate(actions, start=1):
                self.out(f"  {number}  {label}")
            self.out("  0  Quit")
            choice = self.ask("> ").lower()
            if choice in ("0", "q", "quit", "exit"):
                return
            if choice.isdigit() and 1 <= int(choice) <= len(actions):
                self.out("")
                actions[int(choice) - 1][1]()
            else:
                self.out("Pick a number from the menu.")

    def _greet(self) -> None:
        name = self.store.profile_name()
        if name is None:
            self.out("Welcome to your finance tracker! Looks like you're new here.")
            name = self.ask_required("What should I call you? ")
            self.store.create_profile(name)
            self.out(f"Nice to meet you, {name}. Everything you enter is saved automatically.")
        else:
            month = month_of(self.today())
            spent = sum(c for _, c in self.store.totals_by_category(Kind.EXPENSE, month=month))
            self.out(f"Welcome back, {name}. You've spent {format_money(spent)} so far this month.")
        self._offer_legacy_import()

    # ======================================================== input helpers

    def out(self, text: str = "") -> None:
        self.print_fn(text)

    def ask(self, prompt: str) -> str:
        try:
            return self.input_fn(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            raise Quit from None

    def ask_required(self, prompt: str) -> str:
        while True:
            answer = self.ask(prompt)
            if answer:
                return answer
            self.out("  This can't be blank.")

    def ask_parsed(self, prompt: str, parse: Callable[[str], T]) -> T:
        """Re-prompt until ``parse`` accepts the answer (it raises ValueError if not)."""
        while True:
            raw = self.ask(prompt)
            try:
                return parse(raw)
            except ValueError as exc:
                self.out(f"  {exc}")

    def ask_amount(self, prompt: str, *, allow_zero: bool = False) -> int:
        def parse(raw: str) -> int:
            cents = parse_money(raw)
            if cents < 0 or (cents == 0 and not allow_zero):
                raise ValueError("amount must be greater than zero")
            return cents

        return self.ask_parsed(prompt, parse)

    def ask_quantity(self, prompt: str) -> float:
        def parse(raw: str) -> float:
            try:
                value = float(raw.replace(",", ""))
            except ValueError:
                raise ValueError(f"'{raw}' isn't a number") from None
            if not value > 0 or value == float("inf"):
                raise ValueError("quantity must be greater than zero")
            return value

        return self.ask_parsed(prompt, parse)

    def ask_month(self, prompt: str) -> Optional[str]:
        return self.ask_parsed(prompt, lambda raw: parse_month(raw) if raw else None)

    def ask_yes_no(self, prompt: str, *, default: bool) -> bool:
        suffix = " [Y/n] " if default else " [y/N] "
        while True:
            answer = self.ask(prompt + suffix).lower()
            if not answer:
                return default
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            self.out("  Please answer y or n.")

    def ask_id(self, prompt: str) -> Optional[int]:
        """An ID number, or None if the user just pressed Enter."""

        def parse(raw: str) -> Optional[int]:
            if not raw:
                return None
            if not raw.isdigit():
                raise ValueError("enter an ID number, or press Enter to go back")
            return int(raw)

        return self.ask_parsed(prompt, parse)

    def pick_category(self, kind: Kind) -> str:
        shown = self.store.categories(kind)[:MAX_CATEGORY_CHOICES]
        if shown:
            self.out("  Your categories:")
            for start in range(0, len(shown), 4):
                chunk = shown[start:start + 4]
                self.out("    " + "".join(
                    f"{start + i + 1:>2}) {name[:14]:<16}" for i, name in enumerate(chunk)
                ))
        while True:
            raw = self.ask_required("Category (number or new name): " if shown else "Category: ")
            if raw.isdigit() and shown:
                index = int(raw)
                if 1 <= index <= len(shown):
                    return shown[index - 1]
                self.out(f"  Pick 1-{len(shown)}, or type a name.")
                continue
            existing = self.store.find_category(raw)
            if existing:
                return existing
            name = " ".join(raw.split())
            # Confirm brand-new names so a typo ('grocries') doesn't silently
            # split one category into two.
            if not shown or self.ask_yes_no(f"  '{name}' is a new category. Create it?", default=True):
                return name

    # ========================================================= transactions

    def add_transaction(self) -> None:
        answer = self.ask("Expense or income? [E/i] ").lower()
        kind = Kind.INCOME if answer.startswith("i") else Kind.EXPENSE
        description = self.ask_required("Description: ")
        amount = self.ask_amount("Amount: $")
        category = self.pick_category(kind)
        occurred_on = self.ask_parsed(
            "Date (YYYY-MM-DD, Enter for today): ",
            lambda raw: parse_date(raw, today=self.today()),
        )
        tx = Transaction(
            description=description,
            amount_cents=amount,
            category=category,
            occurred_on=occurred_on,
            kind=kind,
        )
        self.store.add_transaction(tx)
        self.out(
            f"Saved {kind.value}: {format_money(amount)} - {description} "
            f"({category}, {occurred_on.isoformat()})"
        )

    def show_transactions(self) -> None:
        rows = self.store.transactions(limit=25)
        if not rows:
            self.out("No transactions yet.")
            return
        self.out(f"  {'ID':>4}  {'Date':10}  {'Amount':>13}  {'Category':16}  Description")
        for tx in rows:
            sign = "+" if tx.kind is Kind.INCOME else "-"
            self.out(
                f"  {tx.id:>4}  {tx.occurred_on.isoformat()}  "
                f"{sign + format_money(tx.amount_cents):>13}  {tx.category[:16]:16}  {tx.description}"
            )
        total = self.store.transaction_count()
        if total > len(rows):
            self.out(f"  (showing the {len(rows)} most recent of {total})")

        tx_id = self.ask_id("Enter an ID to delete it, or press Enter to go back: ")
        if tx_id is None:
            return
        tx = self.store.get_transaction(tx_id)
        if tx is None:
            self.out(f"No transaction with ID {tx_id}.")
            return
        question = (
            f"Delete '{tx.description}' ({format_money(tx.amount_cents)} on "
            f"{tx.occurred_on.isoformat()})? This can't be undone."
        )
        if self.ask_yes_no(question, default=False):
            self.store.delete_transaction(tx_id)
            self.out("Deleted.")

    # ============================================================== reports

    def show_categories(self) -> None:
        month = self.ask_month("Month (YYYY-MM), or Enter for all time: ")
        self.out("")
        self._print_category_breakdown(month)

    def _print_category_breakdown(self, month: Optional[str]) -> None:
        period = month or "all time"
        rows = self.store.totals_by_category(Kind.EXPENSE, month=month)
        income = sum(c for _, c in self.store.totals_by_category(Kind.INCOME, month=month))
        if not rows and not income:
            self.out(f"Nothing recorded for {period}.")
            return
        spent = sum(c for _, c in rows)
        self.out(f"Spending for {period}: {format_money(spent)}")
        largest = rows[0][1] if rows else 0
        for name, cents in rows:
            share = 100 * cents / spent
            self.out(
                f"  {name[:16]:16} {format_money(cents):>13} {share:5.1f}%  "
                f"{reports.bar(cents, largest)}"
            )
        if income:
            self.out(f"Income: {format_money(income)}    Net: {format_money(income - spent)}")

    def show_monthly(self) -> None:
        report = reports.monthly_report(
            self.store.totals_by_month(Kind.EXPENSE), current_month=month_of(self.today())
        )
        if not report.rows:
            self.out("No spending recorded yet.")
            return
        largest = max(row.total_cents for row in report.rows)
        self.out("Monthly spending")
        for row in report.rows:
            self.out(
                f"  {row.month}  {format_money(row.total_cents):>13}  "
                f"{reports.bar(row.total_cents, largest):24}  {row.label}"
            )
        if report.mean_cents is not None:
            line = f"Average month: {format_money(round(report.mean_cents))}"
            if report.stdev_cents is not None:
                line += f"    Typical swing: +/- {format_money(round(report.stdev_cents))}"
            self.out(line)

        month = self.ask_month("Enter a month (YYYY-MM) for its breakdown, or press Enter to go back: ")
        if month:
            self.out("")
            self._print_category_breakdown(month)

    # ============================================================ net worth

    def show_net_worth(self) -> None:
        holdings = self.store.holdings()
        if not holdings:
            self.out("No holdings yet. Add cash, stocks, crypto, or gold under 'Manage holdings'.")
            return
        if any(h.asset_type.is_market_priced for h in holdings):
            self.out("Fetching prices...")
        report = reports.value_holdings(holdings, self.prices.quote)

        self.out(f"  {'Holding':20} {'Type':7} {'Quantity':>12} {'Price':>12} {'Value':>15}")
        for line in report.lines:
            h = line.holding
            quantity = _format_quantity(h.quantity) if h.asset_type.is_market_priced else ""
            price = f"${line.unit_price:,.2f}" if line.unit_price is not None else ""
            value = format_money(line.value_cents) if line.value_cents is not None else "n/a"
            self.out(f"  {h.name[:20]:20} {h.asset_type.value:7} {quantity:>12} {price:>12} {value:>15}")
            if line.note:
                self.out(f"      ({line.note})")

        suffix = "" if report.complete else "   (incomplete: some holdings couldn't be priced)"
        self.out(f"Net worth: {format_money(report.total_cents)}{suffix}")

        # Only record complete valuations, so the history isn't skewed by outages.
        if report.complete:
            previous = self.store.latest_snapshot_before(self.today())
            self.store.record_net_worth(self.today(), report.total_cents)
            if previous:
                day, cents = previous
                change = report.total_cents - cents
                sign = "+" if change >= 0 else ""
                self.out(f"Change since {day.isoformat()}: {sign}{format_money(change)}")

    def manage_holdings(self) -> None:
        while True:
            holdings = self.store.holdings()
            if holdings:
                self.out("Your holdings:")
                for h in holdings:
                    self.out(f"  {h.id:>3}  {_describe_holding(h)}")
            else:
                self.out("You don't have any holdings yet.")
            choice = self.ask("[a]dd, [u]pdate, [r]emove, or press Enter to go back: ").lower()
            if not choice:
                return
            if choice.startswith("a"):
                self._add_holding()
            elif choice.startswith("u"):
                self._update_holding()
            elif choice.startswith("r"):
                self._remove_holding()
            else:
                self.out("Choose a, u, or r, or press Enter.")
            self.out("")

    def _add_holding(self) -> None:
        types: List[AssetType] = list(AssetType)
        for number, asset_type in enumerate(types, start=1):
            self.out(f"  {number}  {asset_type.value:7} {ASSET_HINTS[asset_type]}")
        index = self.ask_parsed("Type: ", lambda raw: _pick_index(raw, len(types)))
        asset_type = types[index]

        if asset_type is AssetType.GOLD:
            quantity = self.ask_quantity("How many troy ounces? ")
            holding = Holding(AssetType.GOLD, "Gold", quantity, symbol=GOLD_SYMBOL)
        elif asset_type.is_market_priced:
            symbol = self.ask_required("Symbol: ").upper()
            if not self._symbol_checks_out(symbol):
                return
            quantity = self.ask_quantity("Quantity: ")
            name = self.ask(f"Name (Enter for {symbol}): ") or symbol
            holding = Holding(asset_type, name, quantity, symbol=symbol)
        else:
            example = "Checking" if asset_type is AssetType.CASH else "Car"
            name = self.ask_required(f"Name (e.g. {example}): ")
            value = self.ask_amount("Current value: $", allow_zero=True)
            holding = Holding(asset_type, name, manual_value_cents=value)

        self.store.add_holding(holding)
        self.out(f"Added {_describe_holding(holding)}.")

    def _symbol_checks_out(self, symbol: str) -> bool:
        self.out(f"Looking up {symbol}...")
        try:
            quote = self.prices.quote(symbol)
        except PriceUnavailable as exc:
            self.out(f"  Couldn't get a price: {exc}")
            return self.ask_yes_no("  Add it anyway?", default=False)
        self.out(f"  {symbol} is at {quote.price:,.2f} {quote.currency}.")
        return True

    def _update_holding(self) -> None:
        holding_id = self.ask_id("ID to update (Enter to cancel): ")
        if holding_id is None:
            return
        holding = self.store.get_holding(holding_id)
        if holding is None:
            self.out(f"No holding with ID {holding_id}.")
            return
        if holding.asset_type.is_market_priced:
            quantity = self.ask_quantity(f"New quantity (currently {_format_quantity(holding.quantity)}): ")
            self.store.update_holding(holding_id, quantity=quantity)
        else:
            current = format_money(holding.manual_value_cents or 0)
            value = self.ask_amount(f"New value (currently {current}): $", allow_zero=True)
            self.store.update_holding(holding_id, manual_value_cents=value)
        self.out("Updated.")

    def _remove_holding(self) -> None:
        holding_id = self.ask_id("ID to remove (Enter to cancel): ")
        if holding_id is None:
            return
        holding = self.store.get_holding(holding_id)
        if holding is None:
            self.out(f"No holding with ID {holding_id}.")
            return
        if self.ask_yes_no(f"Remove {_describe_holding(holding)}?", default=False):
            self.store.remove_holding(holding_id)
            self.out("Removed.")

    # =============================================================== export

    def export_csv(self) -> None:
        rows = self.store.transactions()
        if not rows:
            self.out("No transactions to export.")
            return
        self.export_dir.mkdir(parents=True, exist_ok=True)
        path = self.export_dir / f"transactions-{self.today().isoformat()}.csv"
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "date", "kind", "category", "description", "amount"])
            for tx in reversed(rows):  # oldest first reads naturally in a spreadsheet
                writer.writerow([
                    tx.id,
                    tx.occurred_on.isoformat(),
                    tx.kind.value,
                    tx.category,
                    tx.description,
                    cents_to_plain(tx.amount_cents),
                ])
        self.out(f"Exported {len(rows)} transactions to {path}")

    # =============================================================== legacy

    def _offer_legacy_import(self) -> None:
        if not self.legacy_path.exists() or self.store.get_meta(LEGACY_META_KEY) is not None:
            return
        self.out(f"Found a save file from the first version of this app ({self.legacy_path.name}).")
        if self.ask_yes_no("Import its transactions?", default=True):
            self.import_legacy(self.legacy_path)
        else:
            self.store.set_meta(LEGACY_META_KEY, "declined")
            self.out("Okay. You can import it later with: python main.py --import-legacy")

    def import_legacy(self, path: Path) -> None:
        if self.store.get_meta(LEGACY_META_KEY) == "done":
            self.out("That file has already been imported.")
            return
        if not Path(path).exists():
            self.out(f"No file at {path}.")
            return
        imported, problems = import_legacy_file(self.store, path)
        self.out(f"Imported {imported} transaction(s). The old file was left untouched.")
        for problem in problems:
            self.out(f"  skipped {problem}")


# ===================================================================== helpers


def _pick_index(raw: str, count: int) -> int:
    if raw.isdigit() and 1 <= int(raw) <= count:
        return int(raw) - 1
    raise ValueError(f"pick a number from 1 to {count}")


def _format_quantity(quantity: float) -> str:
    return f"{quantity:,.6f}".rstrip("0").rstrip(".")


def _describe_holding(h: Holding) -> str:
    if h.asset_type.is_market_priced:
        unit = {AssetType.GOLD: " oz", AssetType.STOCK: " shares"}.get(h.asset_type, "")
        return f"{h.name} - {_format_quantity(h.quantity)}{unit} ({h.symbol})"
    return f"{h.name} - {format_money(h.manual_value_cents or 0)} ({h.asset_type.value})"


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Personal finance and portfolio tracker.")
    parser.add_argument(
        "--db",
        default=database_path(),
        help="path to the SQLite database (default: data/finance.db)",
    )
    parser.add_argument(
        "--import-legacy",
        nargs="?",
        const=str(LEGACY_FILE),
        metavar="FILE",
        help="import transactions from the old JSON-lines save file, then exit",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="start the web dashboard instead of the terminal app",
    )
    parser.add_argument("--port", type=int, default=8000, help="port for --web (default: 8000)")
    args = parser.parse_args(argv)

    if args.web:
        try:
            from .api import serve
        except ImportError:
            print(
                "The web dashboard needs a few packages. Install them with:\n"
                "  .venv/bin/python -m pip install -r requirements.txt\n"
                "then run:  .venv/bin/python main.py --web"
            )
            raise SystemExit(1)
        serve(args.db, port=args.port)
        return

    with Store(args.db) as store:
        app = App(store, PriceService(store, YahooPriceProvider()))
        if args.import_legacy:
            app.import_legacy(Path(args.import_legacy))
        else:
            app.run()
