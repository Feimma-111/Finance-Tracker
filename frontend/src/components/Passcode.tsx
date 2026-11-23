import { useEffect, useRef, useState } from "react";
import { api } from "../api";

const LENGTH = 6;
const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "⌫"];

/**
 * iPhone-style passcode screen: six dots and a number pad (or type on a
 * keyboard). ``mode`` "setup" asks twice to choose a passcode; "unlock"
 * checks it with the server.
 */
export function PasscodeScreen({ mode, onDone }: { mode: "setup" | "unlock"; onDone: () => void }) {
  const [digits, setDigits] = useState("");
  const [first, setFirst] = useState<string | null>(null); // setup: the first entry, awaiting confirmation
  const [message, setMessage] = useState<string | null>(null);
  const [shake, setShake] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const title =
    mode === "unlock" ? "Enter passcode" : first === null ? "Create a passcode" : "Confirm your passcode";
  const subtitle =
    mode === "unlock"
      ? "Your finance tracker is locked."
      : first === null
        ? "Choose 6 digits. You'll enter them to open the app on each device."
        : "Enter the same 6 digits again.";

  function fail(text: string) {
    setMessage(text);
    setShake(true);
    setDigits("");
    window.setTimeout(() => setShake(false), 450);
  }

  async function submit(code: string) {
    if (mode === "setup") {
      if (first === null) {
        setFirst(code);
        setDigits("");
        setMessage(null);
        return;
      }
      if (code !== first) {
        setFirst(null);
        fail("Those didn't match. Let's start over.");
        return;
      }
    }
    setBusy(true);
    try {
      if (mode === "setup") await api.setupPasscode(code);
      else await api.login(code);
      onDone();
    } catch (e) {
      fail((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function press(key: string) {
    if (busy) return;
    if (key === "⌫") {
      setDigits((d) => d.slice(0, -1));
      return;
    }
    if (!/^[0-9]$/.test(key) || digits.length >= LENGTH) return;
    const next = digits + key;
    setDigits(next);
    if (next.length === LENGTH) submit(next);
  }

  // Typing on a keyboard works too (digits and Backspace).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.target === input.current) return; // the hidden field handles its own typing
      if (/^[0-9]$/.test(event.key)) press(event.key);
      else if (event.key === "Backspace") press("⌫");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="center-screen lock-screen">
      <div className="lock">
        <img className="lock-logo" src="/icon-192.png" alt="" width={64} height={64} />
        <h1>{title}</h1>
        <p className="subtle">{subtitle}</p>
        <div className={`dots ${shake ? "shake" : ""}`} role="status" aria-label={`${digits.length} of ${LENGTH} digits entered`}>
          {Array.from({ length: LENGTH }, (_, i) => (
            <span key={i} className={i < digits.length ? "filled" : ""} />
          ))}
        </div>
        <p className="lock-message" aria-live="assertive">{message ?? " "}</p>
        {/* Hidden field so phones can also use their own number keyboard / password managers. */}
        <input
          ref={input}
          className="visually-hidden"
          type="password"
          inputMode="numeric"
          autoComplete={mode === "setup" ? "new-password" : "current-password"}
          aria-label="Passcode"
          value={digits}
          maxLength={LENGTH}
          onChange={(e) => {
            const value = e.target.value.replace(/[^0-9]/g, "").slice(0, LENGTH);
            setDigits(value);
            if (value.length === LENGTH) submit(value);
          }}
        />
        <div className="keypad">
          {KEYS.map((key, i) =>
            key ? (
              <button
                key={i}
                type="button"
                className={key === "⌫" ? "key key-delete" : "key"}
                onClick={() => press(key)}
                disabled={busy}
                aria-label={key === "⌫" ? "Delete" : key}
              >
                {key}
              </button>
            ) : (
              <span key={i} />
            ),
          )}
        </div>
      </div>
    </div>
  );
}
