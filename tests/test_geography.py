import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
import pytest

from utilitydata.geography import (
    BAF_EXCLUDED,
    CENSUS_AREAS,
    EXPECTED_POP20,
    HANDLED_LAYERS,
    POPULATION_EXCLUDED,
    apply_county_crosswalk,
    download_jobs,
    population_of_states,
    read_crosswalk,
    read_workbook,
    require_old_county_count,
)
from utilitydata.registry import load_registry


def _crosswalk_text() -> str:
    header = '"STATEFP\n(INCITS38)"|"OLD_COUNTYFP\n(INCITS31)"|OLD_COUNTY_NAMELSAD|"NEW_COUNTYFP\n(INCITS31)"|NEW_COUNTY_NAMELSAD|COUSUBFP|OLD_COUSUB_GEOID|NEW_COUSUB_GEOID\n'
    row = "09|001|Fairfield County|120|Greater Bridgeport Planning Region|08070|0900108070|0912008070\n"
    return header + row


def _columns() -> dict[str, str]:
    return {
        "state": "STATEFP",
        "old_countyfp": "OLD_COUNTYFP",
        "old_county_name": "OLD_COUNTY_NAMELSAD",
        "new_countyfp": "NEW_COUNTYFP",
        "new_county_name": "NEW_COUNTY_NAMELSAD",
        "cousubfp": "COUSUBFP",
        "old_cousub_geoid": "OLD_COUSUB_GEOID",
        "new_cousub_geoid": "NEW_COUSUB_GEOID",
    }


def test_crosswalk_header_and_old_county_count(tmp_path):
    path = tmp_path / "crosswalk.txt"
    path.write_text(_crosswalk_text() + "\nGLOSSARY\nSTATEFP = State FIPS Code\n", encoding="utf-8")
    frame = read_crosswalk(path, _columns())
    assert frame.loc[0, "old_countyfp"] == "001"
    assert frame.loc[0, "new_cousub_geoid"] == "0912008070"
    require_old_county_count(frame, 1)
    with pytest.raises(ValueError, match="old county codes"):
        require_old_county_count(frame, 8)


def test_old_counties_are_mapped_and_blocks_are_kept():
    blocks = pd.DataFrame({
        "block_geoid": ["060010101011000", "090010101011000"],
        "state": ["06", "09"],
        "countyfp": ["001", "001"],
        "cousubfp": [pd.NA, "08070"],
        "cousub_geoid": [pd.NA, "0900108070"],
    })
    crosswalk = pd.DataFrame({
        "state": ["09"],
        "old_countyfp": ["001"],
        "old_county_name": ["Fairfield County"],
        "new_countyfp": ["120"],
        "new_county_name": ["Greater Bridgeport Planning Region"],
        "cousubfp": ["08070"],
        "new_cousub_geoid": ["0912008070"],
    })
    mapped, alias = apply_county_crosswalk(blocks, crosswalk)
    assert mapped["county_geoid"].tolist() == ["06001", "09120"]
    assert mapped["cousub_geoid"].tolist()[1] == "0912008070"
    assert len(mapped) == 2
    assert alias["old_county_geoid"].tolist() == ["09001"]
    assert alias["county_geoid"].tolist() == ["09120"]
    unmatched = blocks.copy()
    unmatched["cousubfp"] = [pd.NA, "99999"]
    with pytest.raises(ValueError, match="no crosswalk county"):
        apply_county_crosswalk(unmatched, crosswalk)


def test_population_keeps_territories_out_of_the_state_total():
    blocks = pd.DataFrame({"state": ["11", "06", "72", "60"], "pop20": [10, 20, 5, 7]})
    assert population_of_states(blocks) == 30
    assert EXPECTED_POP20 == 331_449_281
    assert POPULATION_EXCLUDED == frozenset({"60", "66", "69", "72", "78"})
    assert len(CENSUS_AREAS) - len(BAF_EXCLUDED) == 52


def test_workbook_keeps_sparse_cells_and_every_sheet():
    shared = ["Keep", "Name", "Second"]
    sheet_one = """<?xml version="1.0" encoding="UTF-8"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="inlineStr"><is><t>Extra</t></is></c></row>
    <row r="2"><c r="A2" t="s"><v>2</v></c><c r="C2"><v>4</v></c></row>
    </sheetData></worksheet>"""
    sheet_two = """<?xml version="1.0" encoding="UTF-8"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
    <row r="2"><c r="A2"><v>9</v></c><c r="B2" t="s"><v>1</v></c></row>
    </sheetData></worksheet>"""
    payload = _workbook({"General": sheet_one, "Special": sheet_two}, shared)
    frame = read_workbook(payload, {"Keep", "Name"})
    assert frame["listing"].tolist() == ["General", "Special"]
    assert frame.loc[0, "Keep"] == "Second"
    assert frame.loc[0, "Name"] is None or pd.isna(frame.loc[0, "Name"])
    assert frame.loc[0, "Extra"] == "4"
    assert frame.loc[1, "Keep"] == "9"
    with pytest.raises(ValueError, match="missing columns"):
        read_workbook(payload, {"Missing"})


def test_census_registry_expands_the_published_files(tmp_path):
    registry = Path(__file__).resolve().parents[1] / "registry" / "sources"
    sources = [
        source
        for source in load_registry(registry, require_reviewed=False)
        if source.storage == "home" and source.layers and all(layer.sector == "reference" for layer in source.layers)
    ]
    layers = {layer.layer for source in sources for layer in source.layers}
    assert layers == HANDLED_LAYERS
    assert all(not source.reviewed for source in sources)
    jobs = download_jobs(tmp_path, registry)
    urls = [url for url, _path in jobs]
    assert len(urls) == len(set(urls))
    assert sum(url.endswith("_tabblock20.zip") for url in urls) == 56
    assert sum("BlockAssign_ST" in url for url in urls) == 52
    assert sum(url.endswith("_place.zip") for url in urls) == 56
    assert any(url.endswith("gov_units_2025.zip") for url in urls)
    assert any(url.endswith("ct_cou_to_cousub_crosswalk.txt") for url in urls)
    assert any(url.endswith("tl_2025_us_county.zip") for url in urls)
    assert not any(f"ST{code}_" in url for code in BAF_EXCLUDED for url in urls)


def _workbook(sheets: dict[str, str], shared: list[str]) -> bytes:
    payload = io.BytesIO()
    shared_xml = "<sst xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">" + "".join(f"<si><t>{escape(item)}</t></si>" for item in shared) + "</sst>"
    sheet_tags = []
    relationships = []
    with zipfile.ZipFile(payload, "w") as book:
        for number, (name, body) in enumerate(sheets.items(), start=1):
            book.writestr(f"xl/worksheets/sheet{number}.xml", body)
            sheet_tags.append(f'<sheet name="{escape(name)}" sheetId="{number}" r:id="rId{number}"/>')
            relationships.append(f'<Relationship Id="rId{number}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{number}.xml"/>')
        book.writestr("xl/sharedStrings.xml", shared_xml)
        book.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            + "".join(sheet_tags) + "</sheets></workbook>")
        book.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(relationships) + "</Relationships>")
    return payload.getvalue()
