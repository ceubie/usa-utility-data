import * as d3 from "d3";
import { expandGraph, getServiceAreas, whoServes } from "../api/client";
import { loadCountyStats } from "../api/countyStats";
import { POLYGON_CAP } from "../limits";
import type { MapFeature, WhoServesSystem } from "../types/api";
import { assertNever, classForSectorName, type NodeKind } from "../types/graph";
import { selectionFromProperties } from "../state/entity";
import type { MapClickMode, Store, WorkbenchState } from "../state/store";
import { el } from "../ui/dom";
import { graphFromNeighbors, graphFromWhoServes } from "./graphData";
import {
  capFeatures,
  featureBBox,
  featuresFromTopology,
  isModeledBoundary,
  pathCount,
  planAreaRequest,
  propertyString,
  useCanvas,
  withBoundaryRepresentation,
} from "./mapData";
import { nationalProjection, projectsInNationalView, stateProjection } from "./projection";
import { canvasPathLimit, countyShadeColor, providersFor } from "./scales";

export class TerritoryMap {
  private readonly note = el("p", "wb-quiet");
  private readonly stage = el("div", "wb-map-stage");
  private readonly canvas: HTMLCanvasElement;
  private readonly svg: SVGSVGElement;
  private readonly viewport: SVGGElement;
  private readonly zoom: d3.ZoomBehavior<SVGSVGElement, unknown>;
  private states: MapFeature[] = [];
  private counties: MapFeature[] = [];
  private areas: MapFeature[] = [];
  private areaNote = "";
  private baseNote = "";
  private ready = false;
  private fetchKey = "";
  private areaToken = 0;
  private statsToken = 0;
  private projectionKey = "";
  private transform: d3.ZoomTransform = d3.zoomIdentity;
  private projection: d3.GeoProjection = d3.geoAlbersUsa();
  private width = 800;
  private height = 520;
  private drawnCounties: MapFeature[] = [];
  private drawnAreas: MapFeature[] = [];
  private drawnStates: MapFeature[] = [];
  private unsubscribe: () => void;
  private observer: ResizeObserver;

  constructor(
    private readonly host: HTMLElement,
    private readonly store: Store,
  ) {
    this.host.replaceChildren(el("h2", undefined, "Map"));
    const bar = el("div", "wb-map-bar");
    bar.append(modeButton(store, "inspect", "Inspect polygon"), modeButton(store, "who-serves", "Who serves"), this.note);
    this.canvas = document.createElement("canvas");
    this.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    this.svg.setAttribute("role", "img");
    this.svg.setAttribute("aria-label", "Territory map");
    this.viewport = document.createElementNS("http://www.w3.org/2000/svg", "g");
    this.svg.append(this.viewport);
    this.stage.append(this.canvas, this.svg);
    this.host.append(bar, this.stage);
    this.zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([1, 8])
      .filter((event: Event) => event.type !== "dblclick")
      .on("zoom", (event: d3.D3ZoomEvent<SVGSVGElement, unknown>) => {
        this.transform = event.transform;
        this.viewport.setAttribute("transform", event.transform.toString());
        this.paintCanvas();
      });
    d3.select(this.svg).call(this.zoom);
    this.svg.addEventListener("click", (event) => {
      this.onClick(event);
    });
    this.observer = new ResizeObserver(() => {
      this.drawScene();
    });
    this.observer.observe(this.stage);
    this.unsubscribe = this.store.subscribe(() => {
      this.sync();
    });
    void this.loadBase();
  }

  destroy(): void {
    this.unsubscribe();
    this.observer.disconnect();
  }

