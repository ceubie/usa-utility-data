import { getEntity } from "../api/client";
import { provenanceText, selectionFromEntity } from "../state/entity";
import type { Store } from "../state/store";
import { el } from "./dom";

export function mountInspector(host: HTMLElement, store: Store): void {
  const title = el("h2", undefined, "Inspector");
  const body = el("div");
  host.replaceChildren(title, body);
  let loaded: string | null = null;
  let request = 0;
  const render = () => {
    const selection = store.getState().selection;
    body.replaceChildren();
    if (!selection) {
      body.append(el("p", "wb-quiet", "Select a node, a search result, or a map polygon."));
      return;
    }
    body.append(el("h3", "wb-subhead", selection.label));
    if (selection.kind) body.append(el("p", "wb-kind", selection.kind));
    const attributes = el("dl", "wb-attributes");
    for (const attribute of selection.attributes) {
      attributes.append(el("dt", undefined, attribute.name));
      const value = el("dd");
      value.textContent = attribute.value;
      attributes.append(value);
    }
    body.append(attributes);
    const provenance = el("dl", "wb-provenance");
    provenance.append(el("dt", undefined, "Source"), el("dd", undefined, provenanceText(selection.provenance.source)));
    provenance.append(el("dt", undefined, "Date"), el("dd", undefined, provenanceText(selection.provenance.date)));
    provenance.append(el("dt", undefined, "Authority"), el("dd", undefined, provenanceText(selection.provenance.authority)));
    provenance.append(el("dt", undefined, "Match method"), el("dd", undefined, provenanceText(selection.provenance.matchMethod)));
    provenance.append(el("dt", undefined, "Confidence"), el("dd", undefined, provenanceText(selection.provenance.confidence)));
    body.append(el("h3", "wb-subhead", "Provenance"), provenance);
    if (!selection.iri || loaded === selection.iri) return;
    loaded = selection.iri;
    const token = ++request;
    const prior = selection.provenance;
    void getEntity(selection.iri)
      .then((entity) => {
        if (token !== request) return;
        store.applyReading(selectionFromEntity(entity.iri, entity.rows, prior));
      })
      .catch((error: unknown) => {
        if (token !== request) return;
        store.setStatus(error instanceof Error ? error.message : "The entity description failed.");
      });
  };
  store.subscribe(render);
  render();
}
