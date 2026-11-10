"""Collect public Florida PSC, state and utility map and directory documents."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from collect import ROOT, download

SOURCES=[
 ('states/fl/psc_find_utility_service.html','https://www.psc.state.fl.us/find-utility-service'),
 ('states/fl/psc_electric_utility_map.pdf','https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/ElectricUtilities.pdf'),
 ('states/fl/psc_natural_gas_utility_map.pdf','https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/NaturalGasUtilities.pdf'),
 ('states/fl/psc_utility_solar_facilities_map.pdf','https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/Solar/SolarUtilityFacilities.pdf'),
 ('states/fl/psc_water_wastewater_jurisdictional_counties.pdf','https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/WaterAndWastewater/WaterandWastewaterJurisdictionalCounties.pdf'),
 ('states/fl/fdacs_natural_gas_utilities.html','https://www.fdacs.gov/Business-Services/Energy/Florida-Energy-Clearinghouse/Natural-Gas-Utilities'),
 ('states/fl/florida_public_utilities_service_areas.html','https://fpuc.com/about/service-areas/'),
 ('states/fl/florida_public_utilities_natural_gas_tariff_2025.pdf','https://fpuc.com/wp-content/uploads/Consolidated-Natural-Gas-Tariff_ADA_12.1.25.pdf'),
 ('documentation/florida_orange_county_electric_service_areas_item.json','https://www.arcgis.com/sharing/rest/content/items/109ed3a0d53c4635a49162aa5a8a106f?f=json'),
 ('documentation/dc_water_water_system_service.json','https://geo.dcwater.com/arcgis/rest/services/Viewer/DWS16inLargeMain/MapServer?f=json'),
]

def checked(source):
    r=download(source)
    if r['status']=='downloaded':
        path=ROOT/r['path']
        with path.open('rb') as f: head=f.read(5)
        if path.suffix=='.pdf' and head!=b'%PDF-':
            path.unlink();r.update(status='failed',error='Response is not a PDF')
        if path.suffix=='.json':
            try: json.loads(path.read_text(encoding='utf-8'))
            except Exception as e: path.unlink();r.update(status='failed',error='Response is not JSON: '+str(e))
    return r

if __name__=='__main__':
    rows=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(checked,x) for x in SOURCES]):
            r=future.result();rows.append(r);print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
    (ROOT/'data'/'manifest_round13_files.json').write_text(json.dumps(sorted(rows,key=lambda x:x['path']),indent=2),encoding='utf-8')
