import type { ScorecardRow } from "../types/api";
import type { Store } from "../state/store";
import { coverageColor, formatShare, sectorNonmodeledShare } from "./scales";
import { el } from "../ui/dom";

export class CoverageMatrix {
  private readonly caption = el("p", "wb-share");
  private readonly tableHost = el("div", "wb-matrix-scroll");
  private unsubscribe: () => void;

  constructor(
    private readonly host: HTMLElement,
    private readonly store: Store,
  ) {
    this.host.replaceChildren(el("h2", undefined, "Coverage"), this.caption, this.tableHost);
    this.unsubscribe = this.store.subscribe(() => {
      this.render();
    });
    this.render();
  }

  destroy(): void {
    this.unsubscribe();
  }

  private render(): void {
    const rows = this.store.getState().scorecard;
    const water = sectorNonmodeledShare(rows, "water");
    this.caption.textContent = water === null
      ? "Water non-modeled population share is not in the scorecard."
      : `Water non-modeled population share: ${formatShare(water)}`;
    this.tableHost.replaceChildren();
    if (rows.length === 0) {
      this.tableHost.append(el("p", "wb-quiet", "The scorecard is not loaded."));
      return;
    }
    const sectors = unique(rows.map((row) => row.sector));
    const states = unique(rows.map((row) => row.state ?? "")).filter(Boolean).sort();
    const table = el("table", "wb-matrix");
    const head = el("tr");
    head.append(el("th", undefined, "State"));
    for (const sector of sectors) head.append(el("th", undefined, sector));
    const thead = el("thead");
    thead.append(head);
    const tbody = el("tbody");
    const filters = this.store.getState().filters;
    for (const state of states) {
      const tr = el("tr");
      tr.append(el("th", undefined, state));
      for (const sector of sectors) {
        const row = rows.find((item) => item.state === state && item.sector === sector) ?? null;
        tr.append(cell(row, filters.state === state && filters.sector === sector, () => {
          this.store.setFilters({ state, sector });
        }));
      }
      tbody.append(tr);
    }
    table.replaceChildren(thead, tbody);
    this.tableHost.append(table);
  }
}

function cell(row: ScorecardRow | null, active: boolean, onClick: () => void): HTMLTableCellElement {
  const node = el("td");
  const share = row?.share_population_nonmodeled ?? null;
  node.style.background = coverageColor(row ? share : null);
  node.textContent = share === null ? "—" : formatShare(share);
  node.classList.toggle("is-active", active);
  if (row?.state) {
    const button = el("button", "wb-cell");
    button.type = "button";
    button.textContent = node.textContent;
    button.style.background = node.style.background;
    button.addEventListener("click", onClick);
    node.textContent = "";
    node.append(button);
  }
  return node;
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values)];
}
