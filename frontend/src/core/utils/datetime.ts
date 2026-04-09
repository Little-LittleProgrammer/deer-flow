import { formatDistanceToNow, isValid } from "date-fns";
import { enUS as dateFnsEnUS, zhCN as dateFnsZhCN } from "date-fns/locale";

import { detectLocale, type Locale } from "@/core/i18n";
import { getLocaleFromCookie } from "@/core/i18n/cookies";

function getDateFnsLocale(locale: Locale) {
  switch (locale) {
    case "zh-CN":
      return dateFnsZhCN;
    case "en-US":
    default:
      return dateFnsEnUS;
  }
}

/** Backend may send `str(time.time())` (unix seconds); JS `Date` needs ms or ISO. */
function toValidDate(input: Date | string | number): Date | null {
  if (input instanceof Date) {
    return isValid(input) ? input : null;
  }
  if (typeof input === "number") {
    if (!Number.isFinite(input)) return null;
    const ms = input < 1e12 ? input * 1000 : input;
    const d = new Date(ms);
    return isValid(d) ? d : null;
  }
  const trimmed = input.trim();
  if (!trimmed) return null;
  // Numeric unix timestamp (seconds with optional fraction), e.g. Gateway `str(time.time())`
  if (/^\d+(\.\d+)?$/.test(trimmed)) {
    const sec = Number(trimmed);
    if (!Number.isFinite(sec)) return null;
    const ms = sec < 1e12 ? sec * 1000 : sec;
    const d = new Date(ms);
    return isValid(d) ? d : null;
  }
  const d = new Date(trimmed);
  return isValid(d) ? d : null;
}

export function formatTimeAgo(date: Date | string | number, locale?: Locale) {
  const parsed = toValidDate(date);
  if (!parsed) {
    return "";
  }
  const effectiveLocale =
    locale ??
    (getLocaleFromCookie() as Locale | null) ??
    // Fallback when cookie is missing (or on first render)
    detectLocale();
  return formatDistanceToNow(parsed, {
    addSuffix: true,
    locale: getDateFnsLocale(effectiveLocale),
  });
}
