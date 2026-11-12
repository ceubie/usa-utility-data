import { rankChartRows, barWidths } from "./bars";
import type { Store } from "../state/store";
import { el } from "../ui/dom";

export class RankedBarChart {
  private readonly note = el("p", "wb-quiet");
  private readonly svg: SVGSVGElement;
  private unsubscribe: () => void;

  constructor(
    private readonly host: HTMLElement,
    private readonly store: Store,
  ) {
    this.host.replaceChildren(el("h2", undefined, "Chart"), this.note);
    this.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    this.svg.classList.add("wb-svg", "wb-bars");
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
    const chart = this.store.getState().chart;
    this.svg.replaceChildren();
    if (!chart) {
      this.note.textContent = "A chart appears when an answer includes a show_chart result.";
      return;
    }
    const ranked = rankChartRows(chart);
    if (!ranked.column || ranked.bars.length === 0) {
      this.note.textContent = "The chart result has no numeric column.";
      return;
    }
    this.note.textContent = ranked.hidden > 0
      ? `${ranked.column}. Showing ${ranked.bars.length} of ${ranked.bars.length + ranked.hidden}.`
      : ranked.column;
    const labelWidth = 150;
    const width = Math.max(this.host.clientWidth, 280);
    const barWidth = Math.max(width - labelWidth - 70, 40);
    const lengths = barWidths(ranked.bars, barWidth);
    const rowHeight = 22;
    const height = ranked.bars.length * rowHeight + 8;
    this.svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    ranked.bars.forEach((bar, index) => {
      const y = index * rowHeight + 4;
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", "0");
      label.setAttribute("y", String(y + 12));
      label.textContent = bar.label;
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", String(labelWidth));
      rect.setAttribute("y", String(y));
      rect.setAttribute("width", String(lengths[index] ?? 0));
      rect.setAttribute("height", "14");
      rect.setAttribute("fill", "#1d4e5f");
      const value = document.createElementNS("http://www.w3.org/2000/svg", "text");
      value.setAttribute("x", String(labelWidth + (lengths[index] ?? 0) + 6));
      value.setAttribute("y", String(y + 12));
      value.textContent = String(bar.value);
      this.svg.append(label, rect, value);
    });
  }
}
