import { CANVAS_PATH_CAP } from "../limits";
import type { ScorecardRow } from "../types/api";
import {
  AUTHORITIES,
  type Authority,
  type EdgeKind,
  type NodeKind,
  assertNever,
  isAuthority,
} from "../types/graph";

export const ZERO_SHARE_COLOR = "#f7f1e6";
export const FULL_SHARE_COLOR = "#8c3b2a";
export const MISSING_COLOR = "#d9d3c7";

export type ShadeMode = "providers" | "authority";

export function colorForKind(kind: NodeKind): string {
  switch (kind) {
    case "Organization":
      return "#3d4c63";
    case "UtilitySystem":
      return "#5c6b7a";
    case "WaterSystem":
      return "#1d6a8a";
    case "ElectricSystem":
      return "#c47b12";
    case "WastewaterSystem":
      return "#6b4c7a";
    case "NaturalGasSystem":
      return "#8a5a2a";
    case "MultiUtilitySystem":
      return "#2f6f5e";
    case "ReferenceSystem":
      return "#6e6a62";
    case "StormwaterSystem":
      return "#3e6b8a";
    case "TelecommunicationsSystem":
      return "#3f5f8a";
    case "PetroleumLiquidsSystem":
      return "#8a3d2f";
    case "ServiceArea":
      return "#2a7a68";
    case "Facility":
      return "#a33b4a";
    case "County":
      return "#8d7b4a";
    case "State":
      return "#4d5e4a";
    case "Place":
      return "#6a5a78";
    case "Source":
      return "#5a5a5a";
    case "CountyCoverage":
      return "#3f6f78";
    default:
      return assertNever(kind);
  }
}

export function colorForEdge(kind: EdgeKind): string {
  switch (kind) {
    case "operatesSystem":
      return "#8a3d2f";
    case "ownsSystem":
      return "#1d4e5f";
    case "parentOf":
      return "#6b4c7a";
    case "hasServiceArea":
      return "#2a7a68";
    case "assertedBy":
      return "#5a5a5a";
    case "inState":
      return "#4d5e4a";
    case "locatedInCounty":
      return "#8d7b4a";
    case "servesCounty":
      return "#1d6a8a";
    case "system":
      return "#3f6f78";
    case "county":
      return "#3e6b8a";
    default:
      return assertNever(kind);
  }
}

export function authorityRank(authority: Authority): number {
  switch (authority) {
    case "utility_direct":
      return 0;
    case "state_regulator":
      return 1;
    case "federal_submitted":
      return 2;
    case "federal_modeled":
      return 3;
    case "admin_proxy":
      return 4;
    default:
      return assertNever(authority);
  }
}

export function authorityColor(authority: Authority): string {
  switch (authority) {
    case "utility_direct":
      return "#1d6a8a";
    case "state_regulator":
      return "#2f6f5e";
    case "federal_submitted":
      return "#c47b12";
    case "federal_modeled":
      return "#8a5a2a";
    case "admin_proxy":
      return "#6e6a62";
    default:
      return assertNever(authority);
  }
}

export function bestAuthority(values: readonly string[]): Authority | null {
  let best: Authority | null = null;
  for (const value of values) {
    if (!isAuthority(value)) continue;
    if (best === null || authorityRank(value) < authorityRank(best)) best = value;
  }
  return best;
}

export function coverageColor(share: number | null): string {
  if (share === null || !Number.isFinite(share)) return MISSING_COLOR;
  return mixHex(ZERO_SHARE_COLOR, FULL_SHARE_COLOR, Math.min(1, Math.max(0, share)));
}

export function providerColor(count: number | null): string {
  if (count === null || !Number.isFinite(count)) return MISSING_COLOR;
  if (count <= 0) return "#f4f7f8";
  const t = Math.min(1, Math.log10(count + 1) / Math.log10(501));
  return mixHex("#d5e4ea", "#1d4e5f", t);
}

export function countyShadeColor(
  mode: ShadeMode,
  providers: number | null,
  authorities: readonly string[],
): string {
  switch (mode) {
    case "providers":
      return providerColor(providers);
    case "authority": {
      const best = bestAuthority(authorities);
      return best ? authorityColor(best) : MISSING_COLOR;
    }
    default:
      return assertNever(mode);
  }
}

export function providersFor(
  geoid: string,
  stats: readonly { geoid: string; providers: number | null }[],
  complete: boolean,
): number | null {
  const found = stats.find((item) => item.geoid === geoid);
  if (found && found.providers !== null) return found.providers;
  return complete ? 0 : null;
}

export function sectorNonmodeledShare(rows: readonly ScorecardRow[], sector: string): number | null {
  const matching = rows.filter((row) => row.sector === sector);
  if (matching.length === 0) return null;
  let population = 0;
  let inside = 0;
  let sawPopulation = false;
  for (const row of matching) {
    if (row.population === null || row.population_in_nonmodeled_boundary === null) continue;
    sawPopulation = true;
    population += row.population;
    inside += row.population_in_nonmodeled_boundary;
  }
  if (sawPopulation && population > 0) return inside / population;
  const shares = matching
    .map((row) => row.share_population_nonmodeled)
    .filter((value): value is number => value !== null && Number.isFinite(value));
  if (shares.length === 0) return null;
  return shares.every((share) => share === 0) ? 0 : null;
}

export function formatShare(share: number): string {
  if (share === 0) return "0";
  return `${(share * 100).toFixed(1)}%`;
}

export function barLength(value: number, maxAbs: number, width: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(maxAbs) || maxAbs <= 0 || width <= 0) return 0;
  return (Math.abs(value) / maxAbs) * width;
}

export function mixHex(from: string, to: string, t: number): string {
  const start = parseHex(from);
  const end = parseHex(to);
  const clamped = Math.min(1, Math.max(0, t));
  const channel = (index: 0 | 1 | 2) => Math.round(start[index] * (1 - clamped) + end[index] * clamped);
  return `#${[channel(0), channel(1), channel(2)].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

export function canvasPathLimit(): number {
  return CANVAS_PATH_CAP;
}

export function authorityOrder(): readonly Authority[] {
  return AUTHORITIES;
}

function parseHex(value: string): [number, number, number] {
  const hex = value.replace("#", "");
  return [
    Number.parseInt(hex.slice(0, 2), 16),
    Number.parseInt(hex.slice(2, 4), 16),
    Number.parseInt(hex.slice(4, 6), 16),
  ];
}
