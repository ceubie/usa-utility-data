"""Download additional Idaho utility directories and energy landscape."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from collect import ROOT, download

SOURCES = [
 ('states/id/energy_mineral_landscape_2026_oemr.pdf','https://oemr.idaho.gov/wp-content/uploads/OEMR_2026_Energy_Mineral_Landscape_Revised.pdf'),
 ('states/id/utilities_by_city_ipuc_historical.pdf','https://puc.idaho.gov/Fileroom/PublicFiles/Consumer/cities.pdf'),
 ('states/id/infrastructure_resource_guide_2022_commerce.pdf','https://commerce.idaho.gov/content/uploads/2022/07/InfrastructureResource-Guide-Revised-2022.pdf'),
 ('states/id/utility_contacts_energy_office.html','https://osmec.idaho.gov/utilities/'),
]

if __name__ == '__main__':
    results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(download, item) for item in SOURCES]):
            r=f.result(); results.append(r)
            print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
    (ROOT/'data'/'manifest_round9_idaho.json').write_text(json.dumps(sorted(results,key=lambda r:r['path']),indent=2),encoding='utf-8')
