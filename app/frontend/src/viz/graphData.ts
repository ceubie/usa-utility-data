import { NODE_CAP } from "../limits";
import type { ProjectedLink, ProjectedNode, SearchRow, SparqlRow, WhoServesSystem } from "../types/api";
import {
  type EdgeKind,
  type GraphData,
  type GraphEdge,
  type GraphNode,
  type NodeKind,
  assertNever,
  classForSectorName,
  emptyGraph,
  isEdgeKind,
  isNodeKind,
} from "../types/graph";

const BASE = "http://utilities.local/";

export type TreeRole =
  | "self"
  | "parent"
  | "subsidiary"
  | "owner"
  | "operator"
  | "owned-system"
  | "operated-system";

export interface TreeItem {
  iri: string;
  label: string;
  kind: NodeKind;
  role: TreeRole;
  children: TreeItem[];
}

type SearchKind = "system" | "organization" | "facility" | "county" | "place" | "state";

export function localName(iri: string): string {
  const hash = iri.lastIndexOf("#");
  const slash = iri.lastIndexOf("/");
  const index = Math.max(hash, slash);
  return index >= 0 ? iri.slice(index + 1) : iri;
}

export function asEdgeKind(predicate: string): EdgeKind | null {
  const local = localName(predicate);
  return isEdgeKind(local) ? local : null;
}

export function nodeFromIri(
  iri: string,
  label?: string | null,
  sector?: string | null,
  state?: string | null,
): GraphNode | null {
  if (!iri.startsWith(BASE)) return null;
  const path = iri.slice(BASE.length);
  const kind = kindFromPath(path);
  if (!kind) return null;
  const specific = kind === "UtilitySystem" ? classForSectorName(sector) : kind;
  const fallback = path.split("/").filter(Boolean).at(-1) ?? iri;
  return {
    iri,
    label: label && label.trim() ? label : fallback,
    kind: specific,
    state: state && state.trim() ? state : null,
    sector: sector && sector.trim() ? sector : null,
  };
}

export function nodeFromSearch(row: SearchRow): GraphNode | null {
  if (!row.iri) return null;
  const inferred = nodeFromIri(row.iri, row.label, row.sector, row.state);
  if (!inferred) return null;
  if (!row.kind || !isSearchKind(row.kind)) return inferred;
  return { ...inferred, kind: kindFromSearch(row.kind, row.sector) };
}

export function graphFromNeighbors(center: GraphNode, rows: readonly SparqlRow[]): GraphData {
  const nodes: GraphNode[] = [center];
  const seen = new Set([center.iri]);
  const edges: GraphEdge[] = [];
  let dropped = 0;
  for (const row of rows) {
    const direction = cellValue(row, "direction");
    const predicate = cellValue(row, "predicate");
    const other = row.other;
    if (!predicate || !other || other.kind !== "iri") continue;
    const kind = asEdgeKind(predicate);
    if (!kind) continue;
    const otherNode = nodeFromIri(other.value);
    if (!otherNode) continue;
    if (!seen.has(otherNode.iri)) {
      if (nodes.length >= NODE_CAP) {
        dropped += 1;
        continue;
      }
      nodes.push(otherNode);
      seen.add(otherNode.iri);
    }
    const endpoints = directedEnds(direction, center.iri, otherNode.iri);
    if (!endpoints || endpoints.source === endpoints.target) continue;
    edges.push({ source: endpoints.source, target: endpoints.target, kind });
  }
  return { nodes, edges: dedupeEdges(edges), dropped };
}

export function graphFromDisplay(payload: {
  nodes: readonly ProjectedNode[];
  links: readonly ProjectedLink[];
  dropped: number;
}): GraphData {
  const nodes: GraphNode[] = [];
  const seen = new Set<string>();
  let dropped = payload.dropped;
  for (const node of payload.nodes) {
    const built = nodeFromProjected(node);
    if (!built) {
      dropped += 1;
      continue;
    }
    if (seen.has(built.iri)) continue;
    seen.add(built.iri);
    nodes.push(built);
  }
  const edges: GraphEdge[] = [];
  for (const link of payload.links) {
    const kind = asEdgeKind(link.predicate);
    if (!kind || link.source === link.target) continue;
    if (!seen.has(link.source) || !seen.has(link.target)) continue;
    edges.push({ source: link.source, target: link.target, kind });
  }
  return capGraph({ nodes, edges: dedupeEdges(edges), dropped });
}

