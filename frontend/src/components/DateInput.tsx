import { todayIso } from "../format";

/**
 * A date field. Browsers size the year box from ``max``: without one, Chrome
 * accepts years up to 275760 and waits for a sixth digit before moving on to
 * the month. So every date field has a 4-digit-year min and max (today by default).
 */
export function DateInput({
  value,
  onChange,
  max = todayIso(),
  min = "1900-01-01",
  required,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  max?: string;
  min?: string;
  required?: boolean;
  ariaLabel?: string;
}) {
  return (
    <input
      type="date"
      value={value}
      min={min}
      max={max}
      required={required}
      aria-label={ariaLabel}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
