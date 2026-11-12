"""Best serving areas for active drinking-water systems."""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

from utilitydata.core.config import BEST_ROLES
from utilitydata.core.text import require_columns
from utilitydata.gold.schema import TERRITORY_COLUMNS


def write_territories(wkb_path: Path, destination: Path) -> int:
    """Write the best serving areas as GeoParquet."""
    frame = pd.read_parquet(wkb_path)
    require_columns(frame, TERRITORY_COLUMNS, "best areas")
    geometries = shapely.from_wkb([bytes(value) for value in frame["geometry"].tolist()])
    attributes = frame.drop(columns=["geometry"]).copy()
    attributes["population_served"] = pd.to_numeric(attributes["population_served"], errors="coerce").astype("Int64")
    attributes["footprint_verified"] = attributes["footprint_verified"].astype("boolean")
    geo = gpd.GeoDataFrame(attributes, geometry=list(geometries), crs="EPSG:4326")
    if not bool(geo["status"].eq("active").all()):
        raise ValueError("A territory is not an active system")
    if not bool(geo["is_best"].all()):
        raise ValueError("A territory is not the best area")
    if not bool(geo["zone_role"].isin(BEST_ROLES).all()):
        raise ValueError("A territory is not a serving role")
    if bool(geo["service_area_id"].duplicated().any()):
        raise ValueError("Territory ids are not unique")
    destination.parent.mkdir(parents=True, exist_ok=True)
    geo.loc[:, list(TERRITORY_COLUMNS)].to_parquet(destination, index=False)
    return len(geo)
