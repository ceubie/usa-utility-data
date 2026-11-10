"""Download the Georgia PSC territory maps and Mississippi GIS catalog item."""
import json
from pathlib import Path
from collect import download

SOURCES = [
    ('states/ga/gpsc_electric_territorial_maps.zip', 'https://psc.ga.gov/site/downloads/TerritorialMaps.zip'),
    ('documentation/mississippi_psc_current_service_areas_item.json', 'https://www.arcgis.com/sharing/rest/content/items/5a08ea9c3f6140479260f1f15e115bd1?f=json'),
]

if __name__ == '__main__':
    results = [download(source) for source in SOURCES]
    for result in results:
        print(result['status'], result['path'], result.get('bytes', result.get('error')), flush=True)
    (Path(__file__).parent / 'data/manifest_round5_files.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
