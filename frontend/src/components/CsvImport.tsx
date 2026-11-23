import { useState, type ChangeEvent } from "react";
import { api, type ImportMapping, type ImportOptions, type ImportPreview } from "../api";
import { dateLabel, money } from "../format";

const MAX_BYTES = 5_000_000;
const DEFAULT_OPTIONS: ImportOptions = { date_format: "auto", positive_is: "income", default_category: "Uncategorized" };

/**
 * Import a bank export or spreadsheet. Step 1 reads the file and shows how it
 * would be imported; every choice the app guessed can be changed and the
 * preview updates. Step 2 saves the new rows (duplicates are skipped).
 */
export function CsvImport({ onImported }: { onImported: () => void }) {
  const [fileName, setFileName] = useState("");
  const [csv, setCsv] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<ImportMapping | null>(null);
  const [options, setOptions] = useState<ImportOptions>(DEFAULT_OPTIONS);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);

  function reset() {
    setCsv(null);
    setPreview(null);
    setMapping(null);
    setOptions(DEFAULT_OPTIONS);
    setFileName("");
  }

  async function refresh(text: string, nextMapping?: ImportMapping, nextOptions: ImportOptions = options) {
    setBusy(true);
    try {
      const result = await api.importPreview(text, nextMapping, nextOptions);
      setPreview(result);
      setMapping(result.mapping);
      // Show the format actually used, so the dropdown reflects "auto"'s choice.
      if (result.date_format && nextOptions.date_format === "auto") {
        setOptions({ ...nextOptions, date_format: result.date_format });
      }
    } catch (e) {
      setMessage({ text: (e as Error).message, error: true });
      reset();
    } finally {
      setBusy(false);
    }
  }

  async function pickFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // let the same file be picked again later
    if (!file) return;
    setMessage(null);
    if (file.size > MAX_BYTES) {
      setMessage({ text: "That file is over 5 MB. Split it into smaller files.", error: true });
      return;
    }
    const text = await file.text();
    setFileName(file.name);
    setCsv(text);
    setOptions(DEFAULT_OPTIONS);
    await refresh(text, undefined, DEFAULT_OPTIONS);
  }

  function changeMapping(patch: Partial<ImportMapping>) {
    if (!csv || !mapping) return;
    const next = { ...mapping, ...patch };
    setMapping(next);
    refresh(csv, next);
  }

  function changeOptions(patch: Partial<ImportOptions>) {
    if (!csv || !mapping) return;
    const next = { ...options, ...patch };
    setOptions(next);
    refresh(csv, mapping, next);
  }

  async function runImport() {
    if (!csv || !mapping) return;
    setBusy(true);
    try {
      const result = await api.importCsv(csv, mapping, options);
      const parts = [`Imported ${result.imported} transaction${result.imported === 1 ? "" : "s"}`];
      if (result.duplicates) parts.push(`skipped ${result.duplicates} already in your records`);
      if (result.error_count) parts.push(`skipped ${result.error_count} with problems`);
      setMessage({ text: parts.join(", ") + ".", error: false });
      reset();
      onImported();
    } catch (e) {
      setMessage({ text: (e as Error).message, error: true });
    } finally {
      setBusy(false);
    }
  }

  const headers = preview?.headers ?? [];
  const twoColumns = !!mapping && !mapping.amount && (!!mapping.debit || !!mapping.credit);
  const column = (label: string, key: keyof ImportMapping, optional = false) => (
    <label className="field">
      <span>{label}{optional ? " (optional)" : ""}</span>
      <select value={mapping?.[key] ?? ""} onChange={(e) => changeMapping({ [key]: e.target.value || null })}>
        <option value="">{optional ? "None" : "Choose a column…"}</option>
        {headers.map((h) => <option key={h} value={h}>{h}</option>)}
      </select>
    </label>
  );
  const dateChoices = preview?.date_formats.length ? preview.date_formats : preview?.date_format_choices ?? [];

  return (
    <section className="setting-row">
      <h3>Import transactions</h3>
      <span className="hint">
        Load a CSV from your bank, a spreadsheet, or this app's own export. You'll see exactly how it will be read
        before anything is saved, and transactions you already have are skipped.
      </span>

      <div className="inline-form">
        <label className="btn file-button">
          {csv ? "Choose a different file" : "Choose a CSV file…"}
          <input type="file" accept=".csv,text/csv" onChange={pickFile} hidden />
        </label>
        {csv && <span className="subtle" style={{ alignSelf: "center" }}>{fileName} · {preview?.total_rows ?? 0} rows</span>}
      </div>
      {message && <span className={`message ${message.error ? "error" : "success"}`}>{message.text}</span>}

      {preview && mapping && (
        <div className={`import-panel ${busy ? "refreshing" : ""}`}>
          <h4 className="ai-heading">Columns</h4>
          <div className="field-row">
            {column("Date", "date")}
            {column("Description", "description")}
          </div>

          <div className="segmented" role="group" aria-label="How amounts are stored">
            <button type="button" aria-pressed={!twoColumns}
              onClick={() => changeMapping({ amount: mapping.amount ?? mapping.debit ?? headers[0] ?? null, debit: null, credit: null })}>
              One amount column
            </button>
            <button type="button" aria-pressed={twoColumns}
              onClick={() => changeMapping({ amount: null, debit: mapping.debit ?? mapping.amount, credit: mapping.credit })}>
              Separate debit &amp; credit
            </button>
          </div>
          {twoColumns ? (
            <div className="field-row">
              {column("Debit (money out)", "debit")}
              {column("Credit (money in)", "credit")}
            </div>
          ) : (
            <div className="field-row">
              {column("Amount", "amount")}
              {column("Expense/income column", "kind", true)}
            </div>
          )}
          {!twoColumns && !mapping.kind && (
            <label className="field">
              <span>Positive amounts are</span>
              <select value={options.positive_is} onChange={(e) => changeOptions({ positive_is: e.target.value as ImportOptions["positive_is"] })}>
                <option value="income">Money in (most bank accounts)</option>
                <option value="expense">Spending (many credit cards)</option>
              </select>
            </label>
          )}

          <div className="field-row">
            {column("Category", "category", true)}
            <label className="field">
              <span>Date format</span>
              <select value={options.date_format} onChange={(e) => changeOptions({ date_format: e.target.value })}>
                {options.date_format === "auto" && <option value="auto">Detect automatically</option>}
                {dateChoices.map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
              {preview.date_formats.length > 1 && (
                <span className="hint">These dates could be read more than one way. Check the preview below.</span>
              )}
            </label>
          </div>
          {!mapping.category && (
            <label className="field" style={{ maxWidth: 280 }}>
              <span>Category for every row</span>
              <input
                type="text"
                value={options.default_category}
                onChange={(e) => setOptions({ ...options, default_category: e.target.value })}
                onBlur={() => changeOptions({})}
              />
            </label>
          )}

          {preview.problem ? (
            <p className="message error">{preview.problem}</p>
          ) : (
            <>
              <h4 className="ai-heading" style={{ marginTop: 6 }}>Preview</h4>
              <p className="import-summary">
                <strong>{preview.ready}</strong> ready to import
                {!!preview.duplicates && <> · {preview.duplicates} already in your records (skipped)</>}
                {!!preview.error_count && <> · <span className="amount-negative">{preview.error_count} with problems (skipped)</span></>}
              </p>
              {!!preview.sample?.length && (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>Line</th><th>Date</th><th>Description</th><th>Category</th><th className="right">Amount</th></tr>
                    </thead>
                    <tbody>
                      {preview.sample.map((row) => (
                        <tr key={row.line}>
                          <td className="subtle">{row.line}</td>
                          <td className="num" style={{ whiteSpace: "nowrap" }}>{dateLabel(row.date)}</td>
                          <td>{row.description}</td>
                          <td className="subtle">{row.category}</td>
                          <td className={`right num ${row.kind === "income" ? "amount-income" : ""}`} style={{ whiteSpace: "nowrap" }}>
                            {row.kind === "income" ? "+" : "−"}{money(row.amount_cents)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {!!preview.errors?.length && (
                <details className="table-view">
                  <summary>Rows with problems ({preview.error_count})</summary>
                  <ul className="import-errors">
                    {preview.errors.map((e) => <li key={e}>{e}</li>)}
                    {(preview.error_count ?? 0) > preview.errors.length && <li>…and more</li>}
                  </ul>
                </details>
              )}
            </>
          )}

          <div className="inline-form">
            <button className="btn btn-primary" type="button" disabled={busy || !!preview.problem || !preview.ready} onClick={runImport}>
              {busy ? "Working…" : `Import ${preview.ready ?? 0} transaction${preview.ready === 1 ? "" : "s"}`}
            </button>
            <button className="btn" type="button" onClick={reset} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}
    </section>
  );
}
