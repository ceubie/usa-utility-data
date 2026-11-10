"""Preserve Alabama Power's public statewide and company service maps."""
from pathlib import Path
import json, zipfile
from collect import download

SOURCES=[
 ('states/al/alabama_power_statewide_territories_2022.pdf','https://www.alabamapower.com/content/dam/alabama-power/pdfs-docs/company/service-territory-maps/ServiceTerritoryMaps.pdf'),
 ('states/al/alabama_power_service_territory.kmz','https://www.alabamapower.com/content/dam/alabama-power/pdfs-docs/company/service-territory-maps/alabamapowerserviceterritory.kmz'),
 ('documentation/alabama_power_territories_page.html','https://www.alabamapower.com/company/about-us/service-territory-maps.html'),
]
if __name__=='__main__':
 results=[]
 for source in SOURCES:
  r=download(source)
  if r['status']=='downloaded':
   p=Path(__file__).parent/r['path']
   try:
    if p.suffix=='.pdf' and not p.read_bytes().startswith(b'%PDF-'):raise ValueError('Missing PDF signature')
    if p.suffix=='.kmz':
     with zipfile.ZipFile(p) as z:
      bad=z.testzip()
      if bad:raise ValueError('Corrupt KMZ member '+bad)
      if not any(n.lower().endswith('.kml') for n in z.namelist()):raise ValueError('KMZ has no KML')
      r['archive_entries']=len(z.namelist())
   except Exception as exc:r.update(status='invalid',error=str(exc))
  print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True);results.append(r)
 (Path(__file__).parent/'data/manifest_round7_alabama.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
