import { useEffect, useState } from "react";

export interface AsyncState<T> {
  data?: T;
  error?: string;
  loading: boolean;
}

/** True on phone-width screens -- the same breakpoint as the .hide-narrow CSS class. */
export function useNarrow(): boolean {
  const query = "(max-width: 560px)";
  const [narrow, setNarrow] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setNarrow(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return narrow;
}

/**
 * Run an async loader and re-run it whenever `deps` change.
 *
 * While a reload is in flight the previous `data` is kept (with loading=true),
 * so screens dim slightly instead of flashing empty.
 */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ loading: true });

  useEffect(() => {
    let cancelled = false;
    setState((previous) => ({ ...previous, loading: true }));
    load().then(
      (data) => !cancelled && setState({ data, loading: false }),
      (error: Error) => !cancelled && setState((previous) => ({ ...previous, error: error.message, loading: false })),
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}

export interface ChartTheme {
  series1: string;
  series1Muted: string;
  ink: string;
  ink2: string;
  muted: string;
  grid: string;
  axis: string;
  surface: string;
  hover: string;
}

/**
 * Chart libraries draw SVG with literal colors, so read the CSS custom
 * properties (which already switch for dark mode) and re-read on theme change.
 */
export function useChartTheme(): ChartTheme {
  const read = (): ChartTheme => {
    const style = getComputedStyle(document.documentElement);
    const v = (name: string) => style.getPropertyValue(name).trim();
    return {
      series1: v("--series-1"),
      series1Muted: v("--series-1-muted"),
      ink: v("--text-primary"),
      ink2: v("--text-secondary"),
      muted: v("--text-muted"),
      grid: v("--grid"),
      axis: v("--axis"),
      surface: v("--surface-1"),
      hover: v("--hover"),
    };
  };
  const [theme, setTheme] = useState(read);
  useEffect(() => {
    const update = () => setTheme(read());
    // The OS switching light/dark...
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", update);
    // ...or the Settings page changing <html data-theme>.
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      media.removeEventListener("change", update);
      observer.disconnect();
    };
  }, []);
  return theme;
}

export type ThemeChoice = "system" | "light" | "dark";

/** Point <html data-theme> at the choice and remember it for the next page load. */
export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") delete root.dataset.theme;
  else root.dataset.theme = choice;
  try {
    localStorage.setItem("theme", choice);
  } catch {
    // storage blocked (private window); the theme still applies for this visit
  }
}
