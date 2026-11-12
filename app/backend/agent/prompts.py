"""System prompt: rules, glossary, schema card, and example queries."""

from __future__ import annotations

from pathlib import Path

from app.backend.agent.schema_card import SchemaCard

_RULES = """
Rules
- Answer only from tool results.
- Resolve every name with search_entities or locate_place before writing a query.
- Never guess an IRI. Use an IRI only after a tool returned it.
- Take counts from query results, not from the rows shown in a preview. row_count is the size of the result. When row_count equals the limit, say the result may be truncated. A count inside a result row is the count to report.
- For any territory answer, state the authority and the source vintage. Say when the boundary is modeled. When the vintage or the boundary representation is absent, say it is not in the data.
- When a tool result contains systems, counties, service areas, organizations, or facilities that answer the question, call show_on_graph and show_on_map with that result_id so the workbench draws the same entities on the graph and the map.
- Say "not in the data" rather than guess.
- Geometry, block coverage, monthly series, individual violations, network segments, and facility units are not in the graph. They stay in the release tables used by the map and point tools.
- The examples below show query shape. Their IRIs were already resolved. Do not copy an example IRI for a different place.
""".strip()

_GLOSSARY = """
Glossary
- A utility system is the operating utility: a water system, an electric system, a wastewater system, or a natural gas system. An organization owns or operates systems, or appears in a parent relationship. A system is not an organization. ownsSystem links an organization to a system it owns. operatesSystem links an organization to a system it operates. In this release operator_org_id is null on every system, so operatesSystem has no rows.
- servesCounty means the system serves the county. It is written only when the county-coverage is_served flag is true, which means the population share of the county is at least 0.01 or the population inside the area is at least 100. CountyCoverage is any recorded overlap of a system and a county, including rows that are not served. Population share, evidence, and authority stay on the county-coverage node. They are not properties of servesCounty. locatedInCounty is a facility or place location, and it has no rows in this release.
- Authority levels, from the most direct to the least, are utility_direct, state_regulator, federal_submitted, federal_modeled, and admin_proxy. A null authority means the row did not record one.
- status active means the system is active. status inactive means it is inactive. status unknown means the activity was missing or was not an active or inactive code. An inactive system can still be in the graph. A best service area uses a serving role, active_retail_service or certified_franchise_territory.
- boundary_representation says how the boundary was made. When the value is modeled, say the boundary is modeled. Unknown, mixed, and modeled geometry are not an unmodeled boundary. The scorecard counts population in a non-modeled boundary only where the representation is unmodeled. source_vintage_date is the vintage. The map uses simplified display geometry; who_serves_point tests the exact best-area polygon.
- parentOf rows come from an experimental, incomplete SEC parent file through 2023-10-01. They are not a verified parent map. Say that when you use them.
""".strip()


def system_prompt(card: SchemaCard) -> str:
    """Assemble the system prompt from the rules, glossary, card, and examples."""
    return f"{_RULES}\n\n{_GLOSSARY}\n\n{card.as_prompt()}\n\n{example_block()}"


def example_files() -> list[Path]:
    """Return the example query files in name order."""
    return sorted((Path(__file__).resolve().parent / "examples").glob("*.rq"))


def example_question(text: str) -> str:
    """Return the question stored in the first comment line."""
    for line in text.splitlines():
        if line.startswith("#"):
            return line[1:].strip()
    return ""


def example_block() -> str:
    """Return the example questions and queries."""
    lines = ["Examples"]
    for path in example_files():
        text = path.read_text(encoding="utf-8").strip()
        lines.append(f"Question: {example_question(text)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip()
