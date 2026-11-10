from concurrent.futures import ThreadPoolExecutor,as_completed
from collect import ROOT,download
import json
SOURCES=[
 ('states/az/pima_electric_areas_metadata.html','https://gis.pima.gov/data/contents/metadet.cfm?name=distelec'),
 ('states/az/pima_water_areas_metadata.html','https://gis.pima.gov/data/contents/metadet.cfm?name=watercos'),
 ('states/az/pima_sewer_areas_metadata.html','https://gis.pima.gov/data/contents/metadet.cfm?name=sewr_bnd'),
 ('states/az/pima_tucson_water_restrictions_metadata.html','https://gis.pima.gov/data/contents/metadet.cfm?name=water_tw'),
 ('states/az/corporation_commission_electric_areas_2013.pdf','https://www.azcc.gov/divisions/utilities/electric/map-elect.pdf?d=982'),
 ('states/az/mesa_electric_service_area.pdf','https://gis.mesaaz.gov/energy/serviceareas/Electric_Service_Area.pdf'),
 ('states/az/mesa_gas_service_area.pdf','https://gis.mesaaz.gov/energy/serviceareas/Gas_Service_Area.pdf'),
 ('states/az/mesa_energy_service_areas.html','https://gis.mesaaz.gov/energy/serviceareas/'),
 ('states/in/iurc_2026_annual_report.pdf','https://secure.in.gov/iurc/files/2026-IURC-Annual-Report.pdf'),
 ('states/in/iurc_2023_utility_guide.pdf','https://www.in.gov/iurc/files/IURC-2023-Utility-Guide.pdf'),
 ('states/in/iurc_commission_reports.html','https://secure.in.gov/iurc/commission-reports/'),
 ('states/oh/puco_natural_gas_distribution_companies_2026.pdf','https://dam.assets.ohio.gov/image/upload/puco.ohio.gov/empliibrary/files/OPA/Mapping/Natural%20Gas/Natural_Gas_Distribution_Companies.pdf'),
 ('documentation/arizona_dema_electric_boundaries_item.json','https://www.arcgis.com/sharing/rest/content/items/fe255cca2735494a83d8e2b34a732013?f=json')]
def checked(x):
 r=download(x)
 if r['status']!='downloaded':return r
 p=ROOT/r['path']
 try:
  if p.suffix=='.pdf':
   with p.open('rb') as f: assert f.read(5)==b'%PDF-'
  elif p.suffix=='.json':
   j=json.loads(p.read_text(encoding='utf8'))
   if 'error' in j:raise ValueError(str(j['error']))
 except Exception as e:p.unlink();r.update(status='failed',error='Format validation failed: '+str(e))
 return r
if __name__=='__main__':
 rows=[]
 with ThreadPoolExecutor(max_workers=5) as pool:
  for f in as_completed([pool.submit(checked,x) for x in SOURCES]):
   r=f.result();rows.append(r);print(r['status'],r['path'],r.get('error',r.get('bytes')),flush=True)
 (ROOT/'data'/'manifest_round18_files.json').write_text(json.dumps(sorted(rows,key=lambda r:r['path']),indent=2),encoding='utf8')
