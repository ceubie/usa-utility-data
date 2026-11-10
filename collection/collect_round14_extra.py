from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from collect_round14_files import checked
from collect import ROOT
sources=[('states/nv/energy_status_2024.pdf','https://www.energy.nv.gov/uploadedFiles/energynvgov/content/Media/2024%20Status%20of%20Energy%20Report_Final.pdf'),('states/nv/energy_office_reports.html','https://www.energy.nv.gov/media/reports/')]
rows=[]
with ThreadPoolExecutor(max_workers=2) as p:
 for f in as_completed([p.submit(checked,x) for x in sources]):
  r=f.result();rows.append(r);print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
(ROOT/'data'/'manifest_round14_extra.json').write_text(json.dumps(sorted(rows,key=lambda r:r['path']),indent=2),encoding='utf8')
