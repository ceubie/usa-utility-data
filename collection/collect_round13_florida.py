"""Archive Florida PSC's public county-by-utility lookup without transforming responses."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
import datetime, hashlib, json, re

ROOT = Path(__file__).resolve().parent
DEST = ROOT/'data'/'states'/'fl'/'psc_county_lookup'
JS_URL = 'https://www.psc.state.fl.us/main.4073c5a7ad75fb48.js'
LOOKUP = 'https://pscweb.floridapsc.com/api/ConsumerAssistance/GetUtilitiesByCounty/'

def request(url):
    with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0 utility-data-collection'}),timeout=90) as response:
        return response.read(),response.url,response.headers.get('Last-Modified')

def lookup(county, industry):
    url=LOOKUP+quote(county+';'+str(industry),safe=';')
    filename=re.sub(r'[^a-z0-9]+','_',county.lower()).strip('_')+'_'+str(industry)+'.json'
    path=DEST/filename
    row={'county':county,'industry_code':industry,'url':url,'path':str(path.relative_to(ROOT)).replace('\\','/'),'retrieved_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        body,final,last_modified=request(url); value=json.loads(body)
        if 'result' not in value or (value['result'] is not None and not isinstance(value['result'],list)):
            raise ValueError('Unexpected lookup response shape')
        path.write_bytes(body)
        row.update(status='downloaded',final_url=final,last_modified=last_modified,bytes=len(body),sha256=hashlib.sha256(body).hexdigest(),records=len(value['result'] or []),result_was_null=value['result'] is None)
    except Exception as e:
        row.update(status='failed',error=str(e))
    return row

if __name__=='__main__':
    DEST.mkdir(parents=True,exist_ok=True)
    body,final,last_modified=request(JS_URL)
    js_path=DEST/'psc_site_javascript.js';js_path.write_bytes(body)
    names=sorted(set(re.findall(r'\["title","([^"\]]+)",1,"flcnty"\]',body.decode('utf-8'))))
    if len(names)!=67: raise ValueError('Expected 67 map county labels; found '+str(len(names)))
    names=[('St. Johns' if x=='St.Johns' else x) for x in names]
    (DEST/'county_names.json').write_text(json.dumps(names,indent=2),encoding='utf-8')
    rows=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(lookup,county,kind) for county in names for kind in (1,2,3)]
        for f in as_completed(futures):
            r=f.result();rows.append(r)
            if len(rows)%20==0 or r['status']=='failed':print('completed',len(rows),'of',len(futures),'latest',r['county'],r['industry_code'],r['status'],flush=True)
    manifest={'javascript_url':JS_URL,'javascript_final_url':final,'javascript_last_modified':last_modified,'javascript_sha256':hashlib.sha256(body).hexdigest(),'county_name_source':'titles in PSC interactive map JavaScript; St.Johns normalized to St. Johns, the API form that returns records','industry_codes':{'1':'electric','2':'natural gas','3':'water and wastewater'},'expected_counties':67,'expected_requests':201,'responses':sorted(rows,key=lambda x:(x['county'],x['industry_code']))}
    (DEST/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    if any(r['status']!='downloaded' for r in rows):raise SystemExit('Some Florida PSC county queries failed; see manifest')
