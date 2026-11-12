import { AUTHORITIES, NODE_KINDS, SECTORS } from "../types/graph";
import type { Store } from "../state/store";
import { authorityColor, formatShare, sectorNonmodeledShare } from "../viz/scales";
import { colorForKind } from "../viz/scales";
import { el } from "./dom";

export function mountFilters(host: HTMLElement, store: Store): void {
  host.replaceChildren(el("h2", undefined, "Filters"));
  const form = el("div", "wb-filters");
  const sector = select("Sector", "filter-sector", [["", "Any sector"], ...SECTORS.map((item) => [item, item] as [string, string])]);
  const state = select("State", "filter-state", [["", "All states"]]);
  const authority = select("Authority", "filter-authority", [
    ["", "Any authority"],
    ...AUTHORITIES.map((item) => [item, item] as [string, string]),
  ]);
  form.append(sector.label, sector.input, state.label, state.input, authority.label, authority.input);
  host.append(form);
  let optionsKey = "";
  const render = () => {
    const current = store.getState();
    const nextKey = stateOptionKey(current);
    if (nextKey !== optionsKey) {
      optionsKey = nextKey;
      fillStates(state.input, current);
    }
    sector.input.value = current.filters.sector ?? "";
    if (state.input.value !== (current.filters.state ?? "")) state.input.value = current.filters.state ?? "";
    authority.input.value = current.filters.authority ?? "";
  };
  sector.input.addEventListener("change", () => {
    store.setFilters({ sector: sector.input.value || null });
  });
  state.input.addEventListener("change", () => {
    store.setFilters({ state: state.input.value || null });
  });
  authority.input.addEventListener("change", () => {
    store.setFilters({ authority: authority.input.value || null });
  });
  store.subscribe(render);
  render();
}

export function mountLegend(host: HTMLElement, store: Store): void {
  host.replaceChildren(el("h2", undefined, "Legend"));
  const kinds = el("ul", "wb-legend");
  for (const kind of NODE_KINDS) {
    const item = el("li");
    const swatch = el("span", "wb-swatch");
    swatch.style.background = colorForKind(kind);
    item.append(swatch, document.createTextNode(kind));
    kinds.append(item);
  }
  const share = el("p", "wb-share");
  const shade = el("div", "wb-shade");
  const providers = radio("providers", "Provider count");
  const authority = radio("authority", "Best authority");
  shade.append(providers.label, authority.label);
  const authorities = el("ul", "wb-legend");
  for (const name of AUTHORITIES) {
    const item = el("li");
    const swatch = el("span", "wb-swatch");
    swatch.style.background = authorityColor(name);
    item.append(swatch, document.createTextNode(name));
    authorities.append(item);
  }
  const modeled = el("p", "wb-quiet", "A dashed service-area outline means boundary_representation is modeled. Mixed, unknown, and unmodeled outlines stay solid.");
  const edges = el("p", "wb-quiet", "operatesSystem and locatedInCounty are drawn only when a result includes those edges.");
  host.append(kinds, shade, authorities, modeled, edges, share);
  const render = () => {
    const current = store.getState();
    providers.input.checked = current.shade === "providers";
    authority.input.checked = current.shade === "authority";
    const water = sectorNonmodeledShare(current.scorecard, "water");
    share.textContent = water === null
      ? "Water non-modeled population share is not in the scorecard."
      : `Water non-modeled population share: ${formatShare(water)}`;
  };
  providers.input.addEventListener("change", () => {
    if (providers.input.checked) store.setShade("providers");
  });
  authority.input.addEventListener("change", () => {
    if (authority.input.checked) store.setShade("authority");
  });
  store.subscribe(render);
  render();
}

function select(name: string, id: string, options: readonly [string, string][]): { label: HTMLLabelElement; input: HTMLSelectElement } {
  const label = el("label", "wb-label", name);
  const input = el("select");
  input.id = id;
  label.htmlFor = id;
  for (const [value, text] of options) input.append(option(value, text));
  return { label, input };
}

function stateOptionKey(state: ReturnType<Store["getState"]>): string {
  return [...state.geoStates.map((item) => item.usps), ...state.scorecard.map((row) => row.state ?? "")].join("|");
}

function fillStates(input: HTMLSelectElement, state: ReturnType<Store["getState"]>): void {
  const selected = state.filters.state ?? "";
  const names = new Map(state.geoStates.map((item) => [item.usps, item.name]));
  for (const row of state.scorecard) {
    if (row.state && !names.has(row.state)) names.set(row.state, row.state);
  }
  const options = [...names.entries()].sort((left, right) => left[1].localeCompare(right[1]));
  input.replaceChildren(option("", "All states"));
  for (const [usps, name] of options) input.append(option(usps, `${name} (${usps})`));
  input.value = selected;
}

function option(value: string, text: string): HTMLOptionElement {
  const node = el("option", undefined, text);
  node.value = value;
  return node;
}

function radio(value: "providers" | "authority", text: string): { label: HTMLLabelElement; input: HTMLInputElement } {
  const label = el("label", "wb-radio");
  const input = el("input");
  input.type = "radio";
  input.name = "county-shade";
  input.value = value;
  label.append(input, document.createTextNode(text));
  return { label, input };
}
