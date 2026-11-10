"""Preserve federal metadata and the DOE U.S. Virgin Islands energy profile."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from collect import ROOT, download

SOURCES = [
 ('states/vi/doe_energy_sector_risk_profile_2024.pdf','https://www.energy.gov/sites/default/files/2024-10/TerritorySectorRiskProfile-USVI.pdf'),
 ('documentation/usvi_water_infrastructure_fema_item.json','https://www.arcgis.com/sharing/rest/content/items/b7f36b5307fb429cad09200ee81ecd76?f=json'),
 ('documentation/usvi_generation_infrastructure_fema_item.json','https://www.arcgis.com/sharing/rest/content/items/eeedce283d554f8cb856ceb4b1d67790?f=json'),
 ('documentation/usvi_wastewater_facilities_fema_item.json','https://www.arcgis.com/sharing/rest/content/items/f52df8dc50a64ec9bff56c423703684d?f=json'),
]

if __name__ == '__main__':
    rows=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(download,x) for x in SOURCES]):
            row=future.result(); rows.append(row)
            print(row['status'],row['path'],row.get('bytes',row.get('error')),flush=True)
    (ROOT/'data'/'manifest_round12_usvi.json').write_text(json.dumps(sorted(rows,key=lambda x:x['path']),indent=2),encoding='utf-8')