export function graphFromWhoServes(systems: readonly WhoServesSystem[]): GraphData {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  for (const system of systems) {
    if (!system.iri) continue;
    const node = nodeFromIri(system.iri, system.name, system.sector, system.primary_state);
    if (!node) continue;
    nodes.push({ ...node, kind: classForSectorName(system.sector) });
    if (!system.service_area_iri) continue;
    const area = nodeFromIri(system.service_area_iri, system.service_area_id, null, system.primary_state);
    if (!area) continue;
    nodes.push({ ...area, kind: "ServiceArea", sector: system.sector });
    edges.push({ source: node.iri, target: area.iri, kind: "hasServiceArea" });
  }
  return capGraph({ nodes, edges: dedupeEdges(edges), dropped: 0 });
}

export function capGraph(graph: GraphData, cap = NODE_CAP): GraphData {
  if (graph.nodes.length <= cap) return { ...graph, edges: dedupeEdges(graph.edges) };
  const nodes = graph.nodes.slice(0, cap);
  const ids = new Set(nodes.map((node) => node.iri));
  const edges = dedupeEdges(graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)));
  return { nodes, edges, dropped: graph.dropped + (graph.nodes.length - cap) };
}

export function mergeGraph(current: GraphData, incoming: GraphData, cap = NODE_CAP): GraphData {
  const nodes = current.nodes.map((node) => ({ ...node }));
  const index = new Map(nodes.map((node, position) => [node.iri, position]));
  let dropped = current.dropped + incoming.dropped;
  for (const node of incoming.nodes) {
    const existing = index.get(node.iri);
    if (existing !== undefined) {
      const prior = nodes[existing];
      if (!prior) continue;
      nodes[existing] = preferNode(prior, node);
      continue;
    }
    if (nodes.length >= cap) {
      dropped += 1;
      continue;
    }
    index.set(node.iri, nodes.length);
    nodes.push({ ...node });
  }
  const ids = new Set(nodes.map((node) => node.iri));
  const edges = dedupeEdges(
    [...current.edges, ...incoming.edges].filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
  );
  return { nodes, edges, dropped };
}

export function ownershipTree(rootIri: string, graph: GraphData): TreeItem | null {
  const root = graph.nodes.find((node) => node.iri === rootIri);
  if (!root) return null;
  return {
    iri: root.iri,
    label: root.label,
    kind: root.kind,
    role: "self",
    children: ownershipChildren(root, graph, new Set([root.iri]), true),
  };
}

export function roleLabel(role: TreeRole): string {
  switch (role) {
    case "self":
      return "";
    case "parent":
      return "parent";
    case "subsidiary":
      return "subsidiary";
    case "owner":
      return "owner";
    case "operator":
      return "operator";
    case "owned-system":
      return "system";
    case "operated-system":
      return "operated system";
    default:
      return assertNever(role);
  }
}

