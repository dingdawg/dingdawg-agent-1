"use client";

import { useTranslation } from "@/lib/i18n";
import type { SupportedLocale } from "@/lib/i18n";

const LOCALE_LABELS: Record<SupportedLocale, string> = {
  en: "English",
  es: "Español",
  zh: "中文",
  fr: "Français",
  ar: "العربية",
  ht: "Kreyòl Ayisyen",
  vi: "Tiếng Việt",
};

const LOCALES = Object.keys(LOCALE_LABELS) as SupportedLocale[];

export default function LanguageSwitcher() {
  const { locale, setLocale } = useTranslation();

  return (
    <select
      value={locale}
      onChange={(e) => setLocale(e.target.value as SupportedLocale)}
      aria-label="Select language"
      className="rounded border border-gray-600 bg-gray-900 px-2 py-1 text-sm text-white focus:outline-none focus:ring-2 focus:ring-yellow-400"
    >
      {LOCALES.map((code) => (
        <option key={code} value={code}>
          {LOCALE_LABELS[code]}
        </option>
      ))}
    </select>
  );
}
