"""Preserve official Bureau of Reclamation ArcGIS item descriptions."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
from collect import download

ITEMS={
 'hydropower_facilities':'2cf9b3330ffe46b5ad3dacea782181d9',
 'pumping_plants':'ba9c8d5c551b43b7925c0c1973acbe84',
 'water_treatment':'1f61d257b56c48f899909a2acbb2cb44',
 'conveyance_lines':'e7eb9ec4e5df44d1a8301e48963c7dcc',
 'reservoirs_lakes_pools':'98c2f5bc50394193b899ab93619909b3',
 'dams':'6db8567ef051481e8e1ce853ea712d8a',
 'under_construction':'b9c77894b5c64d19bfca90151c59747c',
}
if __name__=='__main__':
 sources=[('documentation/usbr_'+name+'_item.json','https://www.arcgis.com/sharing/rest/content/items/'+id+'?f=json') for name,id in ITEMS.items()]
 with ThreadPoolExecutor(max_workers=4) as p:results=list(p.map(download,sources))
 for r in results:print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
 (Path(__file__).parent/'data/manifest_round8_usbr_docs.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
