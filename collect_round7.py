"""Download public Hawaii wastewater datasets and their agency metadata."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
from collect import download

SOURCES = [
    ('states/hi/wastewater_treatment_plants.zip', 'https://files.hawaii.gov/dbedt/op/gis/data/WWTP.shp.zip'),
    ('states/hi/offshore_sewer_lines.zip', 'https://files.hawaii.gov/dbedt/op/gis/data/sewerlines.shp.zip'),
    ('states/hi/onsite_sewage_systems.zip', 'https://files.hawaii.gov/dbedt/op/gis/data/osds.shp.zip'),
    ('states/hi/cesspool_prioritization.zip', 'https://files.hawaii.gov/dbedt/op/gis/data/hcpt_cesspool_data.shp.zip'),
    ('documentation/hi_wastewater_treatment_plants.pdf', 'https://files.hawaii.gov/dbedt/op/gis/data/WWTP.pdf'),
    ('documentation/hi_offshore_sewer_lines.pdf', 'https://files.hawaii.gov/dbedt/op/gis/data/sewer_lines.pdf'),
    ('documentation/hi_onsite_sewage_oahu.pdf', 'https://files.hawaii.gov/dbedt/op/gis/data/osds_oah.pdf'),
    ('documentation/hi_onsite_sewage_neighbor_islands.pdf', 'https://files.hawaii.gov/dbedt/op/gis/data/osds_ni.pdf'),
    ('documentation/hi_cesspool_prioritization.pdf', 'https://files.hawaii.gov/dbedt/op/gis/data/hcpt_cesspool_data.pdf'),
    ('documentation/dc_water_at_a_glance.html', 'https://www.dcwater.com/about-dc-water/who-we-are/dc-water-glance'),
]

def validated(item):
    r = download(item)
    if r['status'] == 'downloaded' and r['path'].endswith('.pdf'):
        with (Path(__file__).parent / r['path']).open('rb') as f:
            if not f.read(8).startswith(b'%PDF-'):
                r.update(status='invalid', error='Missing PDF signature')
    print(r['status'], r['path'], r.get('bytes', r.get('error')), flush=True)
    return r

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(validated, SOURCES))
    (Path(__file__).parent / 'data/manifest_round7.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
