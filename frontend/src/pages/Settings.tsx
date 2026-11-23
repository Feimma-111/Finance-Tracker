import { useState, type FormEvent } from "react";
import { api, CSV_EXPORT_URL, type Settings as SettingsData } from "../api";
import type { ThemeChoice } from "../hooks";

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
}: {
  name: string;
  settings: SettingsData | undefined;
  onTheme: (theme: ThemeChoice) => void;
  onRenamed: () => void;
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
