"""Save the publisher's own licence and credit text for every ArcGIS registry source.

For each ArcGIS source the script reads three public records and stores the
text verbatim:

- the layer record (``copyrightText``, ``description``) saved with the collection;
- the service record (``serviceItemId``, ``copyrightText``, ``documentInfo``);
- for ArcGIS Online items, the item record (``owner``, ``licenseInfo``,
  ``accessInformation``, ``title``).

The output is evidence for a human licence decision. It does not change any
registry entry. Run it from the repository root:

    uv run python scripts/collect_licence_evidence.py
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from html import unescape
from pathlib import Path

import requests
import yaml

REGISTRY = Path("registry/sources")
COLLECTION = Path("collection/data")
OUTPUT = Path("registry/licence_evidence.json")
TIMEOUT = 40
ITEM_URL = "https://www.arcgis.com/sharing/rest/content/items/{item}?f=json"
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def plain(text: object) -> str | None:
    """Return text with markup removed, or None when nothing is left."""
    if not isinstance(text, str):
        return None
    cleaned = _SPACE.sub(" ", unescape(_TAG.sub(" ", text))).strip()
    return cleaned or None


def get_json(session: requests.Session, url: str) -> dict | None:
    """Fetch one JSON document. A failure is tried once more, then recorded as missing."""
    for attempt in range(2):
        try:
            response = session.get(url, timeout=TIMEOUT)
            if response.status_code != 200:
                data = None
            else:
                data = response.json()
        except (requests.RequestException, ValueError):
            data = None
        if isinstance(data, dict) and "error" not in data:
            return data
        if attempt == 0:
            time.sleep(0.5)
    return None


def service_root(layer_url: str) -> str:
    return layer_url.rstrip("/").rsplit("/", 1)[0]


def main() -> None:
    sources = []
    for path in sorted(REGISTRY.glob("*.yaml")):
        sources.extend(yaml.safe_load(path.read_text(encoding="utf-8"))["sources"])
    session = requests.Session()
    session.headers["User-Agent"] = "utilitydata-licence-evidence/1.0"
    services: dict[str, dict | None] = {}
    items: dict[str, dict | None] = {}
    records = []
    for source in sources:
        if source.get("driver") != "arcgis" or not source.get("url"):
            continue
        url = str(source["url"])
        record: dict[str, object] = {"source_id": source["source_id"], "url": url}
        for raw_path in source.get("paths", []):
            metadata_path = COLLECTION / raw_path / "layer_metadata.json"
            if metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                record["layer_name"] = metadata.get("name")
                record["layer_copyright_text"] = plain(metadata.get("copyrightText"))
                record["layer_description"] = plain(metadata.get("description"))
        root = service_root(url)
        if root not in services:
            services[root] = get_json(session, f"{root}?f=json")
            time.sleep(0.15)
        service = services[root]
        if service is None:
            record["service_record"] = "not retrieved"
        else:
            record["service_copyright_text"] = plain(service.get("copyrightText"))
            record["service_description"] = plain(service.get("serviceDescription") or service.get("description"))
            document = service.get("documentInfo") or {}
            record["service_author"] = plain(document.get("Author"))
            record["service_credits"] = plain(document.get("Credits"))
            item_id = service.get("serviceItemId")
            if isinstance(item_id, str) and item_id:
                if item_id not in items:
                    items[item_id] = get_json(session, ITEM_URL.format(item=item_id))
                    time.sleep(0.15)
                item = items[item_id]
                record["item_id"] = item_id
                record["item_page"] = f"https://www.arcgis.com/home/item.html?id={item_id}"
                if item is None:
                    record["item_record"] = "not retrieved"
                else:
                    record["item_title"] = item.get("title")
                    record["item_owner"] = item.get("owner")
                    record["item_org_id"] = item.get("orgId")
                    record["item_licence_text"] = plain(item.get("licenseInfo"))
                    record["item_access_information"] = plain(item.get("accessInformation"))
                    record["item_snippet"] = plain(item.get("snippet"))
                    modified = item.get("modified")
                    if isinstance(modified, (int, float)):
                        record["item_modified"] = datetime.fromtimestamp(modified / 1000, tz=UTC).date().isoformat()
        record["retrieved_utc"] = datetime.now(tz=UTC).isoformat(timespec="seconds")
        quoted = (
            record.get("item_licence_text"),
            record.get("item_access_information"),
            record.get("service_copyright_text"),
            record.get("layer_copyright_text"),
            record.get("service_credits"),
        )
        if not any(isinstance(text, str) and text.strip() for text in quoted):
            record["terms"] = "no terms found"
        records.append(record)
        print(source["source_id"], "|", record.get("item_owner"), "|", (record.get("item_licence_text") or record.get("terms") or "")[:90], flush=True)
    payload = {
        "retrieved_utc": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "note": "Verbatim publisher text. This file is evidence for review and does not set any licence.",
        "sources": records,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} with {len(records)} sources")


if __name__ == "__main__":
    main()