  private async loadBase(): Promise<void> {
    try {
      const [states, counties] = await Promise.all([
        fetch("/geo/states.topo.json").then((response) => readJson(response, "states")),
        fetch("/geo/counties.topo.json").then((response) => readJson(response, "counties")),
      ]);
      this.states = featuresFromTopology(states);
      this.counties = featuresFromTopology(counties);
      if (this.states.length === 0 || this.counties.length === 0) {
        throw new Error("Base map topology did not contain features.");
      }
      this.ready = true;
      this.baseNote = "";
      this.store.setGeoStates(this.states.flatMap((item) => {
        const usps = propertyString(item, "STUSPS");
        const name = propertyString(item, "NAME");
        const fips = propertyString(item, "STATEFP");
        return usps && name && fips ? [{ usps, name, fips }] : [];
      }));
    } catch {
      this.baseNote = "Base maps are not available. Run npm run geo. No geometries were invented.";
      this.drawScene();
    }
  }

  private sync(): void {
    const state = this.store.getState();
    const key = JSON.stringify({
      state: state.filters.state,
      sector: state.filters.sector,
      authority: state.filters.authority,
      ids: state.mapFocus.serviceAreaIds,
      point: state.mapFocus.point,
    });
    if (this.ready && key !== this.fetchKey) {
      this.fetchKey = key;
      void this.loadAreas(state);
      void this.refreshStats(this.fipsFor(state.filters.state), state.filters.sector);
    }
    this.drawScene();
  }

  private async loadAreas(state: WorkbenchState): Promise<void> {
    const token = ++this.areaToken;
    const selected = this.stateFeature(state.filters.state);
    const bbox = selected ? featureBBox(selected) : null;
    const explicit = [
      ...state.mapFocus.serviceAreaIds,
      ...state.mapFocus.systems.flatMap((system) => (system.service_area_id ? [system.service_area_id] : [])),
    ];
    const plan = planAreaRequest({ explicitIds: explicit, bbox, sector: state.filters.sector });
    if (plan.mode === "none") {
      this.areas = [];
      this.areaNote = "";
      if (token === this.areaToken) this.drawScene();
      return;
    }
    try {
      const collection = await getServiceAreas({
        ids: plan.ids,
        bbox: plan.bbox,
        sector: plan.sector,
        limit: POLYGON_CAP,
      });
      if (token !== this.areaToken) return;
      const capped = capFeatures(collection.features);
      this.areas = capped.features;
      this.areaNote = collection.truncated || capped.truncated || plan.omitted > 0
        ? "Service areas are capped at 300."
        : "";
      this.drawScene();
    } catch (error) {
      if (token !== this.areaToken) return;
      this.areas = [];
      this.areaNote = error instanceof Error ? error.message : "Service areas failed.";
      this.drawScene();
    }
  }

  private async refreshStats(fips: string | null, sector: string | null): Promise<void> {
    const token = ++this.statsToken;
    if (!fips) {
      this.store.setCountyStats([], false, null);
      return;
    }
    const result = await loadCountyStats(fips, sector);
    if (token !== this.statsToken) return;
    this.store.setCountyStats(result.stats, result.complete, result.note);
  }

  private drawScene(): void {
    const state = this.store.getState();
    this.width = Math.max(this.stage.clientWidth, 320);
    this.height = Math.max(this.stage.clientHeight, 420);
    const selected = this.stateFeature(state.filters.state);
    const nextKey = selected ? propertyString(selected, "STUSPS") ?? "state" : "national";
    if (nextKey !== this.projectionKey) {
      this.projectionKey = nextKey;
      this.transform = d3.zoomIdentity;
      this.viewport.removeAttribute("transform");
    }
    this.projection = selected
      ? stateProjection(selected, this.width, this.height)
      : nationalProjection(this.width, this.height);
    const fips = selected ? propertyString(selected, "STATEFP") : null;
    this.drawnStates = selected
      ? [selected]
      : this.states.filter((item) => projectsInNationalView(item, this.projection));
    this.drawnCounties = (fips
      ? this.counties.filter((item) => propertyString(item, "STATEFP") === fips)
      : this.counties.filter((item) => projectsInNationalView(item, this.projection)));
    const represented = withBoundaryRepresentation(this.areas, state.mapFocus.systems, state.representations);
    this.drawnAreas = represented.filter((item) => {
      if (!state.filters.authority) return true;
      return propertyString(item, "authority") === state.filters.authority;
    });
    this.note.textContent = [this.baseNote, this.areaNote, state.countyNote, this.clickHint(state.mapClick)]
      .filter(Boolean)
      .join(" ");
    this.paintCanvas();
    this.paintSvg(state);
  }

