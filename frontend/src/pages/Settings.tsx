import { useEffect, useState, type FormEvent } from "react";
import { api, CSV_EXPORT_URL, type AiStatus, type Settings as SettingsData } from "../api";
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

        <section className="setting-row">
          <h3>Your data</h3>
          <span className="hint">
            Everything is stored in one file on this computer. Back it up by copying it somewhere safe.
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
