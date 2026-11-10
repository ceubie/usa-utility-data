"""Download source-published snapshots; run from the project root with network access."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import datetime, hashlib, json, urllib.request, urllib.error, zipfile

ROOT = Path(__file__).resolve().parent
SOURCES = [
 ('electric/eia861_2025.zip','https://www.eia.gov/electricity/data/eia861/zip/f8612025.zip'),
 ('electric/eia860_2025.zip','https://www.eia.gov/electricity/data/eia860/xls/eia8602025.zip'),
 ('electric/eia860m_september_2026.xlsx','https://www.eia.gov/electricity/data/eia860m/xls/september_generator2026.xlsx'),
 ('electric/eia923_2025.zip','https://www.eia.gov/electricity/data/eia923/xls/f923_2025.zip'),
 ('electric/eia923_2026_monthly.zip','https://www.eia.gov/electricity/data/eia923/xls/f923_2026.zip'),
 ('gas/eia176_all_ng_data.zip','https://www.eia.gov/naturalgas/ngqs/all_ng_data.zip'),
 ('water/epa_sdwa_latest.zip','https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip'),
 ('water/epa_sdwa_system_search.zip','https://echo.epa.gov/files/echodownloads/SDWA_system_search_download.zip'),
 ('water/epa_pws_boundaries_latest.zip','https://media.githubusercontent.com/media/USEPA/ORD_SAB_Model/main/Version_History/PWS_Boundaries_Latest.zip'),
 ('wastewater/epa_npdes_national.zip','https://echo.epa.gov/files/echodownloads/npdes_downloads.zip'),
 ('wastewater/epa_npdes_outfalls.zip','https://echo.epa.gov/files/echodownloads/npdes_outfalls_layer.zip'),
 ('wastewater/epa_sewer_systems.zip','https://echo.epa.gov/files/echodownloads/current_sewer_overflow_and_collection_systems_tables.zip'),
 ('gas/phmsa_distribution_2010_present.zip','https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/data_statistics/pipeline/annual_gas_distribution_2010_present.zip'),
 ('gas/phmsa_transmission_gathering_2010_present.zip','https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/data_statistics/pipeline/annual_gas_transmission_gathering_2010_present.zip'),
 ('gas/phmsa_gathering_2022_present.zip','https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/data_statistics/pipeline/annual_reporting_regulated_gas_gathering_2022_present.zip'),
 ('gas/phmsa_lng_2010_present.zip','https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/data_statistics/pipeline/annual_liquefied_natural_gas_2010_present.zip'),
 ('gas/phmsa_storage_2017_present.zip','https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/data_statistics/pipeline/annual_underground_natural_gas_storage_2017_present.zip'),
 ('gas/phmsa_hazardous_liquid_2010_present.zip','https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/data_statistics/pipeline/annual_hazardous_liquid_2010_present.zip'),
 ('gas/phmsa_operator_ids.xlsx','https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/2026-11/Pipeline%20Operators%20-%20OpIDs%20.xlsx'),
]

def download(item):
    rel, url = item
    dest = ROOT/'data'/rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(dest.name+'.partial')
    result = {'path': 'data/'+rel, 'url': url, 'retrieved_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        request = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 utility-data-collection'})
        with urllib.request.urlopen(request, timeout=180) as response, temp.open('wb') as out:
            result['final_url'] = response.url
            result['last_modified'] = response.headers.get('Last-Modified')
            result['content_type'] = response.headers.get('Content-Type')
            expected = response.headers.get('Content-Length')
            h = hashlib.sha256()
            while True:
                chunk = response.read(1024*1024)
                if not chunk: break
                h.update(chunk); out.write(chunk)
        size = temp.stat().st_size
        if expected and size != int(expected): raise ValueError('length mismatch')
        if dest.suffix in ('.zip','.xlsx'):
            with zipfile.ZipFile(temp) as archive:
                result['archive_entries'] = len(archive.infolist())
                bad = archive.testzip()
                if bad: raise ValueError('corrupt ZIP member: '+bad)
        temp.replace(dest)
        result.update(status='downloaded', bytes=size, sha256=h.hexdigest())
    except Exception as exc:
        temp.unlink(missing_ok=True)
        result.update(status='failed', error=str(exc))
    return result

if __name__ == '__main__':
    results=[]
    with ThreadPoolExecutor(max_workers=5) as pool:
        for f in as_completed([pool.submit(download, x) for x in SOURCES]):
            result=f.result(); results.append(result)
            print(result['status'], result['path'], result.get('bytes',result.get('error')), flush=True)
    (ROOT/'data'/'manifest.json').write_text(json.dumps(sorted(results,key=lambda r:r['path']),indent=2),encoding='utf-8')
