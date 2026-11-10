"""Save Kansas regulator maps and state GIS catalog/configuration documents."""
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, urlunparse
import json
from collect import download

BASE = Path(__file__).resolve().parent
MAP_PAGE = 'https://www.kcc.ks.gov/records-information/maps'
FILES = [
    ('states/ks/kcc_maps_page.html', MAP_PAGE),
    ('states/ks/kcc_electric_certified_areas.pdf', 'https://www.kcc.ks.gov/images/PDFs/maps/ks_electric_certified_areas.pdf'),
    ('states/ks/kcc_gas_certified_areas.pdf', 'https://www.kcc.ks.gov/images/PDFs/maps/ks_gas_certified_areas.pdf'),
    ('states/ks/kcc_telephone_exchange_2025.pdf', 'https://www.kcc.ks.gov/images/maps/2025_Telephone_Exchange.pdf'),
    ('states/ne/oppd_service_area.pdf', 'https://oppd.com/media/204900/service-area-map.pdf'),
    ('documentation/south_dakota_puc_experience.json', 'https://www.arcgis.com/sharing/rest/content/items/cb1c98bb187f436ba1e4337078f8c6fd/data?f=json'),
    ('documentation/south_dakota_puc_webmap.json', 'https://www.arcgis.com/sharing/rest/content/items/0155c631acb94912b78827a82af7a35e/data?f=json'),
    ('documentation/south_dakota_puc_webmap_item.json', 'https://www.arcgis.com/sharing/rest/content/items/0155c631acb94912b78827a82af7a35e?f=json'),
]

class CountyMaps(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag != 'option':
            return
        url = dict(attrs).get('value', '')
        parsed = urlparse(url)
        if parsed.hostname == 'www.kcc.ks.gov' and parsed.path.startswith('/images/PDFs/maps/county/') and parsed.path.lower().endswith('.pdf'):
            self.urls.append(urlunparse(parsed._replace(scheme='https')))

def validated_download(item):
    result = download(item)
    if result['status'] == 'downloaded' and result['path'].lower().endswith('.pdf'):
        with (BASE / result['path']).open('rb') as f:
            if not f.read(8).startswith(b'%PDF-'):
                result.update(status='invalid', error='Missing PDF signature')
    print(result['status'], result['path'], result.get('bytes', result.get('error')), flush=True)
    return result

if __name__ == '__main__':
    page = validated_download(FILES[0])
    if page['status'] != 'downloaded':
        raise SystemExit('Could not retrieve Kansas commission county-map index')
    parser = CountyMaps()
    parser.feed((BASE / page['path']).read_text(encoding='utf-8'))
    county = [('states/ks/counties/' + urlparse(url).path.rsplit('/', 1)[-1], url) for url in dict.fromkeys(parser.urls)]
    print('County map links discovered:', len(county), flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = [page] + list(pool.map(validated_download, FILES[1:] + county))
    (BASE / 'data/manifest_round6.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
