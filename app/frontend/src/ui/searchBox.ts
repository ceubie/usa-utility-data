import { expandGraph, searchEntities } from "../api/client";
import type { SearchRow } from "../types/api";
import { graphFromNeighbors, nodeFromSearch } from "../viz/graphData";
import { selectionFromSearch } from "../state/entity";
import type { Store } from "../state/store";
import { el } from "./dom";

export function mountSearch(host: HTMLElement, store: Store): void {
  host.replaceChildren();
  host.append(el("h2", undefined, "Search"));
  const form = el("form", "wb-search-form");
  const label = el("label", "wb-label", "Name or identifier");
  const input = el("input");
  input.type = "search";
  input.id = "entity-search";
  label.htmlFor = input.id;
  const button = el("button", "wb-button", "Search");
  button.type = "submit";
  form.append(label, input, button);
  const list = el("ul", "wb-results");
  const note = el("p", "wb-quiet");
  host.append(form, note, list);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = input.value.trim();
    if (!query) return;
    void run(query);
  });

  async function run(query: string): Promise<void> {
    note.textContent = "Searching";
    list.replaceChildren();
    try {
      const state = store.getState().filters.state;
      const response = await searchEntities(query, { state, limit: 25 });
      note.textContent = `${response.row_count} matches`;
      for (const row of response.rows) list.append(resultItem(row));
      if (response.rows.length === 0) note.textContent = "No matches.";
    } catch (error) {
      note.textContent = error instanceof Error ? error.message : "Search failed.";
    }
  }

  function resultItem(row: SearchRow): HTMLLIElement {
    const item = el("li");
    const choice = el("button", "wb-result");
    choice.type = "button";
    const title = row.label || row.id || row.iri || "Untitled";
    choice.textContent = [title, row.kind, row.state].filter(Boolean).join(" · ");
    choice.addEventListener("click", () => {
      void choose(row);
    });
    item.append(choice);
    return item;
  }

  async function choose(row: SearchRow): Promise<void> {
    const node = nodeFromSearch(row);
    if (node) store.mergeGraph({ nodes: [node], edges: [], dropped: 0 });
    store.setSelection(selectionFromSearch({
      iri: row.iri,
      label: row.label,
      kind: node?.kind ?? null,
      match: row.match,
      state: row.state,
      sector: row.sector,
      status: row.status,
    }));
    if (!row.iri || !node) return;
    try {
      const expanded = await expandGraph(row.iri, 50);
      store.mergeGraph(graphFromNeighbors(node, expanded.rows));
    } catch (error) {
      store.setStatus(error instanceof Error ? error.message : "The neighborhood could not be loaded.");
    }
  }
}
