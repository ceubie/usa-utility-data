"""Collect agency catalog records and water-boundary guidance for round five."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
from collect import download

SOURCES = [
    ('documentation/epa_water_service_area_state_summaries_2024.pdf', 'https://www.epa.gov/system/files/documents/2024-04/cws-service-area-boundaries-state-dataset-summaries.pdf'),
    ('documentation/epa_water_service_area_standard_2024.pdf', 'https://www.epa.gov/system/files/documents/2024-04/cws-service-area-boundaries-data-standard.pdf'),
    ('documentation/california_electric_iou_pou_item.json', 'https://www.arcgis.com/sharing/rest/content/items/30410214d637434ba1003cbdcc32cf55?f=json'),
    ('documentation/california_electric_other_item.json', 'https://www.arcgis.com/sharing/rest/content/items/07224640a2fe42f89399be796e7b8810?f=json'),
    ('documentation/west_virginia_water_area_item.json', 'https://www.arcgis.com/sharing/rest/content/items/916c34274f334a5fb8c2d26668c0e042?f=json'),
    ('documentation/west_virginia_sewer_area_item.json', 'https://www.arcgis.com/sharing/rest/content/items/a1fa71a131a2477fa345acae1a38795f?f=json'),
    ('documentation/west_virginia_water_line_item.json', 'https://www.arcgis.com/sharing/rest/content/items/f9175f2eeeb24c259e7e9d7c973d55a0?f=json'),
    ('documentation/west_virginia_sewer_line_item.json', 'https://www.arcgis.com/sharing/rest/content/items/1f8eb86ff34142d9a5ce6f56958bc401?f=json'),
    ('documentation/arizona_water_service_areas_adhs_item.json', 'https://www.arcgis.com/sharing/rest/content/items/df37fc5ffd774fcfaffebb4c8b4b6208?f=json'),
]

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(download, SOURCES))
    for result in results:
        if result['status'] == 'downloaded' and result['path'].endswith('.pdf'):
            if not (Path(__file__).parent / result['path']).read_bytes().startswith(b'%PDF-'):
                result.update(status='invalid', error='Missing PDF signature')
        print(result['status'], result['path'], result.get('bytes', result.get('error')), flush=True)
    (Path(__file__).parent / 'data/manifest_round5_docs.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
