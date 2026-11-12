import { describe, expect, it } from "vitest";
import { consumeAskEvents, readAskEvents } from "../src/api/askStream";
import type { AskEvent } from "../src/types/api";

const streamText = [
  "event: status",
  'data: {"message":"Starting"}',
  "",
  "event: tool_call",
  'data: {"call_id":"call_1","name":"run_sparql","arguments":{"query":"SELECT ?system WHERE { ?system a ud:WaterSystem }"}}',
  "",
  "event: tool_result",
  'data: {"call_id":"call_1","name":"run_sparql","result":{"row_count":84,"rows":[]}}',
  "",
  "event: answer_delta",
  'data: {"text":"Travis County has "}',
  "",
  "event: answer_delta",
  'data: {"text":"**84** water systems."}',
  "",
  "event: display",
  'data: {"kind":"graph","nodes":[{"iri":"http://utilities.local/system/SYS_1","label":"Example","kind":"WaterSystem","state":"TX"}],"links":[],"dropped":0}',
  "",
  "event: done",
  'data: {"answer":"Travis County has **84** water systems."}',
  "",
].join("\n");

describe("ask event stream", () => {
  it("parses a fixture stream that is split across chunks", async () => {
    const events = await collect(readAskEvents(streamFrom(streamText, 17)));
    expect(events.map((event) => event.event)).toEqual([
      "status",
      "tool_call",
      "tool_result",
      "answer_delta",
      "answer_delta",
      "display",
      "done",
    ]);
    const call = events[1];
    expect(call?.event).toBe("tool_call");
    if (call?.event === "tool_call") {
      expect(call.name).toBe("run_sparql");
      expect(call.arguments).toMatchObject({ query: expect.stringContaining("WaterSystem") });
    }
    const display = events[5];
    expect(display?.event).toBe("display");
    if (display?.event === "display") {
      expect(display.display.kind).toBe("graph");
    }
    const presentation = consumeAskEvents(events);
    expect(presentation.drewEntities).toBe(true);
    expect(presentation.graph?.nodes[0]?.iri).toBe("http://utilities.local/system/SYS_1");
    expect(presentation.markdown).toBe("Travis County has **84** water systems.");
    expect(presentation.queries[0]).toContain("WaterSystem");
  });
});

function streamFrom(text: string, splitAt: number): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text.slice(0, splitAt)));
      controller.enqueue(encoder.encode(text.slice(splitAt)));
      controller.close();
    },
  });
}

async function collect(source: AsyncGenerator<AskEvent>): Promise<AskEvent[]> {
  const events: AskEvent[] = [];
  for await (const event of source) events.push(event);
  return events;
}