  private paintCanvas(): void {
    const context = this.canvas.getContext("2d");
    if (!context) return;
    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.floor(this.width * ratio);
    this.canvas.height = Math.floor(this.height * ratio);
    this.canvas.style.width = `${this.width}px`;
    this.canvas.style.height = `${this.height}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, this.width, this.height);
    context.save();
    context.translate(this.transform.x, this.transform.y);
    context.scale(this.transform.k, this.transform.k);
    const limit = canvasPathLimit();
    if (useCanvas(pathCount(this.drawnCounties), limit)) this.fillCounties(context);
    if (useCanvas(pathCount(this.drawnAreas), limit)) this.strokeAreas(context);
    context.restore();
  }

  private fillCounties(context: CanvasRenderingContext2D): void {
    const state = this.store.getState();
    const path = d3.geoPath(this.projection, context);
    for (const county of this.drawnCounties) {
      const geoid = propertyString(county, "GEOID");
      context.beginPath();
      path(county);
      context.fillStyle = geoid
        ? countyShadeColor(
          state.shade,
          providersFor(geoid, state.countyStats, state.countyStatsComplete),
          state.countyStats.find((item) => item.geoid === geoid)?.authorities ?? [],
        )
        : "#d9d3c7";
      context.fill();
      context.strokeStyle = state.mapFocus.countyGeoids.includes(geoid ?? "") ? "#1c1915" : "#cfc6b8";
      context.lineWidth = state.mapFocus.countyGeoids.includes(geoid ?? "") ? 1.4 : 0.4;
      context.stroke();
    }
  }

  private strokeAreas(context: CanvasRenderingContext2D): void {
    const path = d3.geoPath(this.projection, context);
    for (const area of this.drawnAreas) {
      context.beginPath();
      path(area);
      context.strokeStyle = "#1d4e5f";
      context.lineWidth = 1.2;
      context.setLineDash(isModeledBoundary(area.properties) ? [5, 3] : []);
      context.stroke();
    }
    context.setLineDash([]);
  }

  private paintSvg(state: WorkbenchState): void {
    const limit = canvasPathLimit();
    const countiesOnSvg = !useCanvas(pathCount(this.drawnCounties), limit);
    const areasOnSvg = !useCanvas(pathCount(this.drawnAreas), limit);
    this.svg.setAttribute("viewBox", `0 0 ${this.width} ${this.height}`);
    this.viewport.replaceChildren();
    const path = d3.geoPath(this.projection);
    if (countiesOnSvg) {
      for (const county of this.drawnCounties) {
        const geoid = propertyString(county, "GEOID") ?? "";
        this.viewport.append(svgPath(path(county) ?? "", {
          fill: countyShadeColor(
            state.shade,
            providersFor(geoid, state.countyStats, state.countyStatsComplete),
            state.countyStats.find((item) => item.geoid === geoid)?.authorities ?? [],
          ),
          stroke: state.mapFocus.countyGeoids.includes(geoid) ? "#1c1915" : "#cfc6b8",
          width: state.mapFocus.countyGeoids.includes(geoid) ? "1.4" : "0.4",
        }));
      }
    }
    for (const item of this.drawnStates) {
      this.viewport.append(svgPath(path(item) ?? "", { fill: "none", stroke: "#1c1915", width: "1" }));
    }
    if (areasOnSvg) {
      for (const area of this.drawnAreas) {
        const shape = svgPath(path(area) ?? "", { fill: "rgba(29, 106, 138, 0.18)", stroke: "#1d4e5f", width: "1.4" });
        if (isModeledBoundary(area.properties)) shape.setAttribute("stroke-dasharray", "5 3");
        this.viewport.append(shape);
      }
    }
    for (const facility of state.facilities) {
      const point = this.projection([facility.longitude, facility.latitude]);
      if (!point) continue;
      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("cx", String(point[0]));
      dot.setAttribute("cy", String(point[1]));
      dot.setAttribute("r", "4");
      dot.setAttribute("fill", "#a33b4a");
      this.viewport.append(dot);
    }
    if (state.mapFocus.point) {
      const point = this.projection([state.mapFocus.point.lon, state.mapFocus.point.lat]);
      if (point) {
        const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        dot.setAttribute("cx", String(point[0]));
        dot.setAttribute("cy", String(point[1]));
        dot.setAttribute("r", "5");
        dot.setAttribute("fill", "none");
        dot.setAttribute("stroke", "#8c3b2a");
        dot.setAttribute("stroke-width", "2");
        this.viewport.append(dot);
      }
    }
    this.viewport.setAttribute("transform", this.transform.toString());
  }

  private onClick(event: MouseEvent): void {
    const lonLat = this.pointerLonLat(event);
    if (!lonLat) return;
    const [lon, lat] = lonLat;
    const mode = this.store.getState().mapClick;
    switch (mode) {
      case "who-serves":
        void this.askWhoServes(lat, lon);
        return;
      case "inspect":
        break;
      default:
        assertNever(mode);
    }
    const facility = this.hitFacility(event);
    if (facility) {
      this.store.setSelection(selectionFromProperties(facility.iri, facility.label, "Facility", {}, null));
      return;
    }
    const area = this.hit(this.drawnAreas, lon, lat);
    if (area) {
      this.inspectFeature(area, "area");
      return;
    }
    const county = this.hit(this.drawnCounties, lon, lat);
    if (county) {
      this.inspectFeature(county, "county");
      return;
    }
    const state = this.hit(this.drawnStates, lon, lat);
    if (state) {
      this.inspectFeature(state, "state");
      return;
    }
    void this.askWhoServes(lat, lon);
  }

  private inspectFeature(item: MapFeature, layer: "state" | "county" | "area"): void {
    const base = this.store.getState().baseIri || "http://utilities.local/";
    const properties = item.properties ?? {};
    switch (layer) {
      case "state": {
        const usps = propertyString(item, "STUSPS");
        this.store.setSelection(selectionFromProperties(
          usps ? `${base}state/${usps}` : null,
          propertyString(item, "NAME") ?? usps ?? "State",
          "State",
          properties,
          null,
        ));
        if (usps) this.store.setFilters({ state: usps });
        return;
      }
      case "county": {
        const geoid = propertyString(item, "GEOID");
        this.store.setSelection(selectionFromProperties(
          geoid ? `${base}county/${geoid}` : null,
          propertyString(item, "NAME") ?? geoid ?? "County",
          "County",
          properties,
          null,
        ));
        return;
      }
      case "area": {
        const id = propertyString(item, "service_area_id");
        this.store.setSelection(selectionFromProperties(
          id ? `${base}area/${id}` : null,
          propertyString(item, "system_id") ?? id ?? "Service area",
          "ServiceArea",
          properties,
          null,
        ));
        return;
      }
      default:
        assertNever(layer);
    }
  }

  private async askWhoServes(lat: number, lon: number): Promise<void> {
    const sector = this.store.getState().filters.sector;
    if (!sector) {
      this.store.setStatus("Choose a sector before asking who serves.");
      return;
    }
    try {
      const response = await whoServes(lat, lon, sector);
      const authority = this.store.getState().filters.authority;
      const systems = authority ? response.systems.filter((system) => system.authority === authority) : response.systems;
      const graph = graphFromWhoServes(systems);
      this.store.mergeGraph(graph);
      this.store.setMapFocus({
        serviceAreaIds: systems.flatMap((system) => (system.service_area_id ? [system.service_area_id] : [])).slice(0, POLYGON_CAP),
        countyGeoids: [],
        point: { lat, lon },
        systems,
      });
      const first = systems[0];
      if (!first?.iri) {
        this.store.setStatus(systems.length === 0 ? `No ${sector} system serves this point.` : "Who serves returned a system without an IRI.");
        return;
      }
      const node = graph.nodes.find((item) => item.iri === first.iri);
      this.store.setSelection(selectionFromWhoServes(first, node?.kind ?? classForSectorName(first.sector)));
      if (!node) return;
      try {
        const expanded = await expandGraph(first.iri, 50);
        this.store.mergeGraph(graphFromNeighbors(node, expanded.rows));
      } catch (error) {
        this.store.setStatus(error instanceof Error ? error.message : "Neighbors were not loaded.");
      }
    } catch (error) {
      this.store.setStatus(error instanceof Error ? error.message : "Who serves failed.");
    }
  }

  private pointerLonLat(event: MouseEvent): [number, number] | null {
    const pointer = d3.pointer(event, this.svg);
    const [x, y] = this.transform.invert(pointer);
    const inverted = this.projection.invert?.([x, y]);
    if (!inverted || !Number.isFinite(inverted[0]) || !Number.isFinite(inverted[1])) return null;
    return [inverted[0], inverted[1]];
  }

  private hit(features: readonly MapFeature[], lon: number, lat: number): MapFeature | null {
    for (let index = features.length - 1; index >= 0; index -= 1) {
      const item = features[index];
      if (item && d3.geoContains(item, [lon, lat])) return item;
    }
    return null;
  }

  private hitFacility(event: MouseEvent): { iri: string; label: string } | null {
    const pointer = d3.pointer(event, this.svg);
    for (const facility of this.store.getState().facilities) {
      const projected = this.projection([facility.longitude, facility.latitude]);
      if (!projected) continue;
      const [x, y] = this.transform.apply(projected);
      const dx = pointer[0] - x;
      const dy = pointer[1] - y;
      if (dx * dx + dy * dy <= 144) return facility;
    }
    return null;
  }

  private stateFeature(usps: string | null): MapFeature | null {
    if (!usps) return null;
    return this.states.find((item) => propertyString(item, "STUSPS") === usps) ?? null;
  }

  private fipsFor(usps: string | null): string | null {
    const feature = this.stateFeature(usps);
    return feature ? propertyString(feature, "STATEFP") : null;
  }

  private clickHint(mode: MapClickMode): string {
    switch (mode) {
      case "inspect":
        return "Click a polygon to inspect it. Click empty map to ask who serves that point.";
      case "who-serves":
        return "Click the map to ask who serves that point.";
      default:
        return assertNever(mode);
    }
  }
}

function modeButton(store: Store, mode: MapClickMode, text: string): HTMLButtonElement {
  const button = el("button", "wb-button", text);
  button.type = "button";
  const paint = () => {
    button.setAttribute("aria-pressed", store.getState().mapClick === mode ? "true" : "false");
  };
  button.addEventListener("click", () => {
    store.setMapClick(mode);
  });
  store.subscribe(paint);
  paint();
  return button;
}

function svgPath(d: string, style: { fill: string; stroke: string; width: string }): SVGPathElement {
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", d);
  path.setAttribute("fill", style.fill);
  path.setAttribute("stroke", style.stroke);
  path.setAttribute("stroke-width", style.width);
  path.setAttribute("pointer-events", "none");
  return path;
}

function selectionFromWhoServes(system: WhoServesSystem, kind: NodeKind) {
  const properties: Record<string, string> = {};
  for (const [name, value] of Object.entries(system)) {
    if (typeof value === "string" && value) properties[name] = value;
  }
  return selectionFromProperties(system.iri, system.name || system.system_id || system.iri || "System", kind, properties, "exact point-in-polygon");
}

async function readJson(response: Response, name: string): Promise<unknown> {
  if (!response.ok) throw new Error(`The ${name} base map was not found.`);
  return response.json() as Promise<unknown>;
}
