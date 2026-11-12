import "./style.css";
import { getScorecard, getStats } from "./api/client";
import type { AskPresentation } from "./api/askStream";
import { createStore, emptyMapFocus } from "./state/store";
import { mountAskPanel } from "./ui/askPanel";
import { el } from "./ui/dom";
import { mountFilters, mountLegend } from "./ui/filters";
import { mountInspector } from "./ui/inspector";
import { mountSearch } from "./ui/searchBox";
import { CoverageMatrix } from "./viz/CoverageMatrix";
import { ForceGraph } from "./viz/ForceGraph";
import { OwnershipTree } from "./viz/OwnershipTree";
import { RankedBarChart } from "./viz/RankedBarChart";
import { TerritoryMap } from "./viz/TerritoryMap";

const store = createStore();
const root = document.querySelector("#app");
if (!root) throw new Error("The workbench root is missing.");

const header = el("header", "wb-header");
const title = el("div");
title.append(el("p", "wb-kicker", "Utility data"), el("h1", undefined, "Workbench"));
const release = el("p", "wb-release");
header.append(title, release);
const status = el("p", "wb-status");
status.setAttribute("role", "status");

const main = el("div", "wb-main");
const side = el("aside", "wb-side");
const filters = el("section", "wb-panel");
const search = el("section", "wb-panel");
const ask = el("section", "wb-panel");
const inspector = el("section", "wb-panel");
const legend = el("section", "wb-panel");
side.append(filters, search, ask, inspector, legend);

const stage = el("div", "wb-stage");
const mapHost = el("section", "wb-panel wb-map-panel");
const lower = el("div", "wb-lower");
const graphHost = el("section", "wb-panel");
const matrixHost = el("section", "wb-panel");
const sideViz = el("div", "wb-sideviz");
const treeHost = el("section", "wb-panel");
const chartHost = el("section", "wb-panel");
sideViz.append(treeHost, chartHost);
lower.append(graphHost, matrixHost, sideViz);
stage.append(mapHost, lower);
main.append(side, stage);
root.append(header, main, status);

mountFilters(filters, store);
mountSearch(search, store);
mountAskPanel(ask, {
  onEntities(presentation: AskPresentation) {
    if (!presentation.drewEntities) return;
    if (presentation.graph) store.replaceGraph(presentation.graph);
    store.setMapFocus(presentation.map
      ? {
          serviceAreaIds: presentation.map.serviceAreaIds,
          countyGeoids: presentation.map.countyGeoids,
          point: null,
          systems: [],
        }
      : emptyMapFocus());
    store.setChart(presentation.chart);
  },
}, store);
mountInspector(inspector, store);
mountLegend(legend, store);
new TerritoryMap(mapHost, store);
new ForceGraph(graphHost, store);
new CoverageMatrix(matrixHost, store);
new OwnershipTree(treeHost, store);
new RankedBarChart(chartHost, store);

store.subscribe(() => {
  const current = store.getState();
  release.textContent = current.release
    ? `${current.release} · ${current.baseIri}`
    : current.baseIri;
  status.textContent = current.status ?? "";
});

void Promise.allSettled([getStats(), getScorecard()]).then((results) => {
  const [stats, scorecard] = results;
  if (stats.status === "fulfilled") store.setRelease(stats.value.release, stats.value.base_iri, stats.value.llm_configured);
  else store.setStatus(stats.reason instanceof Error ? stats.reason.message : "The API is not reachable.");
  if (scorecard.status === "fulfilled") store.setScorecard(scorecard.value.rows);
  else if (stats.status === "fulfilled") {
    store.setStatus(scorecard.reason instanceof Error ? scorecard.reason.message : "The scorecard is not reachable.");
  }
});
