"""Download the official ScienceBase April 2026 solar PV data release."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
from collect import download

SOURCES=[
 ('electric/usgs_uspvdb_v4_20260414.zip','https://www.sciencebase.gov/catalog/file/get/6671c479d34e84915adb7536?f=__disk__ed%2F7b%2F9c%2Fed7b9ce6abb1fc8430fbfe830f8ee58e870c6af3'),
 ('electric/usgs_uspvdb_v4_20260414.csv','https://www.sciencebase.gov/catalog/file/get/6671c479d34e84915adb7536?f=__disk__dc%2Fa5%2F48%2Fdca548712009dd78533a58851d0be28b7489cfc6'),
 ('documentation/usgs_uspvdb_v4_changelog.txt','https://www.sciencebase.gov/catalog/file/get/6671c479d34e84915adb7536?f=__disk__42%2Fd8%2F4e%2F42d84ed48eca1700d02b794b7699dcfa9d6dd778'),
 ('documentation/usgs_uspvdb_v4_dictionary.csv','https://www.sciencebase.gov/catalog/file/get/6671c479d34e84915adb7536?f=__disk__63%2F51%2Fdb%2F6351db72a16a31c05b67c1cf72a3577ccf98e4f1'),
 ('documentation/usgs_uspvdb_v4_metadata.xml','https://www.sciencebase.gov/catalog/file/get/6671c479d34e84915adb7536?f=__disk__d5%2F23%2Fcf%2Fd523cfd9aba10b7f1657c432290ddd624a850f42'),
 ('documentation/usgs_uspvdb_v4_sciencebase_item.json','https://www.sciencebase.gov/catalog/item/6671c479d34e84915adb7536?format=json'),
]
if __name__=='__main__':
 with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(download,SOURCES))
 for r in results:print(r['status'],r['path'],r.get('bytes',r.get('error')),flush=True)
 (Path(__file__).parent/'data/manifest_round8_solar.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
