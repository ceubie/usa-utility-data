"""Download Wisconsin PSC utility GIS files directly from its maps page."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
from collect import download
SOURCES=[
 ('states/wi/psc_electric_territories.zip','https://psc.wi.gov/SiteAssets/Maps/EL_PSCW_ServTerr.zip'),
 ('states/wi/psc_natural_gas_territories.zip','https://psc.wi.gov/SiteAssets/Maps/NG_PSCW_ServTerr.zip'),
 ('states/wi/psc_water_utilities_2025.zip','https://psc.wi.gov/SiteAssets/Maps/WaUtilityLocationsCY2025_Public.zip'),
]
if __name__=='__main__':
 with ThreadPoolExecutor(max_workers=3) as pool: results=list(pool.map(download,SOURCES))
 for r in results: print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
 (Path(__file__).parent/'data/manifest_wi.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
