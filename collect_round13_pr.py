"""Save Puerto Rico energy infrastructure source documentation."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from collect import ROOT, download

SOURCES=[
 ('documentation/puerto_rico_power_generation_fema_item.json','https://www.arcgis.com/sharing/rest/content/items/bc7d5129eafb4e948749a27aad63d967?f=json'),
 ('states/pr/doe_pr100_summary_2024.pdf','https://www.energy.gov/sites/default/files/2024-08/CFE%20PR%20Grid%20Resilience%20and%20Transitions%20to%20100%20Renewable%20Energy.pdf'),
 ('states/pr/doe_electric_transmission_order_2025.pdf','https://www.energy.gov/sites/default/files/2025-05/PREPA%20202%28c%29%20Emergency%20Measures%20Transmission.pdf'),
 ('states/pr/pnnl_electric_infrastructure_2020.pdf','https://www.pnnl.gov/main/publications/external/technical_reports/PNNL-29985.pdf'),
]
if __name__=='__main__':
    rows=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(download,x) for x in SOURCES]):
            r=future.result();rows.append(r);print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
    (ROOT/'data'/'manifest_round13_pr.json').write_text(json.dumps(sorted(rows,key=lambda r:r['path']),indent=2),encoding='utf-8')
