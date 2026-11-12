import * as d3 from "d3";
import { expandGraph } from "../api/client";
import type { EdgeKind, GraphData, GraphNode } from "../types/graph";
import { capGraph, graphFromNeighbors } from "./graphData";
import { colorForEdge, colorForKind } from "./scales";
import type { Store } from "../state/store";
import { el } from "../ui/dom";

interface SimNode extends GraphNode, d3.SimulationNodeDatum {}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  kind: EdgeKind;
}

export class ForceGraph {
  private readonly note = el("p", "wb-quiet");
  private readonly svg: d3.Selection<SVGSVGElement, unknown, null, undefined>;
  private simulation: d3.Simulation<SimNode, SimLink> | null = null;
  private signature = "";
  private unsubscribe: () => void;
  private clickTimer = 0;

  constructor(
    private readonly host: HTMLElement,
    private readonly store: Store,
  ) {
    this.host.replaceChildren(el("h2", undefined, "Graph"), this.note);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("wb-svg");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Force-directed graph");
    this.host.append(svg);
    this.svg = d3.select(svg);
    this.unsubscribe = this.store.subscribe(() => {
      this.render();
    });
    this.render();
  }

  destroy(): void {
    this.unsubscribe();
    window.clearTimeout(this.clickTimer);
    this.simulation?.stop();
  }

  private render(): void {
    const graph = capGraph(this.store.getState().graph);
    const signature = graph.nodes.map((node) => `${node.iri}:${node.kind}:${node.label}`).join("|")
      + "#"
      + graph.edges.map((edge) => `${edge.source}:${edge.kind}:${edge.target}`).join("|");
    this.note.textContent = graph.nodes.length === 0
      ? "Search, expand a node, or ask who serves a point. The graph draws at most 150 nodes."
      : graph.dropped > 0
        ? `${graph.nodes.length} nodes. Dropped ${graph.dropped} past the 150-node limit.`
        : `${graph.nodes.length} nodes.`;
    if (signature !== this.signature) {
      this.signature = signature;
      this.restart(graph);
    } else {
      this.highlight();
    }
  }

  private restart(graph: GraphData): void {
    this.simulation?.stop();
    const width = Math.max(this.host.clientWidth, 320);
    const height = 360;
    this.svg.attr("viewBox", `0 0 ${width} ${height}`);
    const nodes: SimNode[] = graph.nodes.map((node) => ({ ...node }));
    const byIri = new Map(nodes.map((node) => [node.iri, node]));
    const links: SimLink[] = graph.edges.flatMap((edge) => {
      const source = byIri.get(edge.source);
      const target = byIri.get(edge.target);
      if (!source || !target) return [];
      return [{ source, target, kind: edge.kind }];
    });
    const simulation = d3.forceSimulation(nodes)
      .force("link", d3.forceLink<SimNode, SimLink>(links).id((node) => node.iri).distance(64))
      .force("charge", d3.forceManyBody().strength(-160))
      .force("collide", d3.forceCollide(16))
      .force("center", d3.forceCenter(width / 2, height / 2));
    this.simulation = simulation;
    this.svg.on(".zoom", null);
    this.svg.selectAll("*").remove();
    const root = this.svg.append("g");
    this.svg.call(d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.3, 4]).on("zoom", (event: d3.D3ZoomEvent<SVGSVGElement, unknown>) => {
      root.attr("transform", event.transform.toString());
    }));
    root.append("g").selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", (link) => colorForEdge(link.kind))
      .attr("stroke-width", 1.4);
    const drag = d3.drag<SVGGElement, SimNode>()
      .on("start", (event: d3.D3DragEvent<SVGGElement, SimNode, SimNode>, node) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        node.fx = node.x;
        node.fy = node.y;
      })
      .on("drag", (event: d3.D3DragEvent<SVGGElement, SimNode, SimNode>, node) => {
        node.fx = event.x;
        node.fy = event.y;
      })
      .on("end", (event: d3.D3DragEvent<SVGGElement, SimNode, SimNode>, node) => {
        if (!event.active) simulation.alphaTarget(0);
        node.fx = null;
        node.fy = null;
      });
    const groups = root.append("g").selectAll("g")
      .data(nodes)
      .join("g")
      .attr("class", "wb-node");
    (groups as unknown as d3.Selection<SVGGElement, SimNode, SVGGElement, unknown>).call(drag);
    groups.append("circle")
      .attr("r", 8)
      .attr("fill", (node) => colorForKind(node.kind));
    groups.append("text")
      .text((node) => node.label)
      .attr("x", 10)
      .attr("y", 4);
    groups.on("click", (_event, node) => {
      window.clearTimeout(this.clickTimer);
      this.clickTimer = window.setTimeout(() => {
        this.store.setSelection({
          iri: node.iri,
          label: node.label,
          kind: node.kind,
          attributes: [],
          provenance: { source: null, date: null, authority: null, matchMethod: null, confidence: null },
        });
      }, 220);
    });
    groups.on("dblclick", (event, node) => {
      event.preventDefault();
      window.clearTimeout(this.clickTimer);
      void this.expand(node);
    });
    simulation.on("tick", () => {
      root.selectAll<SVGLineElement, SimLink>("line")
        .attr("x1", (link) => point(link.source).x)
        .attr("y1", (link) => point(link.source).y)
        .attr("x2", (link) => point(link.target).x)
        .attr("y2", (link) => point(link.target).y);
      groups.attr("transform", (node) => `translate(${node.x ?? 0},${node.y ?? 0})`);
    });
    this.highlight();
  }

  private highlight(): void {
    const selected = this.store.getState().selection?.iri;
    this.svg.selectAll<SVGCircleElement, SimNode>("circle")
      .attr("stroke", (node) => (node.iri === selected ? "#1c1915" : "transparent"))
      .attr("stroke-width", 2);
  }

  private async expand(node: SimNode): Promise<void> {
    try {
      const expanded = await expandGraph(node.iri, 50);
      this.store.mergeGraph(graphFromNeighbors(node, expanded.rows));
    } catch (error) {
      this.store.setStatus(error instanceof Error ? error.message : "Expand failed.");
    }
  }
}

function point(value: string | number | SimNode): { x: number; y: number } {
  if (typeof value === "object") return { x: value.x ?? 0, y: value.y ?? 0 };
  return { x: 0, y: 0 };
}
