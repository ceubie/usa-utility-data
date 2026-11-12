import { askQuestion, consumeAskEvents, previewAsk, type AskHooks, type AskPresentation } from "../api/askStream";
import type { Store } from "../state/store";
import { renderMarkdown } from "./markdown";
import { el } from "./dom";

export function mountAskPanel(host: HTMLElement, hooks: AskHooks, store?: Store): void {
  host.replaceChildren();
  const form = el("form", "wb-ask-form");
  const label = el("label", "wb-label", "Question");
  const input = el("textarea");
  input.id = "ask-question";
  input.rows = 4;
  input.required = true;
  label.htmlFor = input.id;
  const button = el("button", "wb-button", "Ask");
  button.type = "submit";
  const note = el(
    "p",
    "wb-quiet",
    "Configure AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, and AZURE_OPENAI_API_KEY in the backend environment to enable Ask.",
  );
  form.append(label, input, button, note);
  const results = el("div", "wb-ask-results");
  host.append(form, results);
  if (store) {
    const syncNote = () => {
      const configured = store.getState().llmConfigured;
      note.textContent = configured === true
        ? "Ask is connected to Azure OpenAI (read-only SPARQL + release tools)."
        : configured === false
          ? "Ask is not configured: set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, and AZURE_OPENAI_API_KEY."
          : "Checking backend LLM configuration…";
    };
    store.subscribe(syncNote);
    syncNote();
  }
  let controller: AbortController | null = null;
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    controller?.abort();
    controller = new AbortController();
    button.disabled = true;
    void run(question, controller.signal).finally(() => {
      button.disabled = false;
    });
  });

  async function run(question: string, signal: AbortSignal): Promise<void> {
    const events = [];
    try {
      for await (const item of askQuestion(question, { signal })) {
        events.push(item);
        updateAskPanel(results, previewAsk(events));
      }
    } catch (error) {
      if (signal.aborted) return;
      const message = error instanceof Error ? error.message : "Ask failed.";
      events.push({ event: "error" as const, message });
    }
    if (signal.aborted) return;
    const presentation = consumeAskEvents(events);
    updateAskPanel(results, presentation);
    if (presentation.drewEntities) hooks.onEntities(presentation);
  }
}

export function updateAskPanel(host: HTMLElement, presentation: AskPresentation): void {
  host.replaceChildren();
  host.dataset.drewEntities = presentation.drewEntities ? "true" : "false";
  if (presentation.error) {
    const alert = el("p", "wb-error");
    alert.setAttribute("role", "alert");
    alert.textContent = presentation.error;
    host.append(alert);
    host.append(el("p", "wb-quiet", "This answer did not add entities to the graph or the map."));
  }
  const answer = el("div", "wb-answer");
  if (presentation.markdown.trim()) answer.innerHTML = renderMarkdown(presentation.markdown);
  host.append(answer);
  if (presentation.steps.length > 0) {
    const list = el("ol", "wb-steps");
    for (const step of presentation.steps) {
      const item = el("li");
      item.textContent = `${step.name}: ${step.summary}`;
      list.append(item);
    }
    host.append(el("h3", "wb-subhead", "Tool steps"), list);
  }
  if (presentation.queries.length > 0) {
    const queries = el("pre", "wb-queries");
    queries.textContent = presentation.queries.join("\n\n");
    host.append(el("h3", "wb-subhead", "Query used"), queries);
  }
}
