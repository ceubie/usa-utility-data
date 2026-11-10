"""Fetch the EPA CWNS dictionary link exposed by the current download page."""
from urllib.request import urlopen,Request
from urllib.parse import urljoin
from html import unescape
from pathlib import Path
import re,json
from collect import download
page='https://sdwis.epa.gov/ords/sfdw_pub/r/sfdw/cwns_pub/data-download'
html=urlopen(Request(page,headers={'User-Agent':'Mozilla/5.0'}),timeout=60).read().decode('utf-8')
match=re.search(r'href="([^"]*download-state-zip\?p2_location_id=DD[^"]*)"',html)
if not match: raise RuntimeError('Dictionary link not found on EPA page')
url=urljoin(page,unescape(match.group(1)))
r=download(('wastewater/epa_cwns_2022_dictionary.xlsx',url))
r['source_page']=page
print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
(Path(__file__).parent/'data/manifest_cwns_dictionary.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
