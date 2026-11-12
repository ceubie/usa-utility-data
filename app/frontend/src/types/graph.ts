export const NODE_KINDS = [
  "Organization",
  "UtilitySystem",
  "WaterSystem",
  "ElectricSystem",
  "WastewaterSystem",
  "NaturalGasSystem",
  "MultiUtilitySystem",
  "ReferenceSystem",
  "StormwaterSystem",
  "TelecommunicationsSystem",
  "PetroleumLiquidsSystem",
  "ServiceArea",
  "Facility",
  "County",
  "State",
  "Place",
  "Source",
  "CountyCoverage",
] as const;

export type NodeKind = (typeof NODE_KINDS)[number];

export const EDGE_KINDS = [
  "operatesSystem",
  "ownsSystem",
  "parentOf",
  "hasServiceArea",
  "assertedBy",
  "inState",
  "locatedInCounty",
  "servesCounty",
  "system",
  "county",
] as const;

export type EdgeKind = (typeof EDGE_KINDS)[number];

export const SECTORS = [
  "water",
  "electric",
  "wastewater",
  "natural_gas",
  "multi_utility",
  "reference",
  "stormwater",
  "telecommunications",
  "petroleum_liquids",
] as const;

export type Sector = (typeof SECTORS)[number];

export const AUTHORITIES = [
  "utility_direct",
  "state_regulator",
  "federal_submitted",
  "federal_modeled",
  "admin_proxy",
] as const;

export type Authority = (typeof AUTHORITIES)[number];

export interface GraphNode {
  iri: string;
  label: string;
  kind: NodeKind;
  state: string | null;
  sector: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: EdgeKind;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  dropped: number;
}

export function emptyGraph(): GraphData {
  return { nodes: [], edges: [], dropped: 0 };
}

export function assertNever(value: never, message = "Unexpected value"): never {
  throw new Error(`${message}: ${JSON.stringify(value)}`);
}

export function isNodeKind(value: string): value is NodeKind {
  return (NODE_KINDS as readonly string[]).includes(value);
}

export function isEdgeKind(value: string): value is EdgeKind {
  return (EDGE_KINDS as readonly string[]).includes(value);
}

export function isSector(value: string): value is Sector {
  return (SECTORS as readonly string[]).includes(value);
}

export function isAuthority(value: string): value is Authority {
  return (AUTHORITIES as readonly string[]).includes(value);
}

export function classForSector(sector: Sector): NodeKind {
  switch (sector) {
    case "water":
      return "WaterSystem";
    case "electric":
      return "ElectricSystem";
    case "wastewater":
      return "WastewaterSystem";
    case "natural_gas":
      return "NaturalGasSystem";
    case "multi_utility":
      return "MultiUtilitySystem";
    case "reference":
      return "ReferenceSystem";
    case "stormwater":
      return "StormwaterSystem";
    case "telecommunications":
      return "TelecommunicationsSystem";
    case "petroleum_liquids":
      return "PetroleumLiquidsSystem";
    default:
      return assertNever(sector);
  }
}

export function classForSectorName(value: string | null | undefined): NodeKind {
  if (!value || !isSector(value)) return "UtilitySystem";
  return classForSector(value);
}
