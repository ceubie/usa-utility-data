"""Preserve catalog metadata and agency documentation for the third acquisition batch."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
from collect import download

SOURCES = [
 ('documentation/oregon_utility_areas_item.json','https://www.arcgis.com/sharing/rest/content/items/2102826e218c4d36a24583613df76f0c?f=json'),
 ('documentation/colorado_utility_areas_item.json','https://www.arcgis.com/sharing/rest/content/items/d74d092aad7b4032a8d3efcaceac6d36?f=json'),
 ('documentation/utah_water_areas_item.json','https://www.arcgis.com/sharing/rest/content/items/dc62a286013f447e88fc45480077c944?f=json'),
 ('documentation/florida_sjrwmd_water_areas_item.json','https://www.arcgis.com/sharing/rest/content/items/f2f54ba2896e464a890ce827644f250d?f=json'),
 ('documentation/missouri_water_districts_metadata.xml','https://info.mo.gov/dnr/DNR_GIS/metadata/WATER.PUB_DISTRICTS.xml'),
 ('documentation/arkansas_water_systems_metadata.html','https://gis.arkansas.gov/Metadata/HTML/asdi.Utilities.PUBLIC_WATER_SYSTEMS_export.html'),
 ('documentation/arkansas_electric_areas_metadata.html','https://gis.arkansas.gov/Metadata/HTML/asdi.Utilities.ELECTRIC_UTILITY_TERRITORY_export.html'),
 ('electric/eia861m_2026_sales_ultimate_customers.xlsx','https://www.eia.gov/electricity/data/eia861m/xls/sales_ult_cust_2026.xlsx'),
 ('electric/eia861m_2026_net_metering.xlsx','https://www.eia.gov/electricity/data/eia861m/xls/net_metering2026.xlsx'),
 ('electric/eia861m_2026_non_net_metering.xlsx','https://www.eia.gov/electricity/data/eia861m/xls/non_netmetering2026.xlsx'),
 ('electric/eia861m_2026_small_scale_solar.xlsx','https://www.eia.gov/electricity/data/eia861m/xls/small_scale_solar_2026.xlsx'),
]
if __name__=='__main__':
 import sys
 subset=[x for x in SOURCES if x[0].startswith('electric/')] if '--electric' in sys.argv else [x for x in SOURCES if not x[0].startswith('electric/')]
 with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(download,subset))
 for r in results: print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
 manifest='manifest_round3_electric.json' if '--electric' in sys.argv else 'manifest_round3_docs.json'
 (Path(__file__).parent/'data'/manifest).write_text(json.dumps(results,indent=2),encoding='utf-8')
