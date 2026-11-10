from concurrent.futures import ThreadPoolExecutor,as_completed
from collect import ROOT,download
import json,zipfile
ids={'mn_metc_water_recovery_catalog':'b76ef586d87c4d2a97447fefec8da819','mn_metc_sewer_interceptors_catalog':'29edded7482647ac9c2926cf56aa0164','mn_metc_sewersheds_catalog':'4d457b28300b415d8cc9b04d039935ae','mn_metc_musa_catalog':'558450eac2974d2bb9ec3d5b178d09b0','mn_metc_long_term_sewer_areas_catalog':'cd8a362be7bb473b8a5b97327fe85fcc'}
sources=[('documentation/'+n+'.json','https://www.arcgis.com/sharing/rest/content/items/'+i+'?f=json') for n,i in ids.items()]+[
 ('states/mn/metc_wastewater_treatment_plants_public.zip','https://gisdata.metc.state.mn.us/gisdata/Utility/wastewater_treatment_plants.zip'),
 ('states/mn/metc_sewer_interceptors_public.zip','https://gisdata.metc.state.mn.us/gisdata/Utility/sewer_interceptors.zip'),
 ('states/mn/metc_sanitary_sewersheds_public.zip','https://gisdata.metc.state.mn.us/gisdata/Utility/sanitary_sewersheds.zip'),
 ('states/mn/metc_musa_planning.zip','https://gisdata.metc.state.mn.us/gisdata/Planning/musa.zip')]
def checked(x):
 r=download(x)
 if r['status']!='downloaded':return r
 p=ROOT/r['path']
 try:
  if p.suffix=='.json':
   j=json.loads(p.read_text(encoding='utf8'))
   if 'error' in j:raise ValueError(str(j['error']))
  if p.suffix=='.zip':
   with zipfile.ZipFile(p) as z:assert z.testzip() is None
 except Exception as e:p.unlink();r.update(status='failed',error='Format validation failed: '+str(e))
 return r
if __name__=='__main__':
 rows=[]
 with ThreadPoolExecutor(max_workers=4) as pool:
  for f in as_completed([pool.submit(checked,x) for x in sources]):
   r=f.result();rows.append(r);print(r['status'],r['path'],r.get('error',r.get('bytes')),flush=True)
 (ROOT/'data'/'manifest_round19_extra.json').write_text(json.dumps(sorted(rows,key=lambda r:r['path']),indent=2),encoding='utf8')
