"""Choose a refresh driver from the registry driver field."""

from collections.abc import Mapping
from typing import Never

from shapely.geometry.base import BaseGeometry

from utilitydata.bronze.drivers.arcgis import (
    fetch_arcgis,
    measure_arcgis,
    source_mapped_fields,
)
from utilitydata.bronze.drivers.custom import fetch_custom
from utilitydata.bronze.drivers.discover import fetch_discover
from utilitydata.bronze.drivers.http import fetch_http
from utilitydata.bronze.drivers.measure import measure_tabular
from utilitydata.bronze.drivers.protocol import FetchRequest, FetchResult
from utilitydata.bronze.gate import Measurement
from utilitydata.registry import Source


def fetch(request: FetchRequest) -> FetchResult:
    """Run the driver named on the source."""
    driver = request.source.driver
    match driver:
        case "arcgis":
            return fetch_arcgis(request)
        case "http":
            return fetch_http(request)
        case "discover":
            return fetch_discover(request)
        case "custom":
            return fetch_custom(request)
        case None:
            raise ValueError(f"{request.source.source_id} has no driver")
        case _ as other:
            return _unknown_driver(other)


def measure_files(
    source: Source,
    files: Mapping[str, bytes],
    *,
    expected_state: BaseGeometry | None,
) -> Measurement:
    """Measure the bytes a driver returned. A missing named column raises later in the gate."""
    driver = source.driver
    mapped = source_mapped_fields(source)
    match driver:
        case "arcgis":
            return measure_arcgis(files, mapped_fields=mapped, expected_state=expected_state)
        case "http" | "discover" | "custom":
            return measure_tabular(source, files, mapped_fields=mapped)
        case None:
            raise ValueError(f"{source.source_id} has no driver")
        case _ as other:
            return _unknown_measure(other)


def _unknown_driver(driver: Never) -> FetchResult:
    raise ValueError(f"Unknown driver: {driver}")


def _unknown_measure(driver: Never) -> Measurement:
    raise ValueError(f"Unknown driver: {driver}")
