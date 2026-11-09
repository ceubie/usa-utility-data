"""Snapshot 2026 FERC accepted-filings feeds and public original filing files.

FERC limits RSS feeds to 650 filings. These monthly feeds are retrieval-time
snapshots, not evidence that every accepted or later-amended filing is present.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse, quote
from collect import ROOT, download
import json, re, xml.etree.ElementTree as ET

MANIFEST = ROOT / 'data' / 'manifest_round24_ferc_feed.json'
NS = {'f':'https://ferc.gov'}
TYPES = {'XBRL_INSTANCE_FILE', 'ADDITIONAL_ATTACHMENTS', 'CPA_CERTIFICATE'}

def save(rows):
 tmp = MANIFEST.with_suffix('.json.tmp')
 tmp.write_text(json.dumps(sorted(rows,key=lambda x:x['path']),indent=2),encoding='utf8')
 tmp.replace(MANIFEST)

def fetch(spec):
 row = download((spec['path'],spec['url']))
 row.update({k:v for k,v in spec.items() if k not in {'path','url'}})
 if row['status']=='downloaded' and spec['type']=='XBRL_INSTANCE_FILE':
  try: ET.parse(ROOT / row['path'])
  except Exception as exc: row.update(status='failed',error='Invalid XBRL XML: '+str(exc))
 return row

if __name__=='__main__':
 rows=[]; specs=[]; seen=set()
 for month in range(11,0,-1):
  rel='ferc/official/accepted_filings_2026_%02d.xml'%month
  url='https://ecollection.ferc.gov/api/rssfeed?month=%d&year=2026'%month
  row=download((rel,url)); rows.append(row)
  if row['status']!='downloaded':
   save(rows);print('failed feed',month,row.get('error'),flush=True);continue
  try:
   root=ET.parse(ROOT/row['path']).getroot();items=root.findall('./channel/item')
   row['feed_items']=len(items);row['possibly_truncated']=len(items)>=650
   for item in items:
    filing=item.find('f:xbrlFiling',NS)
    if filing is None: continue
    fid=filing.findtext('f:FilingID',default='',namespaces=NS)
    if not re.fullmatch(r'\d+',fid): continue
    attrs={'filing_id':fid,'cid':filing.findtext('f:CID',default='',namespaces=NS),
           'form':filing.findtext('f:FormName',default='',namespaces=NS),
           'period':filing.findtext('f:Period',default='',namespaces=NS),
           'report_year':filing.findtext('f:Year',default='',namespaces=NS),
           'submitted':filing.findtext('f:SubmittedOn',default='',namespaces=NS)}
    for doc in filing.findall('f:xbrlFile',NS):
     typ=doc.get('type');u=doc.get('url','');name=doc.get('file','')
     if typ not in TYPES or doc.get('availability')!='Public' or not u:continue
     parsed=urlparse(u)
     if parsed.scheme!='https' or parsed.netloc.lower()!='ecollection.ferc.gov':continue
     match=re.fullmatch(r'/api/DownloadDocument/(\d+)/(\d+)',parsed.path,re.I)
     if not match:continue
     # Some FERC feeds contain raw ampersands within the filename query value.
     # Re-encode the filename as one value so it cannot become another parameter.
     u=parsed.scheme+'://'+parsed.netloc+parsed.path+'?filename='+quote(name,safe='')
     key=(fid,match.group(1),match.group(2))
     if key in seen:continue
     seen.add(key);safe=re.sub(r'[^A-Za-z0-9._-]','_',name)[:150] or 'attachment'
     path='ferc/official/filings_accepted_2026/'+fid+'/'+match.group(1)+'_'+safe
     specs.append(dict(path=path,url=u,type=typ,**attrs))
  except Exception as exc:row.update(status='failed',error='Invalid feed: '+str(exc))
  save(rows);print('feed',month,row.get('feed_items'), 'files queued',len(specs),flush=True)
 with ThreadPoolExecutor(max_workers=4) as pool:
  for i,future in enumerate(as_completed([pool.submit(fetch,spec) for spec in specs]),1):
   row=future.result();rows.append(row)
   if i%25==0 or row['status']!='downloaded':
    save(rows);print('documents',i,'of',len(specs),'last',row['status'],row.get('error',''),flush=True)
 save(rows)
 print('DONE',len(specs),'documents',flush=True)
