import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemeChoice = "system" | "light" | "dark";
type Resolved = "light" | "dark";

interface ThemeState {
  choice: ThemeChoice;
  resolved: Resolved;
  setChoice: (choice: ThemeChoice) => void;
}

const ThemeContext = createContext<ThemeState | null>(null);
const KEY = "synapse.theme";
const media = () => window.matchMedia("(prefers-color-scheme: dark)");

function readChoice(): ThemeChoice {
  try {
    const saved = localStorage.getItem(KEY);
    return saved === "light" || saved === "dark" ? saved : "system";
  } catch {
    return "system";
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(readChoice);
  const [systemDark, setSystemDark] = useState(() => media().matches);

  useEffect(() => {
    const query = media();
    const listener = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }, []);

  const resolved: Resolved = choice === "system" ? (systemDark ? "dark" : "light") : choice;

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolved);
  }, [resolved]);

  const value = useMemo<ThemeState>(
    () => ({
      choice,
      resolved,
      setChoice: (next) => {
        setChoiceState(next);
        try {
          localStorage.setItem(KEY, next);
        } catch {
          /* per-viewer convenience only */
        }
      },
    }),
    [choice, resolved],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside ThemeProvider");
  return context;
}

export interface ChartColors {
  surface: string;
  ink: string;
  secondary: string;
  muted: string;
  hairline: string;
  axis: string;
  context: string;
  accent: string;
  series: string[];
}

// Same values as the CSS tokens in styles.css (canvas charts cannot read var()).
export const PALETTES: Record<Resolved, ChartColors> = {
  light: {
    surface: "#fcfcfb",
    ink: "#0b0b0b",
    secondary: "#52514e",
    muted: "#898781",
    hairline: "#e1e0d9",
    axis: "#c3c2b7",
    context: "#d6d5ce",
    accent: "#2a78d6",
    series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
  },
  dark: {
    surface: "#1a1a19",
    ink: "#ffffff",
    secondary: "#c3c2b7",
    muted: "#898781",
    hairline: "#2c2c2a",
    axis: "#383835",
    context: "#3d3d3a",
    accent: "#3987e5",
    series: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
  },
};

/** Chart colours for the active theme. */
export function useChartColors(): ChartColors {
  return PALETTES[useTheme().resolved];
}
