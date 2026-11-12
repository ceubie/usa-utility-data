import type { CountyStat } from "../api/countyStats";
import type { AskPresentation, ToolStep } from "../api/askStream";
import type { ScorecardRow, WhoServesSystem } from "../types/api";
import { type GraphData, type GraphNode, emptyGraph } from "../types/graph";
import type { ShadeMode } from "../viz/scales";
import { capGraph, mergeGraph } from "../viz/graphData";
import { NODE_CAP } from "../limits";
import type { EntityReading, PlacedFacility, Selection } from "./entity";

export interface Filters {
  sector: string | null;
  state: string | null;
  authority: string | null;
}

export interface GeoStateOption {
  usps: string;
  name: string;
  fips: string;
}

export interface MapFocus {
  serviceAreaIds: string[];
  countyGeoids: string[];
  point: { lat: number; lon: number } | null;
  systems: WhoServesSystem[];
}

export type MapClickMode = "inspect" | "who-serves";

export interface WorkbenchState {
  filters: Filters;
  shade: ShadeMode;
  mapClick: MapClickMode;
  selection: Selection | null;
  answer: {
    markdown: string;
    error: string | null;
    steps: ToolStep[];
    queries: string[];
    drewEntities: boolean;
  };
  graph: GraphData;
  mapFocus: MapFocus;
  chart: AskPresentation["chart"];
  scorecard: ScorecardRow[];
  countyStats: CountyStat[];
  countyStatsComplete: boolean;
  countyNote: string | null;
  facilities: PlacedFacility[];
  representations: Record<string, string>;
  geoStates: GeoStateOption[];
  release: string | null;
  baseIri: string;
  llmConfigured: boolean | null;
  status: string | null;
}

export interface Store {
  getState(): WorkbenchState;
  subscribe(listener: () => void): () => void;
  setFilters(patch: Partial<Filters>): void;
  setShade(shade: ShadeMode): void;
  setMapClick(mode: MapClickMode): void;
  setSelection(selection: Selection): void;
  applyReading(reading: EntityReading): void;
  setAnswer(answer: WorkbenchState["answer"]): void;
  replaceGraph(graph: GraphData): void;
  mergeGraph(graph: GraphData): void;
  updateNode(iri: string, patch: Partial<GraphNode>): void;
  setMapFocus(focus: MapFocus): void;
  setScorecard(rows: ScorecardRow[]): void;
  setCountyStats(stats: CountyStat[], complete: boolean, note: string | null): void;
  setChart(chart: AskPresentation["chart"]): void;
  placeFacility(facility: PlacedFacility): void;
  setGeoStates(states: GeoStateOption[]): void;
  setRelease(release: string, baseIri: string, llmConfigured?: boolean): void;
  setStatus(message: string | null): void;
}

export function emptyMapFocus(): MapFocus {
  return { serviceAreaIds: [], countyGeoids: [], point: null, systems: [] };
}

export function createStore(): Store {
  let state = initialState();
  const listeners = new Set<() => void>();
  const emit = () => {
    for (const listener of listeners) listener();
  };
  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    setFilters(patch) {
      state = { ...state, filters: { ...state.filters, ...patch }, mapFocus: emptyMapFocus() };
      emit();
    },
    setShade(shade) {
      state = { ...state, shade };
      emit();
    },
    setMapClick(mapClick) {
      state = { ...state, mapClick };
      emit();
    },
    setSelection(selection) {
      state = { ...state, selection };
      emit();
    },
    applyReading(reading) {
      const facilities = reading.facility
        ? capFacilities([...state.facilities.filter((item) => item.iri !== reading.facility?.iri), reading.facility])
        : state.facilities;
      const representations = reading.representation
        ? { ...state.representations, [reading.representation.id]: reading.representation.value }
        : state.representations;
      const graph = reading.selection.kind && reading.selection.iri
        ? {
            ...state.graph,
            nodes: state.graph.nodes.map((node) =>
              node.iri === reading.selection.iri
                ? {
                    ...node,
                    label: reading.selection.label,
                    kind: reading.selection.kind ?? node.kind,
                  }
                : node,
            ),
          }
        : state.graph;
      state = { ...state, selection: reading.selection, facilities, representations, graph };
      emit();
    },
    setAnswer(answer) {
      state = { ...state, answer };
      emit();
    },
    replaceGraph(graph) {
      state = { ...state, graph: capGraph(graph) };
      emit();
    },
    mergeGraph(graph) {
      state = { ...state, graph: mergeGraph(state.graph, graph) };
      emit();
    },
    updateNode(iri, patch) {
      state = {
        ...state,
        graph: {
          ...state.graph,
          nodes: state.graph.nodes.map((node) => (node.iri === iri ? { ...node, ...patch, iri } : node)),
        },
      };
      emit();
    },
    setMapFocus(mapFocus) {
      state = { ...state, mapFocus };
      emit();
    },
    setScorecard(scorecard) {
      state = { ...state, scorecard };
      emit();
    },
    setCountyStats(countyStats, countyStatsComplete, countyNote) {
      state = { ...state, countyStats, countyStatsComplete, countyNote };
      emit();
    },
    setChart(chart) {
      state = { ...state, chart };
      emit();
    },
    placeFacility(facility) {
      state = {
        ...state,
        facilities: capFacilities([...state.facilities.filter((item) => item.iri !== facility.iri), facility]),
      };
      emit();
    },
    setGeoStates(geoStates) {
      state = { ...state, geoStates };
      emit();
    },
    setRelease(release, baseIri, llmConfigured) {
      state = { ...state, release, baseIri, llmConfigured: llmConfigured ?? state.llmConfigured };
      emit();
    },
    setStatus(status) {
      state = { ...state, status };
      emit();
    },
  };
}

function initialState(): WorkbenchState {
  return {
    filters: { sector: "water", state: null, authority: null },
    shade: "providers",
    mapClick: "inspect",
    selection: null,
    answer: { markdown: "", error: null, steps: [], queries: [], drewEntities: false },
    graph: emptyGraph(),
    mapFocus: emptyMapFocus(),
    chart: null,
    scorecard: [],
    countyStats: [],
    countyStatsComplete: false,
    countyNote: null,
    facilities: [],
    representations: {},
    geoStates: [],
    release: null,
    baseIri: "http://utilities.local/",
    llmConfigured: null,
    status: null,
  };
}

function capFacilities(facilities: PlacedFacility[]): PlacedFacility[] {
  return facilities.slice(-NODE_CAP);
}
