import { useEffect, useState, type FormEvent } from "react";
import { api, type Settings as SettingsData } from "./api";
import { applyTheme, useAsync, type ThemeChoice } from "./hooks";
import { Dashboard } from "./pages/Dashboard";
import { Holdings } from "./pages/Holdings";
import { Settings } from "./pages/Settings";
import { Transactions } from "./pages/Transactions";

type Page = "dashboard" | "transactions" | "holdings" | "settings";
const PAGES: { id: Page; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "transactions", label: "Transactions" },
  { id: "holdings", label: "Holdings" },
  { id: "settings", label: "Settings" },
];

// The page lives in the URL hash (#/holdings), so refreshing or bookmarking
// keeps your place without needing a router library.
function pageFromHash(): Page {
  const id = window.location.hash.replace(/^#\/?/, "");
  return PAGES.some((p) => p.id === id) ? (id as Page) : "dashboard";
}

export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [profileVersion, setProfileVersion] = useState(0);
  // Bumped after any change (new transaction, edited holding...). Every screen
  // lists it as a dependency, so all of them reload their data together.
  const [version, setVersion] = useState(0);
  const onChanged = () => setVersion((v) => v + 1);

  const profile = useAsync(api.profile, [profileVersion]);

  // Settings live on the server (so every device gets the same theme);
  // applyTheme also caches the choice so the next page load starts right.
  const [settings, setSettings] = useState<SettingsData>();
  useEffect(() => {
    api.settings().then((s) => {
      setSettings(s);
      applyTheme(s.theme);
    }, () => {});
  }, []);

  async function changeTheme(theme: ThemeChoice) {
    applyTheme(theme); // instant; then save
    setSettings((s) => (s ? { ...s, theme } : s));
    try {
      setSettings(await api.saveSettings({ theme }));
    } catch {
      // keep the local choice; it'll be retried next time it's changed
    }
  }

  useEffect(() => {
    const update = () => setPage(pageFromHash());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);

  if (profile.error && !profile.data) {
    return (
      <div className="center-screen">
        <div className="card welcome">
          <h1>Can't reach the server</h1>
          <p>{profile.error}</p>
          <p className="hint">Start it from the project folder with <code>.venv/bin/python main.py --web</code>, then reload.</p>
        </div>
      </div>
    );
  }
  if (!profile.data) return <div className="center-screen subtle">Loading…</div>;
  if (!profile.data.name) return <Welcome onDone={() => setProfileVersion((v) => v + 1)} />;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">$</span>
          Finance Tracker
        </div>
        <nav className="nav" aria-label="Main">
          {PAGES.map((p) => (
            <a key={p.id} href={`#/${p.id}`} className={page === p.id ? "active" : undefined} aria-current={page === p.id ? "page" : undefined}>
              {p.label}
            </a>
          ))}
        </nav>
        <span className="greeting">Hi, {profile.data.name}</span>
      </header>
      <main>
        {page === "dashboard" && <Dashboard version={version} onChanged={onChanged} />}
        {page === "transactions" && <Transactions version={version} onChanged={onChanged} />}
        {page === "holdings" && <Holdings version={version} onChanged={onChanged} />}
        {page === "settings" && (
          <Settings
            name={profile.data.name}
            settings={settings}
            onTheme={changeTheme}
            onRenamed={() => setProfileVersion((v) => v + 1)}
            onSettings={setSettings}
            onDataChanged={onChanged}
          />
        )}
      </main>
    </div>
  );
}

function Welcome({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await api.createProfile(name);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="center-screen">
      <form className="card welcome form" onSubmit={submit}>
        <div>
          <h1>Welcome to your finance tracker</h1>
          <p>Track spending, income, and everything you own in one place. Your data stays on this computer.</p>
        </div>
        <label className="field">
          <span>What should we call you?</span>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
        </label>
        {error && <p className="message error">{error}</p>}
        <button className="btn btn-primary" type="submit">Get started</button>
      </form>
    </div>
  );
}
