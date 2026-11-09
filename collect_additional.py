"""Retrieve the second batch without altering the original manifest."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json
from collect import download

SOURCES = [
 ('wastewater/epa_sewersheds_v1_3.zip','https://media.githubusercontent.com/media/USEPA/Sewersheds/main/Current_Release.zip'),
 ('states/tx/puct_water_ccn_tsms.zip','https://ftp.puc.texas.gov/public/puct-info/industry/water/utilities/PUCT_CCN_WATER_TSMS.zip'),
 ('states/tx/puct_sewer_ccn_tsms.zip','https://ftp.puc.texas.gov/public/puct-info/industry/water/utilities/PUCT_CCN_SEWER_TSMS.zip'),
 ('water/usgs_wsa_2017.zip','https://www.sciencebase.gov/catalog/file/get/608035dcd34e8564d6835790?f=__disk__eb%2F77%2F19%2Feb7719921c39783bc3dcd1453d260ac36bbd08e7'),
 ('water/usgs_wsa_geographic_units_2017.zip','https://www.sciencebase.gov/catalog/file/get/608035dcd34e8564d6835790?f=__disk__c3%2Fee%2Ff2%2Fc3eef28d5943dd88b57523d7c82ac23ed453b538'),
 ('water/usgs_wsa_data_tables.zip','https://www.sciencebase.gov/catalog/file/get/608035dcd34e8564d6835790?f=__disk__2b%2Fed%2Fc1%2F2bedc12834473a8e758cb718a4ff50ba70a04c09'),
 ('water/usgs_wsa_metadata.xml','https://www.sciencebase.gov/catalog/file/get/608035dcd34e8564d6835790?f=__disk__68%2Ff1%2Ffa%2F68f1fac9507421b3848b8b18a6ca5123b681d3de'),
]
if __name__ == '__main__':
    results=[]
    with ThreadPoolExecutor(max_workers=5) as pool:
        for f in as_completed([pool.submit(download, x) for x in SOURCES]):
            r=f.result(); results.append(r); print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
    (Path(__file__).resolve().parent/'data'/'manifest_additional.json').write_text(json.dumps(sorted(results,key=lambda r:r['path']),indent=2),encoding='utf-8')
