export type Device = {browser: string | null; system: string | null}

// The first match wins: Edge and Opera also name Chrome, Chrome also names Safari.
const BROWSERS: [RegExp, string][] = [
  [/Edg\//, 'Edge'],
  [/OPR\/|Opera/, 'Opera'],
  [/YaBrowser\//, 'Yandex Browser'],
  [/Firefox\/|FxiOS\//, 'Firefox'],
  [/Chrome\/|CriOS\//, 'Chrome'],
  [/Safari\//, 'Safari'],
]

const SYSTEMS: [RegExp, string][] = [
  [/iPhone|iPad|iPod/, 'iOS'],
  [/Android/, 'Android'],
  [/Windows/, 'Windows'],
  [/Mac OS X|Macintosh/, 'macOS'],
  [/CrOS/, 'ChromeOS'],
  [/Linux/, 'Linux'],
]

/** The browser and the system a session's user agent names, as far as they can be told. */
export function describeDevice(userAgent: string | null | undefined): Device {
  const find = (table: [RegExp, string][]) => table.find(([pattern]) => userAgent && pattern.test(userAgent))?.[1]
  return {browser: find(BROWSERS) ?? null, system: find(SYSTEMS) ?? null}
}
