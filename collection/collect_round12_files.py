"""Preserve Wyoming PSC reference maps and California catalog metadata."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from collect import ROOT, download

SOURCES = [
 ('documentation/california_cpuc_utility_territory_item.json','https://www.arcgis.com/sharing/rest/content/items/4cff5f62470945ceb3549f08ea72f7da?f=json'),
 ('states/wy/psc_certificated_utility_maps.html','https://psc.wyo.gov/home/certificated-utility-maps'),
 ('states/wy/psc_electric_certificated_areas.pdf','https://drive.google.com/uc?export=download&id=1gL-MqErd8Fi4TXRwxRPAaa3TRbd1Qasn'),
 ('states/wy/psc_gas_certificated_areas.pdf','https://drive.google.com/uc?export=download&id=1ovW0FNXchi58aeSmAgke3cLcl4uKuUhz'),
 ('states/wy/psc_telephone_certificated_areas.pdf','https://drive.google.com/uc?export=download&id=1vs67J-asOWxa4idsRRPfQ0QYEgqK_V_7'),
 ('states/wy/psc_water_certificated_areas_2022.pdf','https://drive.google.com/uc?export=download&id=1uiMXLS3xaMVGiHMboi6VhYRgZKZvfRgd'),
 ('states/wy/psc_corporations_presentation_2023.pdf','https://wyoleg.gov/InterimCommittee/2023/07-2023053011-1PSCCorpsPresentationMay31final.pdf'),
]

def checked(source):
    row = download(source)
    if row['status'] == 'downloaded' and row['path'].endswith('.pdf'):
        path = ROOT/row['path']
        with path.open('rb') as f: header=f.read(5)
        if header != b'%PDF-':
            path.unlink(); row.update(status='failed',error='Response is not a PDF')
    return row

if __name__ == '__main__':
    rows=[]
    with ThreadPoolExecutor(max_workers=5) as pool:
        for future in as_completed([pool.submit(checked,x) for x in SOURCES]):
            row=future.result(); rows.append(row)
            print(row['status'],row['path'],row.get('bytes',row.get('error')),flush=True)
    (ROOT/'data'/'manifest_round12_files.json').write_text(json.dumps(sorted(rows,key=lambda x:x['path']),indent=2),encoding='utf-8')
