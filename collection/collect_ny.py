"""Download New York's state-published utility territory GIS exports and metadata."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
from collect import download
SOURCES = [
 ('states/ny/electric_territories.geojson','https://data.ny.gov/api/v3/views/awza-4vgu/query.geojson?accessType=DOWNLOAD'),
 ('states/ny/electric_metadata.json','https://data.ny.gov/api/views/awza-4vgu.json'),
 ('states/ny/gas_territories.geojson','https://data.ny.gov/api/v3/views/i7nm-ih89/query.geojson?accessType=DOWNLOAD'),
 ('states/ny/gas_metadata.json','https://data.ny.gov/api/views/i7nm-ih89.json'),
]
if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=4) as p: results=list(p.map(download,SOURCES))
    for r in results:
        if r['status']=='downloaded':
            try:
                obj=json.loads((Path(__file__).parent/r['path']).read_text(encoding='utf-8'))
                if r['path'].endswith('.geojson'):
                    if obj.get('type')!='FeatureCollection': raise ValueError('Not a FeatureCollection')
                    r['feature_count']=len(obj['features'])
            except Exception as e: r.update(status='invalid',error=str(e))
        print(r['status'],r['path'],r.get('feature_count',r.get('error','')),flush=True)
    (Path(__file__).parent/'data/manifest_ny.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