function ownershipChildren(
  node: GraphNode,
  graph: GraphData,
  visiting: Set<string>,
  asRoot: boolean,
): TreeItem[] {
  const items: TreeItem[] = [];
  const add = (iri: string, role: TreeRole, descend: boolean) => {
    if (visiting.has(iri) || items.some((item) => item.iri === iri)) return;
    const other = graph.nodes.find((candidate) => candidate.iri === iri);
    if (!other) return;
    const next = new Set(visiting);
    next.add(other.iri);
    items.push({
      iri: other.iri,
      label: other.label,
      kind: other.kind,
      role,
      children: descend ? ownershipChildren(other, graph, next, false) : [],
    });
  };
  if (asRoot) {
    for (const edge of graph.edges) {
      if (edge.target !== node.iri) continue;
      switch (edge.kind) {
        case "parentOf":
          add(edge.source, "parent", false);
          break;
        case "ownsSystem":
          add(edge.source, "owner", true);
          break;
        case "operatesSystem":
          add(edge.source, "operator", true);
          break;
        case "hasServiceArea":
        case "assertedBy":
        case "inState":
        case "locatedInCounty":
        case "servesCounty":
        case "system":
        case "county":
          break;
        default:
          assertNever(edge.kind);
      }
    }
  }
  for (const edge of graph.edges) {
    if (edge.source !== node.iri) continue;
    switch (edge.kind) {
      case "parentOf":
        add(edge.target, "subsidiary", true);
        break;
      case "ownsSystem":
        add(edge.target, "owned-system", false);
        break;
      case "operatesSystem":
        add(edge.target, "operated-system", false);
        break;
      case "hasServiceArea":
      case "assertedBy":
      case "inState":
      case "locatedInCounty":
      case "servesCounty":
      case "system":
      case "county":
        break;
      default:
        assertNever(edge.kind);
    }
  }
  return items;
}

function preferNode(prior: GraphNode, incoming: GraphNode): GraphNode {
  const kind = prior.kind === "UtilitySystem" && incoming.kind !== "UtilitySystem" ? incoming.kind : prior.kind;
  const label = prior.label === localName(prior.iri) && incoming.label ? incoming.label : prior.label;
  return {
    ...prior,
    ...incoming,
    kind,
    label,
    state: incoming.state ?? prior.state,
    sector: incoming.sector ?? prior.sector,
  };
}

function nodeFromProjected(node: ProjectedNode): GraphNode | null {
  if (isNodeKind(node.kind)) {
    return {
      iri: node.iri,
      label: node.label || localName(node.iri),
      kind: node.kind,
      state: node.state || null,
      sector: null,
    };
  }
  return nodeFromIri(node.iri, node.label, null, node.state || null);
}

function directedEnds(
  direction: string | null,
  center: string,
  other: string,
): { source: string; target: string } | null {
  switch (direction) {
    case "out":
      return { source: center, target: other };
    case "in":
      return { source: other, target: center };
    default:
      return null;
  }
}

function kindFromPath(path: string): NodeKind | null {
  const segment = path.split("/")[0] ?? "";
  switch (segment) {
    case "coverage":
      return "CountyCoverage";
    case "system":
      return "UtilitySystem";
    case "org":
      return "Organization";
    case "facility":
      return "Facility";
    case "county":
      return "County";
    case "state":
      return "State";
    case "place":
      return "Place";
    case "source":
      return "Source";
    case "area":
      return "ServiceArea";
    case "relationship":
    case "ontology":
      return null;
    default:
      return null;
  }
}

function isSearchKind(value: string): value is SearchKind {
  switch (value) {
    case "system":
    case "organization":
    case "facility":
    case "county":
    case "place":
    case "state":
      return true;
    default:
      return false;
  }
}

function kindFromSearch(kind: SearchKind, sector: string | null): NodeKind {
  switch (kind) {
    case "system":
      return classForSectorName(sector);
    case "organization":
      return "Organization";
    case "facility":
      return "Facility";
    case "county":
      return "County";
    case "place":
      return "Place";
    case "state":
      return "State";
    default:
      return assertNever(kind);
  }
}

function cellValue(row: SparqlRow, name: string): string | null {
  const cell = row[name];
  if (!cell || typeof cell.value !== "string" || !cell.value) return null;
  return cell.value;
}

function dedupeEdges(edges: readonly GraphEdge[]): GraphEdge[] {
  const output: GraphEdge[] = [];
  const seen = new Set<string>();
  for (const edge of edges) {
    const key = `${edge.source}\n${edge.kind}\n${edge.target}`;
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(edge);
  }
  return output;
}

export function blankGraph(): GraphData {
  return emptyGraph();
}
