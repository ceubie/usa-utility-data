"""Display tools accept only a known result id."""

from app.backend.agent.result_store import ResultStore
from app.backend.agent.tools import ToolContext, show_chart, show_on_graph, show_on_map
from app.backend.settings import get_settings


def test_display_tools_reject_an_unknown_result_id():
    context = ToolContext(
        release=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        results=ResultStore(),
        settings=get_settings(),
        card=None,  # type: ignore[arg-type]
    )
    for tool in (show_on_graph, show_on_map, show_chart):
        outcome = tool({"result_id": "missing"}, context)
        assert outcome.display is None
        assert outcome.result["error"] == "Unknown result_id."

    rejected = show_on_graph({"result_id": "missing", "iri": "http://utilities.local/county/48453"}, context)
    assert rejected.display is None
    assert "only a result_id" in rejected.result["error"]
