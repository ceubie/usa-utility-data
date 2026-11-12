import { describe, expect, it } from "vitest";
import { consumeAskEvents, previewAsk, readAskEvents } from "../src/api/askStream";
import { updateAskPanel } from "../src/ui/askPanel";
import { renderMarkdown } from "../src/ui/markdown";

const configurationError = [
  "event: display",
  'data: {"kind":"graph","nodes":[{"iri":"http://utilities.local/system/SYS_X","label":"Should not draw","kind":"WaterSystem","state":"DC"}],"links":[{"source":"http://utilities.local/system/SYS_X","predicate":"servesCounty","target":"http://utilities.local/county/11001"}],"dropped":0}',
  "",
  "event: error",
  'data: {"message":"Ask is not configured. Missing AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, AZURE_OPENAI_API_KEY.","missing":["AZURE_OPENAI_ENDPOINT","AZURE_OPENAI_DEPLOYMENT","AZURE_OPENAI_API_KEY"]}',
  "",
].join("\n");

describe("configuration error", () => {
  it("shows the error and does not draw entities", async () => {
    const events = [];
    for await (const event of readAskEvents(streamFrom(configurationError))) events.push(event);
    const live = previewAsk(events);
    expect(live.drewEntities).toBe(false);
    expect(live.graph).toBeNull();
    const presentation = consumeAskEvents(events);
    expect(presentation.error).toContain("AZURE_OPENAI_ENDPOINT");
    expect(presentation.error).toContain("AZURE_OPENAI_DEPLOYMENT");
    expect(presentation.error).toContain("AZURE_OPENAI_API_KEY");
    expect(presentation.missing).toEqual([
      "AZURE_OPENAI_ENDPOINT",
      "AZURE_OPENAI_DEPLOYMENT",
      "AZURE_OPENAI_API_KEY",
    ]);
    expect(presentation.drewEntities).toBe(false);
    expect(presentation.graph).toBeNull();
    expect(presentation.map).toBeNull();
    expect(presentation.chart).toBeNull();

    const host = document.createElement("div");
    const drawn: unknown[] = [];
    updateAskPanel(host, presentation);
    if (presentation.drewEntities) drawn.push(presentation.graph);
    expect(drawn).toEqual([]);
    expect(host.dataset.drewEntities).toBe("false");
    expect(host.querySelector("[role=alert]")?.textContent).toContain("not configured");
    expect(host.querySelector(".wb-answer")?.textContent).toBe("");
    expect(host.querySelector("[role=alert]")?.querySelector("img")).toBeNull();
  });

  it("keeps an unfinished display from drawing during preview", () => {
    const presentation = previewAsk([
      {
        event: "display",
        display: {
          kind: "map",
          serviceAreaIds: ["SA_1"],
          countyGeoids: ["11001"],
          dropped: 0,
        },
      },
    ]);
    expect(presentation.drewEntities).toBe(false);
    expect(presentation.map).toBeNull();
  });
});

describe("markdown", () => {
  it("passes marked output through DOMPurify before it can reach the page", () => {
    const html = renderMarkdown('Hello <img src=x onerror="alert(1)"> **there**');
    expect(html).toContain("<strong>there</strong>");
    expect(html.toLowerCase()).not.toContain("onerror");
    expect(html.toLowerCase()).not.toContain("<script");
    const host = document.createElement("div");
    host.innerHTML = html;
    expect(host.querySelector("img")?.getAttribute("onerror")).toBeNull();
  });

  it("writes a configuration message as text rather than HTML", () => {
    const host = document.createElement("div");
    updateAskPanel(host, {
      markdown: "",
      error: '<img src=x onerror="alert(1)">',
      missing: [],
      steps: [],
      queries: [],
      graph: null,
      map: null,
      chart: null,
      drewEntities: false,
    });
    expect(host.querySelector("img")).toBeNull();
    expect(host.querySelector("[role=alert]")?.textContent).toContain("<img");
  });
});

function streamFrom(text: string): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text.slice(0, 40)));
      controller.enqueue(encoder.encode(text.slice(40)));
      controller.close();
    },
  });
}
