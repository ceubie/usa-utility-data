"""Download additional original state publications, maps and workbooks."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from collect import ROOT, download

SOURCES = [
 ('states/de/water_regulation_psc.html','https://depsc.delaware.gov/water-regulation/'),
 ('states/de/wastewater_regulation_psc.html','https://depsc.delaware.gov/wastewater-regulation/'),
 ('states/mi/propane_service_pipeline_mpsc.html','https://www.michigan.gov/mpsc/consumer/natural-gas/pipeline-maps/propane-service-via-pipeline'),
 ('states/mi/propane_pipeline_map_mpsc.gif','https://www.michigan.gov/mpsc/-/media/Project/Websites/mpsc/consumer/nat-gas/serviceareapropane.gif?extension=webp&hash=5FC8033A57D13E1712BBD51E014E64AC&rev=9649afad9db241e8a7a1e7a3979bac45'),
 ('states/mi/gas_and_propane_provider_contacts_mpsc.html','https://www.michigan.gov/mpsc/consumer/natural-gas/gas-utilities-in-michigan'),
 ('states/id/electric_investor_owned_utility_areas_ipuc.pdf','https://puc.idaho.gov/Fileroom/PublicFiles/maps/elec.pdf'),
 ('states/id/electric_coop_municipal_areas_ipuc.pdf','https://puc.idaho.gov/Fileroom/PublicFiles/maps/elecoop.pdf'),
 ('states/id/gas_pipelines_and_local_distributors_ipuc.pdf','https://puc.idaho.gov/Fileroom/PublicFiles/maps/gas.pdf'),
 ('states/id/energy_landscape_2019_oemr.pdf','https://oemr.idaho.gov/wp-content/uploads/FINAL-Energy-Landscape-2019.pdf'),
 ('states/mt/understanding_energy_2023_deq.pdf','https://deq.mt.gov/files/Energy/Documents/FINAL2023_Understanding%20Energy%202023_Web_300dpi-with%20images_Final.pdf'),
 ('states/mt/navigable_waters_pipeline_crossings_2015_deq.pdf','https://deq.mt.gov/files/Energy/EnergizeMT/HistoricalEnergy/PDF/MT_NavWtr_Pipeline_Crossings_w_map.pdf'),
 ('states/mt/electricity_tables_2024_deq.xlsx','https://deq.mt.gov/files/Energy/Documents/Energy_Statistics/ElectricityTables2024.xlsx'),
 ('states/mt/natural_gas_tables_2024_deq.xlsx','https://deq.mt.gov/files/Energy/Documents/Energy_Statistics/NaturalGasTables2024.xlsx'),
 ('states/mt/electric_service_areas_deq.jpg','https://deq.mt.gov/files/Energy/Photos/Chapter4_Electric_Service_Areas.jpg'),
 ('states/mt/natural_gas_utility_areas_deq.jpg','https://deq.mt.gov/files/Energy/Photos/Chapter6_Natural_Gas_Utility_Areas.jpg'),
 ('states/mt/natural_gas_system_deq.jpg','https://deq.mt.gov/files/Energy/Photos/Chapter6_Natural_Gas_System.jpg'),
 ('states/mt/electric_transmission_system_deq.jpg','https://deq.mt.gov/files/Energy/Photos/Chapter%205_Electric%20Transmission%20System.jpg'),
 ('states/mt/electric_transmission_pathways_deq.jpg','https://deq.mt.gov/files/Energy/Photos/Chapter%205_Electric_Transmission_Pathways.jpg'),
 ('states/mt/electric_generation_deq.jpg','https://deq.mt.gov/files/Energy/Photos/Chapter4_Electric_Generation_Map.jpg'),
 ('states/mt/hydro_power_deq.jpg','https://deq.mt.gov/files/Energy/Photos/Chapter4_Hydro_Power.jpg'),
 ('states/mt/solar_power_deq.jpg','https://deq.mt.gov/files/Energy/Photos/Chapter%204_Solar%20Power.jpg'),
 ('states/mt/wind_power_deq.jpg','https://deq.mt.gov/files/Energy/Photos/Chapter%204_Wind%20Power.jpg'),
]

if __name__ == '__main__':
    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        for future in as_completed([pool.submit(download, item) for item in SOURCES]):
            result = future.result()
            results.append(result)
            print(result['status'], result['path'], result.get('bytes', result.get('error')), flush=True)
    (ROOT/'data'/'manifest_round9.json').write_text(json.dumps(sorted(results, key=lambda r: r['path']), indent=2), encoding='utf-8')
