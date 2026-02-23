import { createContext, useContext, useState, type ReactNode } from "react";

export interface Translations {
  pageTitle: string;
  htmlTitle: string;
  showMap: string;
  hideMap: string;
  mapHint: string;
  searchPlaceholder: string;
  allVenues: string;
  from: string;
  to: string;
  minPrice: string;
  maxPrice: string;
  filter: string;
  reset: string;
  loading: string;
  noEvents: string;
  open: string;
  start: string;
  rating: string;
  dowShort: string[];
  dowLong: string[];
}

const en: Translations = {
  pageTitle: "Live Events",
  htmlTitle: "Live House Events, Japan",
  showMap: "Show Map",
  hideMap: "Hide Map",
  mapHint: "Pan & zoom to filter events by area",
  searchPlaceholder: "Search title or artist...",
  allVenues: "All venues",
  from: "From",
  to: "To",
  minPrice: "Min price (¥)",
  maxPrice: "Max price (¥)",
  filter: "Filter",
  reset: "Reset",
  loading: "Loading events...",
  noEvents: "No events found.",
  open: "OPEN",
  start: "START",
  rating: "Rating:",
  dowShort: ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"],
  dowLong: [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
  ],
};

const ja: Translations = {
  pageTitle: "ライブイベント",
  htmlTitle: "ライブハウスイベント・日本",
  showMap: "マップを表示",
  hideMap: "マップを非表示",
  mapHint: "パン＆ズームでエリア別にイベントを絞り込み",
  searchPlaceholder: "タイトルやアーティストで検索...",
  allVenues: "すべての会場",
  from: "開始日",
  to: "終了日",
  minPrice: "最低価格 (¥)",
  maxPrice: "最高価格 (¥)",
  filter: "絞り込み",
  reset: "リセット",
  loading: "イベントを読み込み中...",
  noEvents: "イベントが見つかりません。",
  open: "OPEN",
  start: "START",
  rating: "評価:",
  dowShort: ["日", "月", "火", "水", "木", "金", "土"],
  dowLong: [
    "日曜日",
    "月曜日",
    "火曜日",
    "水曜日",
    "木曜日",
    "金曜日",
    "土曜日",
  ],
};

export type Locale = "en" | "ja";

const translations: Record<Locale, Translations> = { en, ja };

interface LanguageContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: Translations;
}

const LanguageContext = createContext<LanguageContextValue>({
  locale: "en",
  setLocale: () => {},
  t: en,
});

const STORAGE_KEY = "app-locale";

function getInitialLocale(): Locale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "en" || stored === "ja") return stored;
  } catch {
    /* localStorage unavailable */
  }
  return "en";
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(getInitialLocale);

  function setLocale(l: Locale) {
    setLocaleState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
  }

  return (
    <LanguageContext.Provider
      value={{ locale, setLocale, t: translations[locale] }}
    >
      {children}
    </LanguageContext.Provider>
  );
}

export function useTranslation() {
  return useContext(LanguageContext);
}
