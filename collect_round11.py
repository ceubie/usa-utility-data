"""Save regulator, agency and utility source documents for this batch."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from collect import ROOT, download

SOURCES = [
 ('documentation/maine_electric_service_webmap_item.json','https://www.arcgis.com/sharing/rest/content/items/7f0f44f9392c4803b33b19cec8b9b94a?f=json'),
 ('documentation/maine_electric_service_webmap_data.json','https://www.arcgis.com/sharing/rest/content/items/7f0f44f9392c4803b33b19cec8b9b94a/data?f=json'),
 ('documentation/texas_water_service_areas_catalog_item.json','https://www.arcgis.com/sharing/rest/content/items/7068e93e64eb43f89343bc3d3b33f7d7?f=json'),
 ('states/me/municipal_water_systems_maine_cdc.html','https://www1.maine.gov/dhhs/mecdc/healthy-living/health-and-safety/drinking-water-safety/public-water-systems/water-systems-municipal'),
 ('states/me/gas_distributors_puc.html','https://www3.maine.gov/mpuc/regulated-utilities/natural-gas/distributors'),
 ('states/me/gas_distribution_service_faq_puc.html','https://www3.maine.gov/mpuc/regulated-utilities/natural-gas/faq'),
 ('states/me/registered_retail_gas_suppliers_puc.html','https://www3.maine.gov/mpuc/regulated-utilities/natural-gas/distributors/gas-licensees'),
 ('states/me/electric_utilities_public_advocate.html','https://www1.maine.gov/meopa/electricity/utilities'),
 ('states/me/gas_service_areas_2024_puc.jpg','https://www.maine.gov/meopa/sites/maine.gov.meopa/files/inline-images/Natural%20Gas%20Service%20Area%20Map%20%282024-01-09%29.jpg'),
 ('states/me/natural_gas_puc_2025_presentation.pdf','https://legisweb0.legislature.maine.gov/doc/11456'),
 ('states/me/maine_energy_plan_2025.pdf','https://www.legislature.maine.gov/doc/11475'),
 ('states/va/electric_service_territories_2020_scc.pdf','https://www.scc.virginia.gov/media/sccvirginiagov-home/consumer-home/public-utilities/electricity/regulated-companies--service-map/el_map.pdf'),
 ('states/va/energy_security_plan_2024.pdf','https://energy.virginia.gov/public/documents/VASESP_2024_PublicVersion_Final.pdf'),
 ('states/la/electric_distribution_map_lpsc.jpg','https://lpsc.louisiana.gov/images/electric_cov_map_large2022_b.jpg'),
 ('states/la/electric_distribution_map_lpsc.html','https://lpsc.louisiana.gov/Utilities_Map'),
 ('states/nv/carson_city_water_service_area_map.pdf','https://www.carsoncity.gov/home/showpublisheddocument/87070/638301078390070000'),
 ('states/tx/water_service_boundaries_twdb.html','https://www.twdb.texas.gov/waterplanning/waterusesurvey/serviceboundaryeditor.asp'),
]

if __name__ == '__main__':
    results=[]
    with ThreadPoolExecutor(max_workers=5) as pool:
        for future in as_completed([pool.submit(download,item) for item in SOURCES]):
            result=future.result(); results.append(result)
            print(result['status'],result['path'],result.get('bytes',result.get('error')),flush=True)
    (ROOT/'data'/'manifest_round11.json').write_text(json.dumps(sorted(results,key=lambda r:r['path']),indent=2),encoding='utf-8')
