import type { Transaction } from "./api";

/*
 * Transaction search. The query is split into words, and a transaction must
 * match every word:
 *
 *   coffee        name or category contains "coffee"
 *   12            amount is $12.00 to $12.99
 *   12.5          amount is $12.50 to $12.59
 *   12.50 / $12.50  exactly $12.50
 *   >100  >=100  <20  <=20   bigger / smaller than
 *   50-100        between $50 and $100 (inclusive)
 *
 * So "boba >5" finds boba purchases over $5.
 */

type Test = (t: Transaction) => boolean;

const NUMBER = String.raw`\$?(\d+(?:\.\d{0,2})?)`;
const COMPARE = new RegExp(String.raw`^(<=|>=|<|>)${NUMBER}$`);
const RANGE = new RegExp(String.raw`^${NUMBER}-${NUMBER}$`);
const AMOUNT = new RegExp(String.raw`^${NUMBER}$`);

const cents = (text: string) => Math.round(parseFloat(text) * 100);

function amountTest(word: string): Test | null {
  const compare = COMPARE.exec(word);
  if (compare) {
    const [, op, value] = compare;
    const limit = cents(value);
    return (t) =>
      op === ">" ? t.amount_cents > limit
      : op === ">=" ? t.amount_cents >= limit
      : op === "<" ? t.amount_cents < limit
      : t.amount_cents <= limit;
  }
  const range = RANGE.exec(word);
  if (range) {
    const [low, high] = [cents(range[1]), cents(range[2])].sort((a, b) => a - b);
    return (t) => t.amount_cents >= low && t.amount_cents <= high;
  }
  const amount = AMOUNT.exec(word);
  if (amount) {
    const text = amount[1];
    if (!text.includes(".")) {
      const dollars = Number(text);
      return (t) => Math.floor(t.amount_cents / 100) === dollars;
    }
    // "12.5" -> 12.50-12.59; "12.50" -> exactly 12.50
    return (t) => (t.amount_cents / 100).toFixed(2).startsWith(text);
  }
  return null;
}

/** A function telling whether a transaction matches ``query`` (everything matches an empty query). */
export function transactionMatcher(query: string): Test {
  // "50 - 100" and "> 100" -> "50-100" and ">100", so they stay one word.
  const normalized = query
    .trim()
    .toLowerCase()
    .replace(/,/g, "")
    .replace(/(\d)\s*(?:-|to)\s*\$?(\d)/g, "$1-$2")
    .replace(/(<=|>=|<|>)\s+/g, "$1");
  const tests: Test[] = normalized.split(/\s+/).filter(Boolean).map((word) => {
    const amount = amountTest(word);
    if (amount) return amount;
    return (t) => t.description.toLowerCase().includes(word) || t.category.toLowerCase().includes(word);
  });
  return (t) => tests.every((test) => test(t));
}
