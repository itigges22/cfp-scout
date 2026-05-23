/**
 * ISO-3166-1 alpha-2 → [longitude, latitude] centroid.
 *
 * Used by the dashboard WorldMap to plot one dot per country. Values
 * are approximate geographic centers (visual-center, not population-
 * weighted) — close enough for a "where are AI events" overview map.
 *
 * Covers the ~90 countries most likely to show up in the
 * developers.events feed. Unknown codes silently fall off the map.
 */

export const COUNTRY_CENTROIDS: Record<string, [number, number]> = {
  // North America
  US: [-98.5, 39.8],
  CA: [-106.3, 56.1],
  MX: [-102.5, 23.6],
  GT: [-90.2, 15.8],
  HN: [-86.6, 15.2],

  // South America
  BR: [-51.9, -14.2],
  AR: [-63.6, -38.4],
  CL: [-71.5, -35.7],
  CO: [-74.3, 4.6],
  PE: [-75.0, -9.2],
  UY: [-55.8, -32.5],
  VE: [-66.6, 6.4],

  // Europe — west
  GB: [-3.4, 55.4],
  IE: [-8.2, 53.4],
  FR: [2.2, 46.2],
  ES: [-3.7, 40.5],
  PT: [-8.2, 39.4],
  IT: [12.6, 41.9],
  DE: [10.5, 51.2],
  NL: [5.3, 52.1],
  BE: [4.5, 50.5],
  CH: [8.2, 46.8],
  AT: [14.6, 47.5],
  LU: [6.1, 49.8],

  // Europe — north
  DK: [9.5, 56.3],
  SE: [18.6, 60.1],
  NO: [8.5, 60.5],
  FI: [25.7, 61.9],
  IS: [-19.0, 64.9],

  // Europe — central / east
  PL: [19.1, 51.9],
  CZ: [15.5, 49.8],
  SK: [19.7, 48.7],
  HU: [19.5, 47.2],
  RO: [25.0, 45.9],
  BG: [25.5, 42.7],
  GR: [22.0, 39.1],
  RS: [21.0, 44.0],
  HR: [15.2, 45.1],
  SI: [14.9, 46.2],
  EE: [25.8, 58.6],
  LV: [24.6, 56.9],
  LT: [23.9, 55.2],
  UA: [31.2, 48.4],
  BY: [27.9, 53.7],
  RU: [105.3, 61.5],
  AL: [20.2, 41.2],
  MK: [21.7, 41.6],

  // Middle East
  IL: [34.9, 31.0],
  TR: [35.2, 38.9],
  AE: [54.0, 23.4],
  SA: [45.1, 23.9],
  QA: [51.2, 25.4],
  KW: [47.6, 29.3],
  JO: [36.8, 30.6],
  LB: [35.9, 33.9],
  IR: [53.7, 32.4],

  // Africa
  ZA: [22.9, -30.6],
  EG: [30.8, 26.8],
  MA: [-7.1, 31.8],
  TN: [9.5, 33.9],
  KE: [37.9, -0.0],
  NG: [8.7, 9.1],
  GH: [-1.0, 7.9],
  CM: [12.3, 7.4],
  ET: [40.5, 9.1],
  CI: [-5.5, 7.5],

  // Asia
  IN: [78.9, 20.6],
  CN: [104.2, 35.9],
  JP: [138.3, 36.2],
  KR: [127.8, 36.6],
  TW: [121.0, 23.7],
  HK: [114.2, 22.4],
  SG: [103.8, 1.4],
  ID: [113.9, -0.8],
  MY: [101.9, 4.2],
  TH: [101.0, 15.9],
  VN: [108.3, 14.1],
  PH: [121.8, 12.9],
  BD: [90.4, 23.7],
  PK: [69.3, 30.4],
  NP: [84.1, 28.4],
  LK: [80.8, 7.9],
  KZ: [66.9, 48.0],

  // Oceania
  AU: [134.5, -25.7],
  NZ: [171.8, -41.0],
};
