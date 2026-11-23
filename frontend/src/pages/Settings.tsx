import { useEffect, useState, type FormEvent } from "react";
import { api, BACKUP_DOWNLOAD_URL, CSV_EXPORT_URL, LOCKED_EVENT, type AiStatus, type Settings as SettingsData } from "../api";
import { CsvImport } from "../components/CsvImport";
import { useAsync, type ThemeChoice } from "../hooks";

/** Where the AI analyst lives: Ollama's address on your PC, and which model to use. */
function AiSettings({ settings, onSaved }: { settings: SettingsData; onSaved: (s: SettingsData) => void }) {
  const [url, setUrl] = useState(settings.ai_url);
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function check() {
    setChecking(true);
    try {
      setStatus(await api.aiStatus());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChecking(false);
    }
  }

  useEffect(() => {
    if (settings.ai_url) check();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const saved = await api.saveSettings({ ai_url: url });
      setUrl(saved.ai_url);
      onSaved(saved);
      await check();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function chooseModel(model: string) {
    try {
      onSaved(await api.saveSettings({ ai_model: model }));
      await check();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="setting-row">
      <h3>AI analyst</h3>
      <span className="hint">
        Reviews are written by Ollama on your own PC, reached over Tailscale. Enter the PC's Tailscale address,
        e.g. <code>http://100.101.102.103:11434</code>. Leave it blank to turn the AI off.
      </span>
      <form className="inline-form" onSubmit={save}>
        <input type="text" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://100.x.y.z:11434" aria-label="Ollama address" />
        <button className="btn" type="submit">Save &amp; test</button>
      </form>
      {error && <span className="message error">{error}</span>}
      {checking && <span className="subtle">Checking…</span>}
      {!checking && status?.configured && (
        status.reachable ? (
          <>
            <span className="ai-status online">● Connected to {status.url}</span>
            {status.models.length > 0 && (
              <label className="field" style={{ maxWidth: 320 }}>
                <span>Model</span>
                <select value={status.model ?? ""} onChange={(e) => chooseModel(e.target.value)}>
                  {status.models.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </label>
            )}
          </>
        ) : (
          <span className="ai-status offline">
            ● Can't reach {status.url}. Is the PC on, with Ollama and Tailscale running?{" "}
            <button className="btn-link" type="button" onClick={check}>Try again</button>
          </span>
        )
      )}
    </section>
  );
}

/** Automatic backups: when the last one ran, back up now, or download a copy. */
function BackupSettings() {
  const [refresh, setRefresh] = useState(0);
  const list = useAsync(api.backups, [refresh]);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  async function backupNow() {
    setBusy(true);
    try {
      const made = await api.backupNow();
      setMessage({ text: `Backed up as ${made.name}.`, error: false });
      setRefresh((r) => r + 1);
    } catch (e) {
      setMessage({ text: (e as Error).message, error: true });
    } finally {
      setBusy(false);
    }
  }

  const latest = list.data?.backups[0];
  return (
    <section className="setting-row">
      <h3>Backups</h3>
      <span className="hint">
        Your data is backed up automatically once a day, and before every import or restore. The last 30 daily
        backups are kept. These copies are on this Mac, so also keep one somewhere else (an external drive, or
        Download a copy).
      </span>
      {list.data && (
        <span className="subtle">
          {latest
            ? `Last backup: ${new Date(latest.created).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} · ${list.data.backups.length} saved`
            : "No backups yet."}
        </span>
      )}
      {list.data && <code className="path">{list.data.location}</code>}
      <div className="inline-form">
        <button className="btn" type="button" onClick={backupNow} disabled={busy}>Back up now</button>
        <a className="btn" href={BACKUP_DOWNLOAD_URL} download>Download a copy</a>
      </div>
      {message && <span className={`message ${message.error ? "error" : "success"}`}>{message.text}</span>}
      <span className="hint">
        To restore one, run on the Mac: <code>.venv/bin/python main.py --restore-backup finance-YYYY-MM-DD.db</code>.
        Your current data is backed up first, so restoring can't lose anything.
      </span>
    </section>
  );
}

/** Change the passcode, or lock this device now. */
function PasscodeSettings() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const digitsOnly = (value: string) => value.replace(/[^0-9]/g, "").slice(0, 6);

  async function change(event: FormEvent) {
    event.preventDefault();
    if (next !== confirm) {
      setMessage({ text: "The new passcodes don't match.", error: true });
      return;
    }
    setBusy(true);
    try {
      const result = await api.changePasscode(current, next);
      const others = result.signed_out_devices;
      setMessage({
        text: `Passcode changed.${others ? ` Signed out ${others} other device${others === 1 ? "" : "s"}.` : ""}`,
        error: false,
      });
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (e) {
      setMessage({ text: (e as Error).message, error: true });
    } finally {
      setBusy(false);
    }
  }

  async function lockNow() {
    await api.logout().catch(() => {});
    window.dispatchEvent(new Event(LOCKED_EVENT));
  }

  const passcodeField = (label: string, value: string, set: (v: string) => void, autoComplete: string) => (
    <label className="field">
      <span>{label}</span>
      <input
        type="password"
        inputMode="numeric"
        autoComplete={autoComplete}
        maxLength={6}
        value={value}
        onChange={(e) => set(digitsOnly(e.target.value))}
        required
        minLength={6}
      />
    </label>
  );

  return (
    <section className="setting-row">
      <h3>Passcode</h3>
      <span className="hint">
        Each device asks for your 6-digit passcode, then stays signed in for 30 days. Forgot it? On the Mac, run{" "}
        <code>.venv/bin/python main.py --reset-passcode</code> and you'll choose a new one.
      </span>
      <form className="form" onSubmit={change} style={{ maxWidth: 420 }}>
        {passcodeField("Current passcode", current, setCurrent, "current-password")}
        <div className="field-row">
          {passcodeField("New passcode", next, setNext, "new-password")}
          {passcodeField("Confirm new", confirm, setConfirm, "new-password")}
        </div>
        <div className="inline-form">
          <button className="btn" type="submit" disabled={busy || current.length < 6 || next.length < 6}>
            Change passcode
          </button>
          <button className="btn btn-danger" type="button" onClick={lockNow}>Lock now</button>
        </div>
        {message && <span className={`message ${message.error ? "error" : "success"}`}>{message.text}</span>}
        <span className="hint">Changing it signs out your other devices.</span>
      </form>
    </section>
  );
}

/** Categories someone else pays for, so the AI doesn't suggest cutting them. */
function CoveredSettings({ settings, onSaved }: { settings: SettingsData; onSaved: (s: SettingsData) => void }) {
  const categories = useAsync(() => api.categories("expense"), []);
  const [note, setNote] = useState(settings.covered_note);
  const [error, setError] = useState<string | null>(null);
  const covered = new Set(settings.covered_categories);

  async function save(patch: Partial<Pick<SettingsData, "covered_categories" | "covered_note">>) {
    setError(null);
    try {
      onSaved(await api.saveSettings(patch));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function toggle(name: string) {
    const next = new Set(covered);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    save({ covered_categories: [...next] });
  }

  return (
    <section className="setting-row">
      <h3>Covered by someone else</h3>
      <span className="hint">
        Pick expenses you don't pay for yourself, like rent or tuition your parents cover. They still count in your
        totals, but the AI won't suggest cutting them and judges your month on the spending you control.
      </span>
      {categories.data?.length ? (
        <div className="toggle-list" role="group" aria-label="Covered categories">
          {categories.data.map((name) => (
            <label key={name} className={`toggle ${covered.has(name) ? "on" : ""}`}>
              <input type="checkbox" checked={covered.has(name)} onChange={() => toggle(name)} />
              {name}
            </label>
          ))}
        </div>
      ) : (
        <span className="subtle">Your categories will show up here once you've added some transactions.</span>
      )}
      <label className="field" style={{ maxWidth: 380 }}>
        <span>Who covers them?</span>
        <input
          type="text"
          value={note}
          placeholder="My parents pay for these"
          maxLength={120}
          onChange={(e) => setNote(e.target.value)}
          onBlur={() => note !== settings.covered_note && save({ covered_note: note })}
        />
      </label>
      {error && <span className="message error">{error}</span>}
    </section>
  );
}

const THEMES: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "Match system" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function Settings({
  name,
  settings,
  onTheme,
  onRenamed,
  onSettings,
  onDataChanged,
}: {
  name: string;
  settings: SettingsData | undefined;
  onTheme: (theme: ThemeChoice) => void;
  onRenamed: () => void;
  onSettings: (settings: SettingsData) => void;
  onDataChanged: () => void;
}) {
  const [draftName, setDraftName] = useState(name);
  const [nameMessage, setNameMessage] = useState<{ text: string; error: boolean } | null>(null);

  async function rename(event: FormEvent) {
    event.preventDefault();
    try {
      await api.renameProfile(draftName);
      setNameMessage({ text: "Saved.", error: false });
      onRenamed();
    } catch (e) {
      setNameMessage({ text: (e as Error).message, error: true });
    }
  }

  return (
    <>
      <h1 className="page-title">Settings</h1>
      <div className="card settings">
        <section className="setting-row">
          <h3>Appearance</h3>
          <div className="segmented" role="group" aria-label="Theme">
            {THEMES.map((t) => (
              <button
                key={t.value}
                type="button"
                aria-pressed={(settings?.theme ?? "system") === t.value}
                onClick={() => onTheme(t.value)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <span className="hint">"Match system" follows your device's light or dark mode.</span>
        </section>

        <PasscodeSettings />

        <section className="setting-row">
          <h3>Your name</h3>
          <form className="inline-form" onSubmit={rename}>
            <input type="text" value={draftName} onChange={(e) => setDraftName(e.target.value)} required aria-label="Your name" />
            <button className="btn" type="submit" disabled={!draftName.trim() || draftName.trim() === name}>
              Save
            </button>
          </form>
          {nameMessage && <span className={`message ${nameMessage.error ? "error" : "success"}`}>{nameMessage.text}</span>}
        </section>

        {settings && <AiSettings settings={settings} onSaved={onSettings} />}
        {settings && <CoveredSettings settings={settings} onSaved={onSettings} />}

        <CsvImport onImported={onDataChanged} />

        <BackupSettings />

        <section className="setting-row">
          <h3>Your data</h3>
          <span className="hint">
            Everything is stored in this one file. It's never sent to a bank or finance company. The AI runs on your
            own PC, and only ticker symbols (never amounts) go to the price service.
          </span>
          {settings && <code className="path">{settings.database}</code>}
          <div>
            <a className="btn btn-small" href={CSV_EXPORT_URL} download>Export transactions as CSV</a>
          </div>
        </section>
      </div>
    </>
  );
}
