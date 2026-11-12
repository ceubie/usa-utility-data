import * as d3 from "d3";
import { expandGraph } from "../api/client";
import type { Store } from "../state/store";
import { graphFromNeighbors, ownershipTree, roleLabel, type TreeItem } from "./graphData";
import { colorForKind } from "./scales";
import { el } from "../ui/dom";

export class OwnershipTree {
  private readonly note = el("p", "wb-quiet");
  private readonly svg: SVGSVGElement;
  private readonly collapsed = new Set<string>();
  private unsubscribe: () => void;

  constructor(
    private readonly host: HTMLElement,
    private readonly store: Store,
  ) {
    this.host.replaceChildren(el("h2", undefined, "Ownership"), this.note);
    this.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    this.svg.classList.add("wb-svg", "wb-tree");
    this.host.append(this.svg);
    this.unsubscribe = this.store.subscribe(() => {
      this.render();
    });
    this.render();
  }

  destroy(): void {
    this.unsubscribe();
  }

  private render(): void {
    const { selection, graph } = this.store.getState();
    const full = selection?.iri ? ownershipTree(selection.iri, graph) : null;
    this.svg.replaceChildren();
    if (!full) {
      this.note.textContent = "Select an organization or system. The tree uses parentOf, ownsSystem, and operatesSystem edges that are already loaded.";
      return;
    }
    this.note.textContent = "Parents, subsidiaries, and systems. operatesSystem appears only when that edge was returned.";
    const root = d3.hierarchy(hideCollapsed(full, this.collapsed));
    const laidOut = d3.tree<TreeItem>().nodeSize([26, 190])(root);
    const nodes = laidOut.descendants();
    const minY = Math.min(...nodes.map((node) => node.x));
    const maxY = Math.max(...nodes.map((node) => node.x));
    const width = Math.max(this.host.clientWidth, 280);
    const height = Math.max(maxY - minY + 48, 160);
    this.svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const plot = document.createElementNS("http://www.w3.org/2000/svg", "g");
    plot.setAttribute("transform", `translate(16, ${24 - minY})`);
    for (const link of laidOut.links()) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", `M${link.source.y},${link.source.x} C${(link.source.y + link.target.y) / 2},${link.source.x} ${(link.source.y + link.target.y) / 2},${link.target.x} ${link.target.y},${link.target.x}`);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "#b7ad9f");
      plot.append(path);
    }
    for (const node of nodes) {
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      group.setAttribute("transform", `translate(${node.y},${node.x})`);
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("r", "6");
      circle.setAttribute("fill", colorForKind(node.data.kind));
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("x", "10");
      text.setAttribute("y", "4");
      const role = roleLabel(node.data.role);
      text.textContent = role ? `${node.data.label} · ${role}` : node.data.label;
      group.append(circle, text);
      group.addEventListener("click", () => {
        this.toggle(full, node.data.iri);
      });
      plot.append(group);
    }
    this.svg.append(plot);
  }

  private toggle(full: TreeItem, iri: string): void {
    const found = findItem(full, iri);
    if (found && found.children.length > 0) {
      if (this.collapsed.has(iri)) this.collapsed.delete(iri);
      else this.collapsed.add(iri);
      this.render();
      return;
    }
    const node = this.store.getState().graph.nodes.find((item) => item.iri === iri);
    if (!node) return;
    void expandGraph(iri, 50)
      .then((expanded) => {
        this.store.mergeGraph(graphFromNeighbors(node, expanded.rows));
      })
      .catch((error: unknown) => {
        this.store.setStatus(error instanceof Error ? error.message : "The ownership neighborhood could not be loaded.");
      });
  }
}

function hideCollapsed(node: TreeItem, collapsed: ReadonlySet<string>): TreeItem {
  return {
    ...node,
    children: collapsed.has(node.iri) ? [] : node.children.map((child) => hideCollapsed(child, collapsed)),
  };
}

function findItem(node: TreeItem, iri: string): TreeItem | null {
  if (node.iri === iri) return node;
  for (const child of node.children) {
    const found = findItem(child, iri);
    if (found) return found;
  }
  return null;
}
