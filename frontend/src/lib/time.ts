const FALLBACK_TIME_ZONE = "Asia/Jakarta";

const timeZoneLabels: Record<string, string> = {
  "Asia/Jakarta": "WIB",
  "Asia/Makassar": "WITA",
  "Asia/Jayapura": "WIT"
};

export function getUserTimeZone(): string {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!zone || zone === "UTC") return FALLBACK_TIME_ZONE;
    return zone;
  } catch {
    return FALLBACK_TIME_ZONE;
  }
}

export function formatLocalDateTime(isoUtc?: string | null): string {
  const date = parseDate(isoUtc);
  if (!date) return "-";
  const timeZone = getUserTimeZone();
  const formatted = new Intl.DateTimeFormat("id-ID", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone
  }).format(date);
  return `${formatted} ${timeZoneSuffix(timeZone)}`;
}

export function formatRelativeTime(isoUtc?: string | null): string {
  const date = parseDate(isoUtc);
  if (!date) return "-";
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  const rtf = new Intl.RelativeTimeFormat("id-ID", { numeric: "auto" });
  if (abs < 60) return rtf.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return rtf.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return rtf.format(hours, "hour");
  return rtf.format(Math.round(hours / 24), "day");
}

export function formatTimeWithUtcDetail(isoUtc?: string | null): { local: string; utc: string; relative: string } {
  const date = parseDate(isoUtc);
  if (!date) return { local: "-", utc: "-", relative: "-" };
  return {
    local: formatLocalDateTime(isoUtc),
    utc: toUtcIso(date),
    relative: formatRelativeTime(isoUtc)
  };
}

function parseDate(value?: string | null): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function toUtcIso(value: Date): string {
  return value.toISOString().replace(".000Z", "Z");
}

function timeZoneSuffix(timeZone: string): string {
  if (timeZoneLabels[timeZone]) return timeZoneLabels[timeZone];
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    timeZoneName: "shortOffset",
    hour: "2-digit",
    minute: "2-digit"
  }).formatToParts(new Date());
  return parts.find((part) => part.type === "timeZoneName")?.value || timeZone;
}
