"""Preserve New Mexico catalog metadata and current Nebraska utility reports."""
from pathlib import Path
import json
from collect import download

SOURCES = [
    ('documentation/new_mexico_water_boundaries_ose_item.json', 'https://www.arcgis.com/sharing/rest/content/items/9d06927341da47f49525203cfeb93fa0?f=json'),
    ('states/ne/power_review_board_biennial_report_2026.pdf', 'https://nebraskalegislature.gov/FloorDocs/109/PDF/Agencies/Power_Review_Board/347_20261014-102136.pdf'),
    ('states/ne/power_association_load_capability_2026.pdf', 'https://powerreview.nebraska.gov/sites/default/files/doc/2026%20Load%20%26%20Capability%20Report%20%28FINAL%29.pdf'),
]

if __name__ == '__main__':
    results = []
    for source in SOURCES:
        result = download(source)
        if result['status'] == 'downloaded' and result['path'].endswith('.pdf'):
            with (Path(__file__).parent / result['path']).open('rb') as f:
                if not f.read(8).startswith(b'%PDF-'):
                    result.update(status='invalid', error='Missing PDF signature')
        print(result['status'], result['path'], result.get('bytes', result.get('error')), flush=True)
        results.append(result)
    (Path(__file__).parent / 'data/manifest_round6_extra.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
