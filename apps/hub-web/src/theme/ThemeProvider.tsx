import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemePreference = "system" | "light" | "dark";
type ResolvedTheme = "light" | "dark";

type ThemeContextValue = {
  preference: ThemePreference;
  resolvedTheme: ResolvedTheme;
  selectTheme: (preference: ThemePreference) => void;
};

const STORAGE_KEY = "commitverse-theme";
const ThemeContext = createContext<ThemeContextValue | null>(null);

function isThemePreference(value: string | undefined): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

function getInitialPreference(): ThemePreference {
  const documentPreference = document.documentElement.dataset.themeMode;
  if (isThemePreference(documentPreference)) return documentPreference;

  try {
    const storedPreference = window.localStorage.getItem(STORAGE_KEY) ?? undefined;
    return isThemePreference(storedPreference) ? storedPreference : "system";
  } catch (error) {
    console.warn("CommitVerse could not read the saved theme preference.", error);
    return "system";
  }
}

function getSystemTheme(): ResolvedTheme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreference] = useState<ThemePreference>(getInitialPreference);
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(getSystemTheme);
  const resolvedTheme = preference === "system" ? systemTheme : preference;

  useEffect(() => {
    const mediaQuery = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mediaQuery) return;

    function updateSystemTheme(event: MediaQueryListEvent) {
      setSystemTheme(event.matches ? "dark" : "light");
    }

    mediaQuery.addEventListener("change", updateSystemTheme);
    return () => mediaQuery.removeEventListener("change", updateSystemTheme);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.themeMode = preference;
    document.documentElement.dataset.theme = resolvedTheme;
    document.documentElement.style.colorScheme = resolvedTheme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", resolvedTheme === "dark" ? "#161715" : "#f7f6f2");

    try {
      window.localStorage.setItem(STORAGE_KEY, preference);
    } catch (error) {
      console.warn("CommitVerse could not save the theme preference.", error);
    }
  }, [preference, resolvedTheme]);

  const selectTheme = useCallback((selected: ThemePreference) => {
    setPreference(selected);
  }, []);

  const value = useMemo(
    () => ({ preference, resolvedTheme, selectTheme }),
    [preference, resolvedTheme, selectTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within ThemeProvider.");
  return context;
}

function ThemeIcon({ theme }: { theme: ThemePreference }) {
  if (theme === "system") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <rect x="3" y="4" width="14" height="10" rx="2" />
        <path d="M7 17h6M10 14v3" />
      </svg>
    );
  }

  if (theme === "dark") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M15.8 12.2A6.6 6.6 0 0 1 7.8 4.1a6.7 6.7 0 1 0 8 8.1Z" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="10" cy="10" r="3.3" />
      <path d="M10 1.8v2M10 16.2v2M18.2 10h-2M3.8 10h-2m14-5.8-1.4 1.4m-8.8 8.8-1.4 1.4m11.6 0-1.4-1.4m-8.8-8.8L4.2 4.2" />
    </svg>
  );
}

export function ThemeToggle() {
  const { preference, selectTheme } = useTheme();
  const options: { value: ThemePreference; label: string }[] = [
    { value: "system", label: "System" },
    { value: "light", label: "Light" },
    { value: "dark", label: "Dark" },
  ];

  return (
    <fieldset className="theme-toggle" role="radiogroup" aria-labelledby="theme-toggle-label">
      <legend className="sr-only" id="theme-toggle-label">
        Color theme
      </legend>
      {options.map((option) => (
        <label className="theme-option" key={option.value}>
          <input
            type="radio"
            name="commitverse-theme"
            value={option.value}
            checked={preference === option.value}
            aria-label={`Switch to ${option.value} theme`}
            onChange={() => selectTheme(option.value)}
          />
          <span className="theme-option-visual" aria-hidden="true">
            <ThemeIcon theme={option.value} />
            <span className="theme-option-label">{option.label}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}
