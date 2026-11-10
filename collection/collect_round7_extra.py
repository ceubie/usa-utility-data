"""Preserve utility-published service descriptions and maps."""
import json
from pathlib import Path
from collect import download

SOURCES = [
    ('multistate/midamerican_community_services.html', 'https://www.midamericanenergy.com/territory-communitylist'),
    ('multistate/midamerican_service_territory_communities.pdf', 'https://www.midamericanenergy.com/media/pdf/mec-detailedservicearea-towns.pdf'),
    ('states/hi/hawaiian_electric_wildfire_plan_2023.pdf', 'https://www.hawaiianelectric.com/documents/about_us/our_vision_and_commitment/resilience/20230101_wildfire_mitigation_plan.pdf'),
    ('states/hi/kauai_island_utility_rate_application_2022.pdf', 'https://kiuc.coop/sites/default/files/2025-03/kiuc-rate-case-application-docket-no-2022-0208-2of2.pdf'),
    ('documentation/maryland_hagerstown_electric_item.json', 'https://www.arcgis.com/sharing/rest/content/items/f96912536e774d6f9605678ea8462e6b?f=json'),
]

if __name__ == '__main__':
    results=[]
    for source in SOURCES:
        r=download(source)
        if r['status']=='downloaded' and r['path'].endswith('.pdf'):
            with (Path(__file__).parent / r['path']).open('rb') as f:
                if not f.read(8).startswith(b'%PDF-'):
                    r.update(status='invalid',error='Missing PDF signature')
        print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
        results.append(r)
    (Path(__file__).parent/'data/manifest_round7_extra.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
