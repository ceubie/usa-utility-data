"""Download state catalog documentation and TVA/SC reference sources."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from collect import ROOT, download

SOURCES = [
 ('documentation/kentucky_dgi_electric_service_webmap_item.json','https://www.arcgis.com/sharing/rest/content/items/111b3574f58e46639b8a97c6af565f37?f=json'),
 ('documentation/kentucky_dgi_electric_service_webmap_data.json','https://www.arcgis.com/sharing/rest/content/items/111b3574f58e46639b8a97c6af565f37/data?f=json'),
 ('documentation/tennessee_tdec_water_boundaries_item.json','https://www.arcgis.com/sharing/rest/content/items/cc62b90b5775475c94f503cf225c5fd7?f=json'),
 ('multistate/tva_local_power_companies.html','https://www.tva.com/Energy/Public-Power-Partnerships/Local-Power-Companies'),
 ('multistate/tva_local_power_company_directory.html','https://www.tva.com/energy/public-power-partnerships/local-power-companies/lpc'),
 ('multistate/tva_local_power_company_territory.png','https://tva-azr-eastus-cdn-ep-tvawcm-prd.azureedge.net/cdn-tvawcma/images/default-source/transmission-towers/energy/public-power/tva-local-power-companies-07-25-2.png?sfvrsn=5ad71516_1'),
 ('states/sc/water_wastewater_geographic_assessment_2022_ria.pdf','https://ria.sc.gov/wp-content/uploads/2022/03/Water-Utility-Assessment-and-Viability-Strategy_web.pdf'),
]

if __name__ == '__main__':
    results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(download, item) for item in SOURCES]):
            result=future.result(); results.append(result)
            print(result['status'],result['path'],result.get('bytes',result.get('error')),flush=True)
    (ROOT/'data'/'manifest_round10.json').write_text(json.dumps(sorted(results,key=lambda r:r['path']),indent=2),encoding='utf-8')
