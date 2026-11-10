"""Preserve Nevada utility reference maps and source catalog metadata."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from collect import ROOT, download

SOURCES=[
 ('states/nv/puc_nv_energy_service_areas.pdf','https://puc.nv.gov/uploadedFiles/pucnvgov/Content/Utilities/NV_Energy_Service_Areas.pdf'),
 ('states/nv/puc_rural_utility_service_areas.pdf','https://puc.nv.gov/uploadedFiles/pucnvgov/Content/Utilities/Nevada_Rural_Utility_Service_Areas.pdf'),
 ('states/nv/puc_2023_biennial_report.pdf','https://www.leg.state.nv.us/Division/Research/Documents/RTTL_NRS703.180_2023.pdf'),
 ('states/nv/puc_electric_capacity_report.pdf','https://puc.nv.gov/uploadedFiles/pucnvgov/Content/Home/Features/ElectricCapacityReport.pdf'),
 ('states/nv/nv_energy_certified_electric_areas.pdf','https://www.nvenergy.com/publish/content/dam/nvenergy/brochures_arch/help/brochures/nevadas_utilities_map.pdf'),
 ('documentation/nevada_electric_service_areas_ndom_item.json','https://www.arcgis.com/sharing/rest/content/items/2c5aab18f94547609dc35c2a2d63a0be?f=json'),
 ('documentation/north_carolina_ncdot_power_providers_metadata.pdf','https://xfer.services.ncdot.gov/gisdot/Metadata/Atlas/NC%20Utility%20Power%20Providers.pdf'),
 ('documentation/north_carolina_ncdot_wastewater_service_areas_metadata.pdf','https://xfer.services.ncdot.gov/gisdot/Metadata/Atlas/NC%20Waste%20Water%20Service%20Areas%20WWSA.pdf'),
 ('documentation/georgia_fulton_water_sewer_service_metadata.json','https://gismaps.fultoncountyga.gov/arcgispub/rest/services/WaterResources/WaterResourcesSewer/MapServer?f=json'),
]

def checked(x):
 r=download(x)
 if r['status']=='downloaded':
  p=ROOT/r['path']
  if p.suffix=='.pdf':
   with p.open('rb') as f: valid=f.read(5)==b'%PDF-'
   if not valid:p.unlink();r.update(status='failed',error='Response is not a PDF')
  elif p.suffix=='.json':
   try:json.loads(p.read_text(encoding='utf8'))
   except Exception as e:p.unlink();r.update(status='failed',error='Response is not JSON: '+str(e))
 return r

if __name__=='__main__':
 rows=[]
 with ThreadPoolExecutor(max_workers=4) as pool:
  for future in as_completed([pool.submit(checked,x) for x in SOURCES]):
   r=future.result();rows.append(r);print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
 (ROOT/'data'/'manifest_round14_files.json').write_text(json.dumps(sorted(rows,key=lambda r:r['path']),indent=2),encoding='utf-8')
