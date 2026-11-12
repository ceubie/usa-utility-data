import { describe, expect, it } from "vitest";
import type { SparqlRow } from "../src/types/api";
import { NODE_CAP, POLYGON_CAP } from "../src/limits";
import { emptyGraph, type GraphNode } from "../src/types/graph";
import { selectionFromEntity } from "../src/state/entity";
import {
  capGraph,
  graphFromDisplay,
  graphFromNeighbors,
  graphFromWhoServes,
  mergeGraph,
  ownershipTree,
} from "../src/viz/graphData";

const county: GraphNode = {
  iri: "http://utilities.local/county/48453",
  label: "Travis",
  kind: "County",
  state: "TX",
  sector: null,
};

describe("graph state", () => {
  it("turns neighbor rows into edges and does not invent empty links", () => {
    const rows: SparqlRow[] = [
      row("in", "http://utilities.local/ontology/servesCounty", "http://utilities.local/system/SYS_1"),
      row("out", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://utilities.local/ontology/County"),
      row("out", "http://utilities.local/ontology/name", "Travis", "literal"),
      row("out", "http://utilities.local/relationship/REL_1", "http://utilities.local/relationship/REL_1"),
    ];
    const graph = graphFromNeighbors(county, rows);
    expect(graph.edges).toEqual([
      {
        source: "http://utilities.local/system/SYS_1",
        target: county.iri,
        kind: "servesCounty",
      },
    ]);
    expect(graph.edges.some((edge) => edge.kind === "operatesSystem" || edge.kind === "locatedInCounty")).toBe(false);
    expect(graph.nodes.map((node) => node.kind)).toContain("UtilitySystem");
  });

  it("keeps at most 150 nodes when an expand payload is larger", () => {
    const rows = Array.from({ length: NODE_CAP + 5 }, (_, index) =>
      row("out", "http://utilities.local/ontology/servesCounty", `http://utilities.local/system/SYS_${index}`),
    );
    const graph = graphFromNeighbors(county, rows);
    expect(graph.nodes).toHaveLength(NODE_CAP);
    expect(graph.dropped).toBe(6);
    expect(graph.edges.every((edge) => graph.nodes.some((node) => node.iri === edge.source))).toBe(true);
  });

  it("merges a display payload and drops nodes past the cap", () => {
    const nodes = Array.from({ length: NODE_CAP + 1 }, (_, index) => ({
      iri: `http://utilities.local/org/ORG_${index}`,
      label: `Org ${index}`,
      kind: "Organization",
      state: "",
    }));
    const graph = graphFromDisplay({
      nodes,
      links: [{ source: nodes[0]?.iri ?? "", predicate: "parentOf", target: nodes[1]?.iri ?? "" }],
      dropped: 0,
    });
    expect(graph.nodes).toHaveLength(NODE_CAP);
    expect(graph.dropped).toBe(1);
    expect(graph.edges[0]?.kind).toBe("parentOf");
  });

  it("builds service-area edges from who-serves without operatesSystem", () => {
    const graph = graphFromWhoServes([
      {
        iri: "http://utilities.local/system/SYS_PWS_DC0000002",
        service_area_iri: "http://utilities.local/area/SA_1",
        service_area_id: "SA_1",
        system_id: "SYS_PWS_DC0000002",
        name: "DC Water",
        sector: "water",
        status: "active",
        primary_state: "DC",
        authority: "federal_submitted",
        source_vintage_date: null,
        boundary_representation: "mixed",
        zone_role: null,
        licence: null,
        grain: null,
      },
    ]);
    expect(graph.nodes.map((node) => node.kind)).toEqual(["WaterSystem", "ServiceArea"]);
    expect(graph.edges.map((edge) => edge.kind)).toEqual(["hasServiceArea"]);
  });

  it("builds an ownership tree only from parent, owner, and operator edges", () => {
    const parent = org("PARENT");
    const child = org("CHILD");
    const system = {
      iri: "http://utilities.local/system/SYS_1",
      label: "System",
      kind: "WaterSystem" as const,
      state: "TX",
      sector: "water",
    };
    const graph = {
      nodes: [parent, child, system, county],
      edges: [
        { source: parent.iri, target: child.iri, kind: "parentOf" as const },
        { source: child.iri, target: system.iri, kind: "ownsSystem" as const },
        { source: system.iri, target: county.iri, kind: "servesCounty" as const },
      ],
      dropped: 0,
    };
    const tree = ownershipTree(child.iri, graph);
    expect(tree?.children.map((item) => item.role).sort()).toEqual(["owned-system", "parent"]);
    expect(JSON.stringify(tree)).not.toContain("operatesSystem");
    expect(JSON.stringify(tree)).not.toContain(county.iri);
    expect(mergeGraph(emptyGraph(), graph).nodes).toHaveLength(4);
  });

  it("caps a merged graph at 150 nodes", () => {
    const incoming = {
      nodes: Array.from({ length: NODE_CAP + 2 }, (_, index) => org(`N_${index}`)),
      edges: [],
      dropped: 0,
    };
    const merged = capGraph(mergeGraph(emptyGraph(), incoming));
    expect(merged.nodes).toHaveLength(NODE_CAP);
    expect(merged.dropped).toBe(2);
  });

  it("keeps who-serves authority when the entity description has none", () => {
    const reading = selectionFromEntity("http://utilities.local/system/SYS_PWS_DC0000002", [
      {
        predicate: { kind: "iri", value: "http://utilities.local/ontology/name" },
        value: { kind: "literal", value: "DC Water" },
      },
    ], {
      source: null,
      date: "2024-01-01",
      authority: "federal_submitted",
      matchMethod: "exact point-in-polygon",
      confidence: null,
    });
    expect(reading.selection.label).toBe("DC Water");
    expect(reading.selection.provenance.authority).toBe("federal_submitted");
    expect(reading.selection.provenance.date).toBe("2024-01-01");
    expect(reading.selection.provenance.matchMethod).toBe("exact point-in-polygon");
  });
});

function org(id: string): GraphNode {
  return {
    iri: `http://utilities.local/org/${id}`,
    label: id,
    kind: "Organization",
    state: null,
    sector: null,
  };
}

function row(direction: string, predicate: string, other: string, kind: "iri" | "literal" = "iri"): SparqlRow {
  return {
    direction: { kind: "literal", value: direction },
    predicate: { kind: "iri", value: predicate },
    other: { kind, value: other },
  };
}

describe("polygon cap constant", () => {
  it("matches the service-area response cap", () => {
    expect(POLYGON_CAP).toBe(300);
    expect(NODE_CAP).toBe(150);
  });
});
