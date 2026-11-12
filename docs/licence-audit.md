# Licence audit

Re-fetched on 2026-11-12 from each ArcGIS layer record saved with the collection, the live service record, and the ArcGIS Online item record when the service published an item id. The file-level retrieval time is 2026-11-12T19:05:58+00:00. Identical quotes are one group. A proposal is not applied to the registry until an independent reviewer accepts it.

ArcGIS sources re-fetched: 270. Item records still not retrieved: 62. Sources with no terms found: 79.

A warranty disclaimer, the word Public, or Public Access is unknown. Esri Master License Agreement and Platts text are internal. CC BY-SA and MIT stay internal because they are outside the vocabulary. A bare licence URL is not the grant. Bureau of Reclamation text that refuses downloading, republishing, derived products, and dissemination is internal. HIFLD gas had no terms and stays unknown. Kentucky electric has a credit line, not a licence, and stays unknown.

A recorded restriction is not relaxed when the re-fetch finds no terms. The first application of this audit moved six sources from a restriction to `unknown`. They were restored to the frozen snapshot labels: the four Metropolitan Council wastewater layers (`minnesota_metc_wastewater_treatment_facilities`, `minnesota_metc_current_sewersheds`, `minnesota_metc_long_term_wastewater_areas`, `minnesota_metc_sewer_interceptors`) and `virginia_fairfax_sewer_service_areas` are `internal_or_no_redistribution`, and `washington_king_county_sewer_service_providers` is `attribution_no_commercial_sale`. The Metropolitan Council catalog terms say not to transfer or share these wastewater data, and the supplemental Metropolitan Council copies already kept that label. `relaxed_restrictions` in `src/utilitydata/registry.py` enforces the rule, and `tests/test_registry.py` compares the registry with the frozen snapshot registry. The four `attribution_required` sources that moved to `unknown` are stricter, so they keep `unknown`.

## Groups

### Group 1

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: terms
- Why: No publisher terms were found on the re-fetched ArcGIS records.
- Example URL: https://www.arcgis.com/home/item.html?id=c3b82f947d0247fcb22313f432d58c57
- Sources (79): alabama_power_divisions_2023, alabama_power_operating_centers_2023, alabama_power_territory_2023, arizona_electric_utility_areas_dema, arizona_electric_utility_areas_dema_source, arkansas_electric_providers_gis, arkansas_water_system_areas_adh, california_broadband_territories_cpuc_2023, california_electric_iou_territories_cpuc_2020, california_gas_iou_territories_cpuc_2020, california_voice_territories_cpuc_2023, california_water_class_a_territories_cpuc_2023, colorado_metro_water_recovery_members, colorado_metro_water_recovery_sewer_devices, colorado_metro_water_recovery_sewer_lines, connecticut_community_water_service_areas_dph, connecticut_drinking_water_watersheds_dph, connecticut_exclusive_water_service_area_changes_dph, connecticut_exclusive_water_service_areas_dph, dc_water_drain_pipes, dc_water_facilities, dc_water_pressure_zones, delaware_community_solar_psc, florida_broward_drainage_districts, florida_broward_sewer_provider_areas, florida_broward_water_provider_areas, florida_collier_wastewater_service_area, florida_collier_water_service_area, florida_orange_county_electric_service_areas, hawaii_maui_west_water_service_areas, indiana_electric_territories_iurc, iowa_utility_providers_by_survey_township_eoc, kansas_rural_water_districts_dasc, maryland_frederick_city_sewer_service_plan, maryland_frederick_city_water_service_plan, maryland_frederick_county_sewer_service_plan, maryland_frederick_county_water_service_plan, maryland_hagerstown_electric_service_area, minnesota_metc_current_sewersheds, minnesota_metc_long_term_wastewater_areas, minnesota_metc_sewer_interceptors, minnesota_metc_wastewater_treatment_facilities, national_usace_inventory_of_dams, natural_gas_ldc_territories_hifld, nevada_electric_service_areas_ndom, north_carolina_sewer_current_2004, north_carolina_sewer_future_2004, north_carolina_stormwater_2004, north_carolina_water_current_2004, north_carolina_water_future_2004, ohio_electric_certified_territories_puco, ohio_electric_overlap_areas_puco, oregon_eugene_private_waste_lines, oregon_eugene_waste_basin_studies, oregon_eugene_waste_lines, oregon_eugene_waste_points, oregon_eugene_waste_system_plan, oregon_eugene_wastewater_basins, pennsylvania_water_service_areas_dep, south_carolina_greer_electric_service_areas, south_carolina_greer_gas_service_areas, south_carolina_greer_sewer_service_areas, south_carolina_greer_water_service_areas, south_carolina_summerville_cpw_sewer_service_area, south_carolina_summerville_cpw_water_service_area, south_dakota_electric_service_territories_puc, texas_water_service_areas_twdb, virginia_state_sewer_area_vdh_deq_2019, washington_utc_gas_certificated_areas, wisconsin_dane_carpc_sewer_service_amendments, wisconsin_sewrpc_regional_sewer_plans_2025, wisconsin_washington_county_planned_sewer_areas, wyoming_laramie_electric_certificated_areas, wyoming_laramie_gas_certificated_areas, wyoming_laramie_high_west_power_lines, wyoming_laramie_telephone_certificated_areas, wyoming_laramie_wapa_microwave_towers, wyoming_laramie_wapa_power_lines, wyoming_laramie_wapa_substations

`	ext
no terms found
`

### Group 2

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.portlandmaps.com/arcgis/rest/services/Public/Utilities_Sewer/MapServer/19
- Sources (15): oregon_portland_connections, oregon_portland_diversions, oregon_portland_inlet_leads, oregon_portland_inlets, oregon_portland_lateral_cleanouts, oregon_portland_laterals, oregon_portland_non_bes_ownership, oregon_portland_pond_connectors, oregon_portland_service_status_lines, oregon_portland_service_status_points, oregon_portland_sewer_nodes, oregon_portland_sewer_pipes, oregon_portland_storm_nodes, oregon_portland_storm_pipes, oregon_portland_vaults_ponds_encasements

`	ext
City of Portland, Oregon
`

### Group 3

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://mapsdep.nj.gov/arcgis/rest/services/Features/Utilities/MapServer/13
- Sources (11): new_jersey_combined_sewer_overflow_outfalls_dep, new_jersey_electric_territories_dep, new_jersey_gas_territories_dep, new_jersey_hydropower_facilities_dep, new_jersey_sewer_service_areas_dep, new_jersey_solar_pv_by_county_dep, new_jersey_solar_pv_grid_supply_dep, new_jersey_solar_pv_public_facilities_dep, new_jersey_utility_line_features_dep, new_jersey_water_purveyors_njdep_2017, new_jersey_wreck_pond_sanitary_sewer_lines_dep

`	ext
NJDEP
`

### Group 4

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=0a994c3da20e47168151211a143187db
- Sources (8): alaska_electric_areas_rca, alaska_electric_community_rca, alaska_natural_gas_areas_rca, alaska_natural_gas_community_rca, alaska_sewer_areas_rca, alaska_sewer_community_rca, alaska_water_areas_rca, alaska_water_community_rca

`	ext
AEA, SOA DCCED DCRA, AIDEA, SOA DEC
`

### Group 5

- Proposed licence: internal_or_no_redistribution
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: The publisher does not authorize downloading, republishing, derived products, or dissemination.
- Example URL: https://www.arcgis.com/home/item.html?id=b9c77894b5c64d19bfca90151c59747c
- Sources (7): usbr_assets_under_construction, usbr_conveyance_lines, usbr_dams, usbr_hydropower_facilities, usbr_pumping_plants, usbr_reservoirs_lakes_pools, usbr_water_treatment_facilities

`	ext
The Bureau of Reclamation assumes no responsibility or liability for any errors or omissions in the content of this data. The information contained in this data is provided on an “as is” basis with no guarantees of completeness, accuracy, usefulness or timeliness and without any warranties of any kind whatsoever, express or implied. Reclamation does not warrant that this data and any information or material that may be downloaded from the data, will be uninterrupted, error-free, omission-free and/or free of virus or other harmful items. Reclamation does not authorize downloading or republishing, deriving new data products, or the dissemination of Reclamation’s data into other systems or by others. Use of this site constitutes notice of and agreement with the terms of use in this statement. U.S. Government Works Furthermore, certain data includes website hypertext links, or pointers, to information created and maintained by other public and/or private organizations. Reclamation provides these links and pointers for your information and convenience. When you select a link to an outside website, you are leaving this site and are subject to the privacy and security policies of the owners/sponsors of the outside website. Reclamation does not control or guarantee the accuracy, relevance, timeliness, or completeness of information contained on a linked website. Reclamation does not endorse the organizations sponsoring linked websites and we do not endorse the views they express or the products/services they offer. Reclamation cannot authorize the use of copyrighted materials contained in linked websites. Users must request such authorization from the sponsor of the linked website. Reclamation is not responsible for transmissions users receive from linked websites. Reclamation does not guarantee that outside websites comply with Section 508 (accessibility requirements) of the Rehabilitation Act.
`

### Group 6

- Proposed licence: internal_or_no_redistribution
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: The text names the Esri Master License Agreement or a Platts restriction.
- Example URL: https://www.arcgis.com/home/item.html?id=bb2aee97117d403ea63bcfe6be4a12c8
- Sources (6): crude_oil_pipelines_eia, electric_transmission_lines_eia, hydrocarbon_gas_liquids_pipelines_eia, natural_gas_pipelines_eia, petroleum_products_pipelines_eia, power_plants_eia

`	ext
This work is licensed under the Esri Master License Agreement. View Summary | View Terms of Use
`

### Group 7

- Proposed licence: public_unrestricted
- Proposed redistribution: shareable
- Confidence: medium
- Quote source: item_licence_text
- Why: The text says there are no restrictions on use, reproduction, or distribution. This is not applied until a reviewer accepts the named grantor.
- Example URL: https://www.arcgis.com/home/item.html?id=81d3a7c02de5406bba42a2236a531c5b
- Sources (6): michigan_crude_oil_pipelines_mpsc, michigan_electric_mpsc, michigan_gas_transmission_pipelines_mpsc, michigan_natural_gas_mpsc, michigan_refined_petroleum_pipelines_mpsc, michigan_underground_gas_storage_mpsc

`	ext
Access Constraints: None. Use Constraints: This data set is a public record and, as more fully described below, there are no restrictions on the use, reproduction, or distribution of this dataset. Notwithstanding the foregoing, the public release of this dataset should not be construed, expressed or implied, as to whether any use constitutes a legally permissible purpose. It is the sole responsibility of the user to determine if the data is usable for their purposes. This dataset is provided “AS IS” and on an “AS AVAILABLE” basis. The State of Michigan (“State”) makes no warranties, express or implied, regarding the accuracy, adequacy, reliability, timeliness, or completeness of the dataset. THE STATE DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS DATASET AND ANY INFORMATION PROVIDED TO YOU, INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT OF PROPRIETARY RIGHTS. THE STATE WILL NOT BE LIABLE, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY OR BY STATUTE OR OTHERWISE, FOR ANY CLAIM FOR CONSEQUENTIAL, INCIDENTAL, INDIRECT, OR SPECIAL DAMAGES, INCLUDING WITHOUT LIMITATION LOST PROFITS AND LOST BUSINESS OPPORTUNITIES, RELATED TO THE ACCESS OR USE OF THIS DATASET. IN NO EVENT WILL THE STATE BE LIABLE FOR ANY AMOUNTS THAT MAY RESULT FROM THE ACCESS OR USE OF THIS DATASET, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY, OR BY STATUTE OR OTHERWISE. You forever release the State, its departments, subdivisions, officers, and employees from all claims, rights, actions, demands, damages, liabilities, expenses and fees, which arise out of or relate to your access or use of this dataset. You must defend, indemnify and hold the State, its departments, subdivisions, officers, and employees harmless, without limitation, from and against all actions, claims, losses, liabilities, damages, costs, attorney fees, and expenses (including those required to establish the right to indemnification) arising out of or relating to your access or use of this dataset. The State reserves the right to modify or remove this dataset for any reason, without notice, at any time. Nothing in these terms constitutes or is intended to be a limitation upon, or waiver of, any privileges and immunities that apply to the State. These terms are governed by and interpreted under the law of the State of Michigan without regard to conflicts of laws provisions. Dataset Credit: State of Michigan
`

### Group 8

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: Public or Public Use alone is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=5fc570de6ae64b29b181c1235fc331fb
- Sources (6): hawaii_maui_sewer_discharge_points, hawaii_maui_sewer_gravity_mains, hawaii_maui_sewer_lateral_lines, hawaii_maui_sewer_manholes, hawaii_maui_sewer_pressurized_mains, hawaii_maui_sewer_pump_stations

`	ext
Public
`

### Group 9

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=28ba7ea684704b3799eeb0682b6245e7
- Sources (5): georgia_fulton_wastewater_pipes, georgia_fulton_wastewater_pump_stations, georgia_fulton_wastewater_treatment_plants, georgia_fulton_water_sewer_service_areas, georgia_fulton_water_tanks

`	ext
Fulton County Department of Water Services
`

### Group 10

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_licence_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=5a08ea9c3f6140479260f1f15e115bd1
- Sources (5): mississippi_electric_certificated_areas_psc, mississippi_gas_certificated_areas_psc, mississippi_sewer_certificated_areas_psc, mississippi_telephone_certificated_areas_psc, mississippi_water_certificated_areas_psc

`	ext
Utility information compiled by the Public Utilities Staff. The map was generated by the Certificated Area Mapping Information Systm (CAMIS). Base data were supplied by the Mississippi Automated Resource Information System (MARIS). The utility information and base data contained on this map are considered dependable, but the accuracy, completeness, and currency thereof are not guaranteed. The Mississippi Public Utilities Staff and MARIS make no warranties, expressed or implied as to the accuracy, completeness, currency, reliability, or suitability, for any particular purpose of any data or information contained in or generated from this map. The State of Mississippi, the Mississippi Public Utilities Staff, and MARIS or any employee thereof assumes no liability associated with the use of this map.
`

### Group 11

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=a2f51f23d17c4894a618abba3f87acb8
- Sources (5): tennessee_gallatin_cumberland_electric_area, tennessee_gallatin_gas_service_area, tennessee_gallatin_nes_electric_area, tennessee_gallatin_sewer_service_area, tennessee_gallatin_water_service_areas

`	ext
Jesse Mardis
`

### Group 12

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_licence_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=817e83e079b74895b337fb03004dad25
- Sources (5): vermont_gmp_distribution_lines_vcgi, vermont_gmp_poles_vcgi, vermont_gmp_underground_structures_vcgi, vermont_vec_distribution_lines_vcgi, vermont_vec_poles_vcgi

`	ext
VCGI and the State of VT make no representations of any kind, including but not limited to the warranties of merchantability or fitness for a particular use, nor are any such warranties to be implied with respect to the data.
`

### Group 13

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_licence_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=a2c11f98f3e84b33ac60f5e6ffc75f26
- Sources (4): oregon_clean_water_services_district_border, oregon_clean_water_services_pump_station_boundaries, oregon_clean_water_services_sewer_maintenance, oregon_clean_water_services_treatment_plant_basins

`	ext
Clean Water Services Disclaimer regarding GIS data: This product and its associated data are for informational purposes only and were derived from several databases. They were not prepared for, and are not suitable for legal, engineering or surveying purposes. Users of this information should review or consult the primary data and information sources to ensure accuracy. Clean Water Services cannot accept any responsibility for errors, omissions or positional accuracy. There are no warranties for this product. Mainline and service lateral locations are depicted using best available information but must be field verified and located before digging. Service laterals are marked in the field as “Unlocatable underground facilities” as defined in OAR 952-001-0010 (20). Easement data are not currently completed District-wide and should be used for general reference only. All sanitary or storm sewer data, with the exception of sanitary lines 24” and larger located within the city limits of Beaverton, Cornelius, Forest Grove, Hillsboro, Lake Oswego, Portland, Sherwood, Tigard or Tualatin, need to be verified by contacting the individual city. Notification of any errors would be appreciated. Clean Water Services, Development Services, 2550 SW Hillsboro Highway, Hillsboro OR 97123, (503) 681-5100.
`

### Group 14

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://gis.cityofconway.com/arcgis/rest/services/WATER_AND_SEWER_MAPS/WATER_AND_SEWER_UTILITY_MAP_FOR_PUBLIC/MapServer/4
- Sources (4): south_carolina_conway_gravity_sewers, south_carolina_conway_sewer_force_mains, south_carolina_conway_utility_service_area, south_carolina_conway_water_lines

`	ext
CITY OF CONWAY GIS
`

### Group 15

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://maps.vcgi.vermont.gov/arcgis/rest/services/PSD_services/PSD_Published_Layers/MapServer/18
- Sources (4): vermont_electric_service_areas_psd, vermont_electric_substations_psd, vermont_wec_distribution_lines_psd, vermont_wec_poles_psd

`	ext
PSD
`

### Group 16

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: A warranty disclaimer is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=1f8eb86ff34142d9a5ce6f56958bc401
- Sources (4): west_virginia_sewer_lines_ijdc, west_virginia_sewer_served_ijdc, west_virginia_water_lines_ijdc, west_virginia_water_served_ijdc

`	ext
This dataset is intended for general informational purposes only as an estimate of existing service. The quality of the line locations varies from system to system and from line to line and the line locations, material and diameter information may have changed since it was provided to the IJDC without the IJDC's knowledge. Users are cautioned to consider carefully the limitations of the data and information provided before using them for decisions that concern personal or public safety or to conduct business that involves substantial monetary or operational consequences. Conclusions drawn from, or actions undertaken on the basis of, such data and information are the sole responsibility of the user. Neither the West Virginia Infrastructure & Jobs Development Council, the West Virginia Water Development Authority, the State of West Virginia, nor any other agency thereof, nor any of their employees, contractors, or subcontractors, make any warranty, express or implied, nor assume any legal liability or responsibility for the accuracy, completeness, or usefulness of any information, apparatus, product, or process disclosed, nor represent that its use would not infringe on privately owned rights. By agreeing to use this data, you, the user, acknowledge that any reliance upon any information shall be at the sole risk of the user. The West Virginia Infrastructure & Jobs Development Council reserves the right, in its sole discretion, to make improvements to, or correct any error or omissions in, any portion of the data. In no event shall the State of West Virginia be liable for any direct, indirect, incidental, or consequential damage of any kind whatsoever with respect to the information gathered from this dataset.
`

### Group 17

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_access_information
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=ea9017f289f44b07a08a0a217d971617
- Sources (4): wisconsin_caledonia_not_serviced_sewer_district, wisconsin_caledonia_not_serviced_water_district, wisconsin_caledonia_sewer_service_area, wisconsin_caledonia_water_service_area

`	ext
Marc A Coss - Caledonia GIS Specialist
`

### Group 18

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_licence_text
- Why: The record is a link without the grant on that page. The link was not used as the licence.
- Example URL: https://www.arcgis.com/home/item.html?id=30410214d637434ba1003cbdcc32cf55
- Sources (3): california_electric_iou_pou_load_serving_cec, california_electric_other_load_serving_cec, california_natural_gas_cec

`	ext
https://www.energy.ca.gov/conditions-of-use
`

### Group 19

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/DEP_SEWER_SERVICE_AREAS/FeatureServer/3
- Sources (3): massachusetts_sewer_nonpotw_massdep, massachusetts_sewer_potw_massdep, massachusetts_sewer_unlocated_massdep

`	ext
MassDEP Water Utility Resilience Program, 2025, Publicly-Owned Treatment Work and Non-Publicly-Owned Sewer Service Areas (PubV2025_10).
`

### Group 20

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/DEP_PWS_WATER_SERVICE_AREAS/FeatureServer/2
- Sources (3): massachusetts_water_community_massdep, massachusetts_water_nontransient_massdep, massachusetts_water_unlocated_massdep

`	ext
MassDEP, Water Utility Resilience Program. 2024. Community and Non-Transient Non-Community Public Water System Service Area (PubV2024_7).
`

### Group 21

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=b4464800aadf4893b1eff8dde3e81a09
- Sources (3): minnesota_metc_musa_2030, minnesota_metc_musa_2040, minnesota_metc_musa_undesignated_reserve

`	ext
clip
`

### Group 22

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_access_information
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=64282a89e0bb45b480f8d0e122b00fba
- Sources (3): new_york_tioga_gas_service_areas, new_york_tioga_sewer_service_areas, new_york_tioga_water_service_areas

`	ext
Tioga County GIS, Tioga County Real Property & Taxation Services, NYS OPRHP, NYS DEC, FEMA, USGS, Susquehanna River Basin Commission,
`

### Group 23

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=412ab2f779f144f7affe86fd41d72efb
- Sources (3): wisconsin_electric_municipal_psc, wisconsin_electric_psc, wisconsin_natural_gas_psc_2016

`	ext
Tyler Tomaszewski Public Service Commission 608-266-2730 tyler.tomaszewski@wisconsin.gov
`

### Group 24

- Proposed licence: public_unrestricted
- Proposed redistribution: shareable
- Confidence: medium
- Quote source: item_licence_text
- Why: The text says there are no restrictions on use, reproduction, or distribution. This is not applied until a reviewer accepts the named grantor.
- Example URL: https://www.arcgis.com/home/item.html?id=44ccd54a4c3f4bdd8b1da98f667b06f5
- Sources (2): michigan_biomass_power_plants_mpsc, michigan_coal_power_plants_mpsc

`	ext
Access Constraints: None. Use Constraints: This data set is a public record and, as more fully described below, there are no restrictions on the use, reproduction, or distribution of this dataset. Notwithstanding the foregoing, the public release of this dataset should not be construed, expressed or implied, as to whether any use constitutes a legally permissible purpose. It is the sole responsibility of the user to determine if the data is usable for their purposes. This dataset is provided “AS IS” and on an “AS AVAILABLE” basis. The State of Michigan (“State”) makes no warranties, express or implied, regarding the accuracy, adequacy, reliability, timeliness, or completeness of the dataset. THE STATE DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS DATASET AND ANY INFORMATION PROVIDED TO YOU, INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT OF PROPRIETARY RIGHTS. THE STATE WILL NOT BE LIABLE, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY OR BY STATUTE OR OTHERWISE, FOR ANY CLAIM FOR CONSEQUENTIAL, INCIDENTAL, INDIRECT, OR SPECIAL DAMAGES, INCLUDING WITHOUT LIMITATION LOST PROFITS AND LOST BUSINESS OPPORTUNITIES, RELATED TO THE ACCESS OR USE OF THIS DATASET. IN NO EVENT WILL THE STATE BE LIABLE FOR ANY AMOUNTS THAT MAY RESULT FROM THE ACCESS OR USE OF THIS DATASET, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY, OR BY STATUTE OR OTHERWISE. You forever release the State, its departments, subdivisions, officers, and employees from all claims, rights, actions, demands, damages, liabilities, expenses and fees, which arise out of or relate to your access or use of this dataset. You must defend, indemnify and hold the State, its departments, subdivisions, officers, and employees harmless, without limitation, from and against all actions, claims, losses, liabilities, damages, costs, attorney fees, and expenses (including those required to establish the right to indemnification) arising out of or relating to your access or use of this dataset. The State reserves the right to modify or remove this dataset for any reason, without notice, at any time. Nothing in these terms constitutes or is intended to be a limitation upon, or waiver of, any privileges and immunities that apply to the State. These terms are governed by and interpreted under the law of the State of Michigan without regard to conflicts of laws provisions. Dataset Credit: U.S. Energy Information Administration, State of Michigan
`

### Group 25

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://gisdata.pima.gov/arcgis1/rest/services/GISOpenData/WaterReclamation/MapServer/0
- Sources (2): arizona_pima_wastewater_service_areas, arizona_pima_water_provider_areas_except_tucson

`	ext
Pima County Information Technology Department - Geographic Information Systems, 33 N Stone Av, 15th Floor, Tucson, AZ 85701
`

### Group 26

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://geo.dcwater.com/arcgis/rest/services/Viewer/DWS16inLargeMain/MapServer/4
- Sources (2): dc_water_large_mains, dc_water_pressure_mains

`	ext
DC Water, Department of Engineering and Technical Services, GIS Asset Mapping Group, gisedits@dcwater.com
`

### Group 27

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://enterprise.firstmap.delaware.gov/arcgis/rest/services/Boundaries/DE_CPCN/FeatureServer/0
- Sources (2): delaware_wastewater_certificated_areas_psc, delaware_water_certificated_areas_psc

`	ext
Delaware Public Service Commission
`

### Group 28

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=46d14d2caa3343a0b497bf3af55b23f8
- Sources (2): florida_sfwmd_water_current, florida_sfwmd_water_future

`	ext
SFWMD, Geospatial Services: Geospatial Services is a unit within the South Florida Water Management District’s Information Technology Bureau (ITB). Geospatial Services manages and maintains enterprise geospatial services, products, and data and is governed by the ITB's Policies and Procedures.
`

### Group 29

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=28ba7ea684704b3799eeb0682b6245e7
- Sources (2): georgia_fulton_water_hydrants, georgia_fulton_water_pipes

`	ext
Fulton County Department of Water Resources
`

### Group 30

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://kygisserver.ky.gov/arcgis/rest/services/WGS84WM_Services/Ky_Electric_Service_Areas_WGS84WM/MapServer/1
- Sources (2): kentucky_electric_service_areas_dgi, kentucky_electric_service_boundary_lines_dgi

`	ext
Kentucky Public Service Commission (PSC), DGI
`

### Group 31

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/ElectricityProviders/MapServer/0
- Sources (2): massachusetts_electric_providers_massgis, massachusetts_gas_providers_massgis

`	ext
Massachusetts Department of Public Utilities
`

### Group 32

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_licence_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=558450eac2974d2bb9ec3d5b178d09b0
- Sources (2): minnesota_metc_musa_2050, minnesota_metc_musa_composite

`	ext
None. This dataset is public domain under the Minnesota Government Data Practices Act (Minnesota Statutes Chapter 13).
`

### Group 33

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: MIT is outside the licence vocabulary, so the source stays internal.
- Example URL: https://www.arcgis.com/home/item.html?id=95b861a3bb0d4fa6b5eb84494b135c51
- Sources (2): national_epa_noncommunity_water_service_areas_v1_1, national_epa_noncommunity_water_service_centers_v1_1

`	ext
The MIT License (MIT) Copyright (c) 2026 Permission is hereby granted, free of charge, to any person obtaining a copy of this data and associated documentation files, to deal in the data without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the data, and to permit persons to whom the data is furnished to do so, subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies or substantial portions of the data. THE DATA IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE DATA.
`

### Group 34

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: A warranty disclaimer is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=c95891254aa349389135752a137670c5
- Sources (2): national_ferc_hydropower_exempted_projects, national_ferc_hydropower_licensed_projects

`	ext
These data are provided by the Federal Energy Regulatory Commission (FERC) “as is” and might contain errors or omissions. The User assumes the entire risk associated with its use of these data and bears all responsibility in determining whether these data are fit for the User’s intended use. The information contained in these data is dynamic and may change over time. The data are not better than the sources from which they were derived, and both scale and accuracy may vary across the data set. These data might not have the accuracy, resolution, completeness, timeliness, or other characteristics appropriate for applications that potential users of the data may contemplate. The User is encouraged to carefully consider the content of the metadata file associated with these data. These data are neither legal documents nor land surveys, and must not be used as such. Please report any errors in the data to the data Owner or FERC Program Office from which it was obtained. Any Users wishing to modify the data should describe the types of modifications they have performed. The User should not misrepresent the data, nor imply that changes made were approved or endorsed by FERC. This data may be updated by FERC without notification.
`

### Group 35

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=33ca9d838d5344869a2df0b85ca28a5b
- Sources (2): new_hampshire_water_lines_des, new_hampshire_water_service_areas_des

`	ext
NHDES, DGWB, Gomez and Sullivan Engineers
`

### Group 36

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://mapsdep.nj.gov/arcgis/rest/services/Features/Utilities/MapServer/20
- Sources (2): new_jersey_power_plant_parcels_dep, new_jersey_power_plants_dep

`	ext
NJDEP. USEIA
`

### Group 37

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_access_information
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=b7f36b5307fb429cad09200ee81ecd76
- Sources (2): usvi_power_generation_fema_2025, usvi_water_infrastructure_fema_wapa_2022

`	ext
US Virgin Islands - Water and Power Authority (WAPA) and Federal Emergency Management Agency (FEMA)
`

### Group 38

- Proposed licence: internal_or_no_redistribution
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: The text names the Esri Master License Agreement or a Platts restriction.
- Example URL: https://www.arcgis.com/home/item.html?id=d74d092aad7b4032a8d3efcaceac6d36
- Sources (1): colorado_electric_areas_cdot

`	ext
Use is limited to the individiuals identified in a Master Service Agreement with Platts. Usage and Sourcing guidelines are detailed in the "GeospatialProductUsageSourcing" document, delivered with a subscription to Platts geospatial products and data. Please email powermap_support@platts.com for a copy.
`

### Group 39

- Proposed licence: public_unrestricted
- Proposed redistribution: shareable
- Confidence: medium
- Quote source: item_licence_text
- Why: The text says there are no restrictions on use, reproduction, or distribution. This is not applied until a reviewer accepts the named grantor.
- Example URL: https://www.arcgis.com/home/item.html?id=f1f6d170d5804ab19e3a4ac687316a51
- Sources (1): michigan_detroit_refinery_mpsc

`	ext
Access Constraints: None. Use Constraints: This data set is a public record and, as more fully described below, there are no restrictions on the use, reproduction, or distribution of this dataset. Notwithstanding the foregoing, the public release of this dataset should not be construed, expressed or implied, as to whether any use constitutes a legally permissible purpose. It is the sole responsibility of the user to determine if the data is usable for their purposes. This dataset is provided “AS IS” and on an “AS AVAILABLE” basis. The State of Michigan (“State”) makes no warranties, express or implied, regarding the accuracy, adequacy, reliability, timeliness, or completeness of the dataset. THE STATE DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS DATASET AND ANY INFORMATION PROVIDED TO YOU, INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT OF PROPRIETARY RIGHTS. THE STATE WILL NOT BE LIABLE, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY OR BY STATUTE OR OTHERWISE, FOR ANY CLAIM FOR CONSEQUENTIAL, INCIDENTAL, INDIRECT, OR SPECIAL DAMAGES, INCLUDING WITHOUT LIMITATION LOST PROFITS AND LOST BUSINESS OPPORTUNITIES, RELATED TO THE ACCESS OR USE OF THIS DATASET. IN NO EVENT WILL THE STATE BE LIABLE FOR ANY AMOUNTS THAT MAY RESULT FROM THE ACCESS OR USE OF THIS DATASET, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY, OR BY STATUTE OR OTHERWISE. You forever release the State, its departments, subdivisions, officers, and employees from all claims, rights, actions, demands, damages, liabilities, expenses and fees, which arise out of or relate to your access or use of this dataset. You must defend, indemnify and hold the State, its departments, subdivisions, officers, and employees harmless, without limitation, from and against all actions, claims, losses, liabilities, damages, costs, attorney fees, and expenses (including those required to establish the right to indemnification) arising out of or relating to your access or use of this dataset. The State reserves the right to modify or remove this dataset for any reason, without notice, at any time. Nothing in these terms constitutes or is intended to be a limitation upon, or waiver of, any privileges and immunities that apply to the State. These terms are governed by and interpreted under the law of the State of Michigan without regard to conflicts of laws provisions. Dataset Credit: U.S. Energy Information Administration, State of Michigan, and publicly available information
`

### Group 40

- Proposed licence: public_unrestricted
- Proposed redistribution: shareable
- Confidence: medium
- Quote source: item_licence_text
- Why: The text says there are no restrictions on use, reproduction, or distribution. This is not applied until a reviewer accepts the named grantor.
- Example URL: https://www.arcgis.com/home/item.html?id=276ba7206baf431180460c9743709469
- Sources (1): michigan_distributed_solar_2024_mpsc

`	ext
Access Constraints: None. Use Constraints: This data set is a public record and, as more fully described below, there are no restrictions on the use, reproduction, or distribution of this dataset. Notwithstanding the foregoing, the public release of this dataset should not be construed, expressed or implied, as to whether any use constitutes a legally permissible purpose. It is the sole responsibility of the user to determine if the data is usable for their purposes. This dataset is provided “AS IS” and on an “AS AVAILABLE” basis. The State of Michigan (“State”) makes no warranties, express or implied, regarding the accuracy, adequacy, reliability, timeliness, or completeness of the dataset. THE STATE DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS DATASET AND ANY INFORMATION PROVIDED TO YOU, INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT OF PROPRIETARY RIGHTS. THE STATE WILL NOT BE LIABLE, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY OR BY STATUTE OR OTHERWISE, FOR ANY CLAIM FOR CONSEQUENTIAL, INCIDENTAL, INDIRECT, OR SPECIAL DAMAGES, INCLUDING WITHOUT LIMITATION LOST PROFITS AND LOST BUSINESS OPPORTUNITIES, RELATED TO THE ACCESS OR USE OF THIS DATASET. IN NO EVENT WILL THE STATE BE LIABLE FOR ANY AMOUNTS THAT MAY RESULT FROM THE ACCESS OR USE OF THIS DATASET, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY, OR BY STATUTE OR OTHERWISE. You forever release the State, its departments, subdivisions, officers, and employees from all claims, rights, actions, demands, damages, liabilities, expenses and fees, which arise out of or relate to your access or use of this dataset. You must defend, indemnify and hold the State, its departments, subdivisions, officers, and employees harmless, without limitation, from and against all actions, claims, losses, liabilities, damages, costs, attorney fees, and expenses (including those required to establish the right to indemnification) arising out of or relating to your access or use of this dataset. The State reserves the right to modify or remove this dataset for any reason, without notice, at any time. Nothing in these terms constitutes or is intended to be a limitation upon, or waiver of, any privileges and immunities that apply to the State. These terms are governed by and interpreted under the law of the State of Michigan without regard to conflicts of laws provisions. Dataset Credit: State of Michigan, United States Census Bureau
`

### Group 41

- Proposed licence: public_unrestricted
- Proposed redistribution: shareable
- Confidence: medium
- Quote source: item_licence_text
- Why: The text says there are no restrictions on use, reproduction, or distribution. This is not applied until a reviewer accepts the named grantor.
- Example URL: https://www.arcgis.com/home/item.html?id=6baa84bc7a4b48f69778f12c35be0268
- Sources (1): michigan_hydroelectric_dams_mpsc

`	ext
Access Constraints: None. Use Constraints: This data set is a public record and, as more fully described below, there are no restrictions on the use, reproduction, or distribution of this dataset. Notwithstanding the foregoing, the public release of this dataset should not be construed, expressed or implied, as to whether any use constitutes a legally permissible purpose. It is the sole responsibility of the user to determine if the data is usable for their purposes. This dataset is provided “AS IS” and on an “AS AVAILABLE” basis. The State of Michigan (“State”) makes no warranties, express or implied, regarding the accuracy, adequacy, reliability, timeliness, or completeness of the dataset. THE STATE DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS DATASET AND ANY INFORMATION PROVIDED TO YOU, INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT OF PROPRIETARY RIGHTS. THE STATE WILL NOT BE LIABLE, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY OR BY STATUTE OR OTHERWISE, FOR ANY CLAIM FOR CONSEQUENTIAL, INCIDENTAL, INDIRECT, OR SPECIAL DAMAGES, INCLUDING WITHOUT LIMITATION LOST PROFITS AND LOST BUSINESS OPPORTUNITIES, RELATED TO THE ACCESS OR USE OF THIS DATASET. IN NO EVENT WILL THE STATE BE LIABLE FOR ANY AMOUNTS THAT MAY RESULT FROM THE ACCESS OR USE OF THIS DATASET, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY, OR BY STATUTE OR OTHERWISE. You forever release the State, its departments, subdivisions, officers, and employees from all claims, rights, actions, demands, damages, liabilities, expenses and fees, which arise out of or relate to your access or use of this dataset. You must defend, indemnify and hold the State, its departments, subdivisions, officers, and employees harmless, without limitation, from and against all actions, claims, losses, liabilities, damages, costs, attorney fees, and expenses (including those required to establish the right to indemnification) arising out of or relating to your access or use of this dataset. The State reserves the right to modify or remove this dataset for any reason, without notice, at any time. Nothing in these terms constitutes or is intended to be a limitation upon, or waiver of, any privileges and immunities that apply to the State. These terms are governed by and interpreted under the law of the State of Michigan without regard to conflicts of laws provisions. Dataset Credit: U.S. Army Corps of Engineers (USACE), State of Michigan
`

### Group 42

- Proposed licence: public_unrestricted
- Proposed redistribution: shareable
- Confidence: medium
- Quote source: item_licence_text
- Why: The text says there are no restrictions on use, reproduction, or distribution. This is not applied until a reviewer accepts the named grantor.
- Example URL: https://www.arcgis.com/home/item.html?id=f7fff6ec9567480aa1e2341b0132f4d3
- Sources (1): michigan_natural_gas_power_plants_mpsc

`	ext
Access Constraints: None. Use Constraints: This data set is a public record and, as more fully described below, there are no restrictions on the use, reproduction, or distribution of this dataset. Notwithstanding the foregoing, the public release of this dataset should not be construed, expressed or implied, as to whether any use constitutes a legally permissible purpose. It is the sole responsibility of the user to determine if the data is usable for their purposes. This dataset is provided “AS IS” and on an “AS AVAILABLE” basis. The State of Michigan (“State”) makes no warranties, express or implied, regarding the accuracy, adequacy, reliability, timeliness, or completeness of the dataset. THE STATE DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS DATASET AND ANY INFORMATION PROVIDED TO YOU, INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT OF PROPRIETARY RIGHTS. THE STATE WILL NOT BE LIABLE, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY OR BY STATUTE OR OTHERWISE, FOR ANY CLAIM FOR CONSEQUENTIAL, INCIDENTAL, INDIRECT, OR SPECIAL DAMAGES, INCLUDING WITHOUT LIMITATION LOST PROFITS AND LOST BUSINESS OPPORTUNITIES, RELATED TO THE ACCESS OR USE OF THIS DATASET. IN NO EVENT WILL THE STATE BE LIABLE FOR ANY AMOUNTS THAT MAY RESULT FROM THE ACCESS OR USE OF THIS DATASET, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY, OR BY STATUTE OR OTHERWISE. You forever release the State, its departments, subdivisions, officers, and employees from all claims, rights, actions, demands, damages, liabilities, expenses and fees, which arise out of or relate to your access or use of this dataset. You must defend, indemnify and hold the State, its departments, subdivisions, officers, and employees harmless, without limitation, from and against all actions, claims, losses, liabilities, damages, costs, attorney fees, and expenses (including those required to establish the right to indemnification) arising out of or relating to your access or use of this dataset. The State reserves the right to modify or remove this dataset for any reason, without notice, at any time. Nothing in these terms constitutes or is intended to be a limitation upon, or waiver of, any privileges and immunities that apply to the State. These terms are governed by and interpreted under the law of the State of Michigan without regard to conflicts of laws provisions. Dataset Credit: EIA , State of Michigan
`

### Group 43

- Proposed licence: public_unrestricted
- Proposed redistribution: shareable
- Confidence: medium
- Quote source: item_licence_text
- Why: The text says there are no restrictions on use, reproduction, or distribution. This is not applied until a reviewer accepts the named grantor.
- Example URL: https://www.arcgis.com/home/item.html?id=f10a6c66e2284fd6866bed48fa021644
- Sources (1): michigan_nuclear_power_plants_mpsc

`	ext
Access Constraints: None. Use Constraints: This data set is a public record and, as more fully described below, there are no restrictions on the use, reproduction, or distribution of this dataset. Notwithstanding the foregoing, the public release of this dataset should not be construed, expressed or implied, as to whether any use constitutes a legally permissible purpose. It is the sole responsibility of the user to determine if the data is usable for their purposes. This dataset is provided “AS IS” and on an “AS AVAILABLE” basis. The State of Michigan (“State”) makes no warranties, express or implied, regarding the accuracy, adequacy, reliability, timeliness, or completeness of the dataset. THE STATE DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS DATASET AND ANY INFORMATION PROVIDED TO YOU, INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT OF PROPRIETARY RIGHTS. THE STATE WILL NOT BE LIABLE, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY OR BY STATUTE OR OTHERWISE, FOR ANY CLAIM FOR CONSEQUENTIAL, INCIDENTAL, INDIRECT, OR SPECIAL DAMAGES, INCLUDING WITHOUT LIMITATION LOST PROFITS AND LOST BUSINESS OPPORTUNITIES, RELATED TO THE ACCESS OR USE OF THIS DATASET. IN NO EVENT WILL THE STATE BE LIABLE FOR ANY AMOUNTS THAT MAY RESULT FROM THE ACCESS OR USE OF THIS DATASET, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY, OR BY STATUTE OR OTHERWISE. You forever release the State, its departments, subdivisions, officers, and employees from all claims, rights, actions, demands, damages, liabilities, expenses and fees, which arise out of or relate to your access or use of this dataset. You must defend, indemnify and hold the State, its departments, subdivisions, officers, and employees harmless, without limitation, from and against all actions, claims, losses, liabilities, damages, costs, attorney fees, and expenses (including those required to establish the right to indemnification) arising out of or relating to your access or use of this dataset. The State reserves the right to modify or remove this dataset for any reason, without notice, at any time. Nothing in these terms constitutes or is intended to be a limitation upon, or waiver of, any privileges and immunities that apply to the State. These terms are governed by and interpreted under the law of the State of Michigan without regard to conflicts of laws provisions. Dataset Credit: EIA , State of Michigan, U.S. NRC
`

### Group 44

- Proposed licence: public_unrestricted
- Proposed redistribution: shareable
- Confidence: medium
- Quote source: item_licence_text
- Why: The text says there are no restrictions on use, reproduction, or distribution. This is not applied until a reviewer accepts the named grantor.
- Example URL: https://www.arcgis.com/home/item.html?id=2f318d742c2b4ea9a20c51c3537ec9c5
- Sources (1): michigan_solar_power_plants_mpsc

`	ext
Access Constraints: None. Use Constraints: This data set is a public record and, as more fully described below, there are no restrictions on the use, reproduction, or distribution of this dataset. Notwithstanding the foregoing, the public release of this dataset should not be construed, expressed or implied, as to whether any use constitutes a legally permissible purpose. It is the sole responsibility of the user to determine if the data is usable for their purposes. This dataset is provided “AS IS” and on an “AS AVAILABLE” basis. The State of Michigan (“State”) makes no warranties, express or implied, regarding the accuracy, adequacy, reliability, timeliness, or completeness of the dataset. THE STATE DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS DATASET AND ANY INFORMATION PROVIDED TO YOU, INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT OF PROPRIETARY RIGHTS. THE STATE WILL NOT BE LIABLE, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY OR BY STATUTE OR OTHERWISE, FOR ANY CLAIM FOR CONSEQUENTIAL, INCIDENTAL, INDIRECT, OR SPECIAL DAMAGES, INCLUDING WITHOUT LIMITATION LOST PROFITS AND LOST BUSINESS OPPORTUNITIES, RELATED TO THE ACCESS OR USE OF THIS DATASET. IN NO EVENT WILL THE STATE BE LIABLE FOR ANY AMOUNTS THAT MAY RESULT FROM THE ACCESS OR USE OF THIS DATASET, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY, OR BY STATUTE OR OTHERWISE. You forever release the State, its departments, subdivisions, officers, and employees from all claims, rights, actions, demands, damages, liabilities, expenses and fees, which arise out of or relate to your access or use of this dataset. You must defend, indemnify and hold the State, its departments, subdivisions, officers, and employees harmless, without limitation, from and against all actions, claims, losses, liabilities, damages, costs, attorney fees, and expenses (including those required to establish the right to indemnification) arising out of or relating to your access or use of this dataset. The State reserves the right to modify or remove this dataset for any reason, without notice, at any time. Nothing in these terms constitutes or is intended to be a limitation upon, or waiver of, any privileges and immunities that apply to the State. These terms are governed by and interpreted under the law of the State of Michigan without regard to conflicts of laws provisions. Dataset Credit: EIA, State of Michigan
`

### Group 45

- Proposed licence: public_unrestricted
- Proposed redistribution: shareable
- Confidence: medium
- Quote source: item_licence_text
- Why: The text says there are no restrictions on use, reproduction, or distribution. This is not applied until a reviewer accepts the named grantor.
- Example URL: https://www.arcgis.com/home/item.html?id=4774ee92d7a5454c93c99a6abc31c421
- Sources (1): michigan_wind_turbines_mpsc

`	ext
Access Constraints: None. Use Constraints: This data set is a public record and, as more fully described below, there are no restrictions on the use, reproduction, or distribution of this dataset. Notwithstanding the foregoing, the public release of this dataset should not be construed, expressed or implied, as to whether any use constitutes a legally permissible purpose. It is the sole responsibility of the user to determine if the data is usable for their purposes. This dataset is provided “AS IS” and on an “AS AVAILABLE” basis. The State of Michigan (“State”) makes no warranties, express or implied, regarding the accuracy, adequacy, reliability, timeliness, or completeness of the dataset. THE STATE DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS DATASET AND ANY INFORMATION PROVIDED TO YOU, INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT OF PROPRIETARY RIGHTS. THE STATE WILL NOT BE LIABLE, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY OR BY STATUTE OR OTHERWISE, FOR ANY CLAIM FOR CONSEQUENTIAL, INCIDENTAL, INDIRECT, OR SPECIAL DAMAGES, INCLUDING WITHOUT LIMITATION LOST PROFITS AND LOST BUSINESS OPPORTUNITIES, RELATED TO THE ACCESS OR USE OF THIS DATASET. IN NO EVENT WILL THE STATE BE LIABLE FOR ANY AMOUNTS THAT MAY RESULT FROM THE ACCESS OR USE OF THIS DATASET, REGARDLESS OF THE FORM OF ACTION, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY, OR BY STATUTE OR OTHERWISE. You forever release the State, its departments, subdivisions, officers, and employees from all claims, rights, actions, demands, damages, liabilities, expenses and fees, which arise out of or relate to your access or use of this dataset. You must defend, indemnify and hold the State, its departments, subdivisions, officers, and employees harmless, without limitation, from and against all actions, claims, losses, liabilities, damages, costs, attorney fees, and expenses (including those required to establish the right to indemnification) arising out of or relating to your access or use of this dataset. The State reserves the right to modify or remove this dataset for any reason, without notice, at any time. Nothing in these terms constitutes or is intended to be a limitation upon, or waiver of, any privileges and immunities that apply to the State. These terms are governed by and interpreted under the law of the State of Michigan without regard to conflicts of laws provisions. Dataset Credit: ACP, EIA, LBNL, State of Michigan, and USGS
`

### Group 46

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://gisdata.pima.gov/arcgis1/rest/services/GISOpenData/OverlayUtilities/MapServer/2
- Sources (1): arizona_pima_electric_service_areas

`	ext
Pima County Information Technology Department - Geographic Information Systems 33 N Stone Ave., 15th Floor Tucson, AZ 85701
`

### Group 47

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: A warranty disclaimer is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=df37fc5ffd774fcfaffebb4c8b4b6208
- Sources (1): arizona_water_service_areas_adhs_2022

`	ext
While every effort has been made to ensure the accuracy of these data, the Arizona Department of Health Services (ADHS) provides them on an “as is” and “as available” basis. ADHS makes no representations or warranties , express or implied, regarding the accuracy, completeness, reliability, or suitability of the data for any particular purpose. ADHS shall not be liable for any errors, inaccuracies, or omissions, nor for any damages, losses, or liabilities arising from the use of, or reliance on, these data. Pursuant to A.R.S. § 37-178 , a public agency that shares geospatial data of which it is the custodian is not liable for errors, inaccuracies, or omissions and shall be held harmless from and against all damage, loss, or liability arising from any use of shared geospatial data. The information contained in these datasets is dynamic and may change over time. Users are responsible for reviewing and using the data in a manner consistent with the purpose, limitations, and update frequency described in the associated metadata . Any boundary, linear, or point locations contained in these datasets or displayed in associated applications are approximate and should not be used for authoritative, regulatory, or legal location purposes . Users should independently research, investigate, and verify all information to determine whether the data quality is appropriate for their intended use. If legally defensible boundaries or locations are required, they should be established by an appropriate state-registered professional .
`

### Group 48

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://gis.arkansas.gov/arcgis/rest/services/FEATURESERVICES/Utilities/MapServer/18
- Sources (1): arkansas_electric_substations_gis

`	ext
Arkansas GIS Office
`

### Group 49

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://gis.arkansas.gov/arcgis/rest/services/FEATURESERVICES/Utilities/MapServer/12
- Sources (1): arkansas_electric_territories_gis

`	ext
AR Geographic Information Office
`

### Group 50

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_licence_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=fbba842bf134497c9d611ad506ec48cc
- Sources (1): california_water_areas_swrcb

`	ext
Please note that the service areas may change without notice as the data set is dynamic and updated on an on-going basis.
`

### Group 51

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_licence_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=aeff5c54d4e34b01bc7f8a8a00b23e8e
- Sources (1): connecticut_connected_sewer_areas

`	ext
This data contained herein was collated using existing data from multiple sources. No guarantee of quality, accuracy, and completeness is made. The data does not constitute an endorsement or approval of any existing or planned land use that may be interpreted from the information contained herein. This data is publicly available. CC0
`

### Group 52

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Planimetrics_1999/MapServer/25
- Sources (1): dc_electric_substations_1999_dcgis

`	ext
DC GIS
`

### Group 53

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: Public or Public Use alone is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=597555ce8e4a4892a030784a7c657fdd
- Sources (1): electric_retail_territories_hifld

`	ext
None (Public Use). Users are advised to read the data set's metadata thoroughly to understand appropriate use and data limitations.
`

### Group 54

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: A warranty disclaimer is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=6ffb9014f190482da5b2ff77d0f60464
- Sources (1): florida_lee_water_service_area

`	ext
The Lee County GIS Department has provided these GIS data sets as a public information resource. Every reasonable effort has been made to assure the accuracy of the data and other information contained. However, these data, maps, and other information are only as accurate as the source of such data, maps, and other information. Further, the data, maps, and other information on this layer are updated only periodically and therefore may not reflect the most current information. The Lee County GIS Department makes no warranty, representation, or guarantee of any kind regarding either any data or other information provided herein or the sources of such data, maps, or other information. The Lee County GIS Department specifically disclaims all representations or warranties, express or implied, including, without limitation, the implied warranties of merchantability and fitness for a particular purpose. The Lee County GIS Department assumes no liability either for any errors, omissions, or inaccuracies in the information provided regardless of the cause of such or for any decision made, action taken, or action not taken by the user in reliance upon any data, maps, or information provided herein.
`

### Group 55

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: A warranty disclaimer is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=f2f54ba2896e464a890ce827644f250d
- Sources (1): florida_sjrwmd_water_service_areas

`	ext
The St. Johns River Water Management District (SJRWMD) develops and maintains geospatial content for its internal use and purposes. It is provided “as is” to the public without warranty and may not be suitable for other applications. Full disclaimer: https://www.sjrwmd.com/disclaimer/ Additional SJRWMD GIS resources: https://www.sjrwmd.com/data/gis Contact Guidance: To avoid delays and duplicate tickets, please do not include both of the following email addresses in the same message: For questions about existing geospatial datasets or web services , contact GIS Support at GIS_Support@sjrwmd.com . For inquiries about modeling, analysis projects, or related reports , contact the District Clerk at clerk@sjrwmd.com , who will route your request to the appropriate experts.
`

### Group 56

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www45.swfwmd.state.fl.us/arcgis12/rest/services/OpenData/RegulatoryPro/MapServer/16
- Sources (1): florida_swfwmd_water_service_areas

`	ext
Southwest Florida Water Management District
`

### Group 57

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: A warranty disclaimer is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=6cbd5cf5be394ac48cebe905d4baf775
- Sources (1): hawaii_maui_recycled_water_customers

`	ext
County of Maui uses Geographical Information Systems (hereafter "GIS") technology to provide a visual display of data for the convenience of the end user. There are no expressed warranties associated with the release of these data. Specifically, no warranty is made that the GIS data or any subsequent updates will be error free and no warranty is made regarding the positional, thematic or attribute accuracy of the GIS data. The GIS data and any features it depicts do not represent or confer any legal rights, privileges, benefits, boundaries or claims of any kind, and data is subject to change.
`

### Group 58

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: Public or Public Use alone is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=675906ae06b5460296154760b7fb1367
- Sources (1): illinois_electric_territories_broadband_office

`	ext
This dataset is provided for public use, government planning, economic development, and research . Public Availability: The dataset is available for GIS mapping, spatial analysis, and planning projects . No Warranty: This dataset is provided as-is , with no guarantee of accuracy, completeness, or timeliness. Non-Legal Use: It is intended for informational and planning purposes only and should not be used for legal boundary determinations . Attribution Requirement: Users must cite the data source when using this dataset in maps, reports, or publications. Modification & Redistribution: Users may modify or analyze the data but must indicate any changes when sharing derived products. Liability Disclaimer: The publisher is not responsible for errors, omissions, or misinterpretations arising from the dataset’s use.
`

### Group 59

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_licence_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=8352a5af1f854f0ab6138e2c6d26b2f3
- Sources (1): iowa_electric_service_areas_iuc

`	ext
CC BY
`

### Group 60

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_licence_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=bbbcda170fd3499bba7ed2f0fe64460f
- Sources (1): kentucky_natural_gas_distribution_areas

`	ext
LIMITATION OF LIABILITY: The Kentucky Infrastructure Authority (KIA) has no indication or reason to believe that there are any inaccuracies or defects of information incorporated in this work and make no representations of any kind, including, but not limited to, the warranties of merchantability or fitness for a particular use, nor are any such warranties to be implied, with respect to the information or data, furnished herein. https://creativecommons.org/publicdomain/zero/1.0/
`

### Group 61

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://maps.brla.gov/gis/rest/services/Governmental_Units/Utility_Coverage_Area/MapServer/0
- Sources (1): louisiana_east_baton_rouge_electric_areas

`	ext
EBRGIS; DEMCO; ENTERGY; Department of Transportation and Drainage; Department of Information Services
`

### Group 62

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: Public or Public Use alone is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=03cb7df975ef488f8a248ef55e6c6470
- Sources (1): maine_electric_service_areas_puc_2020

`	ext
Public Access
`

### Group 63

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=715955c500164789a7a30a68f9b3a2eb
- Sources (1): missouri_public_water_districts_dnr

`	ext
Missouri Office of Administration, Information Technology Services Division, Office of Geospatial Information; Missouri Department of Natural Resources
`

### Group 64

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://mapsdep.nj.gov/arcgis/rest/services/Features/Utilities/MapServer/26
- Sources (1): new_jersey_community_solar_projects_dep

`	ext
New Jersey Community Solar PV Projects, Edition 20200318
`

### Group 65

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://mapsdep.nj.gov/arcgis/rest/services/Features/Utilities/MapServer/24
- Sources (1): new_jersey_rggi_power_generating_units_dep

`	ext
United States Environmental Protection Agency Air Markets Program Data https://ampd.epa.gov/ampd/ United Stated Energy Information Administration https://www.eia.gov/
`

### Group 66

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://mapsdep.nj.gov/arcgis/rest/services/Features/Utilities/MapServer/22
- Sources (1): new_jersey_solar_pv_behind_meter_dep

`	ext
NJDEP, Bureau of Energy and Sustainability Edition 20190327
`

### Group 67

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: A warranty disclaimer is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=9d06927341da47f49525203cfeb93fa0
- Sources (1): new_mexico_public_water_system_areas_ose

`	ext
The New Mexico Office of the State Engineer (OSE) provides this geographic data and any associated metadata “as is” without warranty of any kind, including but not limited to its completeness, fitness for a particular use, or accuracy of its content, positional or otherwise. It is the sole responsibility of the user to determine the usability of the data for their purposes. In no event shall OSE have any liability whatsoever for payment of any consequential, incidental, indirect, special, or tort damages of any kind arising out of the use of or reliance on the geographic data or metadata. In providing this data or access to it, OSE assumes no obligation to assist the user in the use of such data or in the development, use, or maintenance of any applications applied to or associated with the data or metadata.
`

### Group 68

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://gis.greensboro-nc.gov/arcgis/rest/services/WaterResources/GeneralBasemapNoOrthos_MS/MapServer/6
- Sources (1): north_carolina_greensboro_water_sewer_service_area

`	ext
Water Resources
`

### Group 69

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: A warranty disclaimer is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=a4f83983d536407eb1adee8740f1ccde
- Sources (1): north_dakota_rural_water_districts_ndgis

`	ext
The North Dakota State Water Commission has compiled this data according to conventional cartographic standards, using what is thought to be the most reliable information available. This data is intended to make results of research available at the earliest possible date, but is not intended to constitute final or formal publication. The State of North Dakota makes every effort to provide virus-free files but does not guarantee uncorrupted files. The North Dakota State Water Commission does not guarantee this data to be free from errors, inaccuracies, or viruses, and disclaims any responsibility or liability for interpretations or decisions based on this data.
`

### Group 70

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=05db59d695b147cfb13fbfd24ff838ac
- Sources (1): ohio_water_service_areas_puco

`	ext
PUCO
`

### Group 71

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: A warranty disclaimer is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=3cd4236ec9284a0fa307aef9e6433cb9
- Sources (1): oklahoma_water_pipelines_owrb

`	ext
The data represent the results of data collection and/or processing for the specific OWRB activity or purpose described above. As such, the data are valid only for their use, content, time, and accuracy specifications determined or intended by, or acceptable to, the OWRB. These data are not guaranteed to be useable, timely, accurate, or complete. The user is responsible for any use of these data other than their use by the OWRB, and for the results of any application of the data for other than the purpose intended by the OWRB. Although these data have been processed successfully on a computer system at the OWRB, NEITHER THE STATE OF OKLAHOMA NOR THE OWRB NOR ANY OTHER AGENCY THEREOF, NOR ANY OF THEIR EMPLOYEES, CONTRACTORS, OR SUBCONTRACTORS, MAKE ANY WARRANTY, EXPRESS OR IMPLIED, NOR ASSUME ANY LEGAL LIABILITY OR RESPONSIBILITY FOR OR AS TO THE ACCURACY, COMPLETENESS, USEFULNESS OR MERCHANTABILITY OF ANY DATUM, SOFTWARE, INFORMATION, APPARATUS, PRODUCT, OR PROCESS DISCLOSED, NOR REPRESENT THAT ITS USE WOULD NOT INFRINGE ON PRIVATELY OWNED RIGHTS. NOR SHALL THE ACT OF DISTRIBUTION CONSTITUTE ANY SUCH WARRANTY. THIS DISCLAIMER APPLIES BOTH TO INDIVIDUAL USE OF THE DATA AND AGGREGATE USE WITH OTHER DATA. Conclusions drawn from, or actions undertaken on the basis of, such data and information are the sole responsibility of the user. Users are cautioned to consider carefully the provisional nature of these data and information before using them for decisions that concern personal or public safety or the conduct of business that involves substantial monetary or operational consequences.
`

### Group 72

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=348739b0e7cd4a2b95c2eb8362581c6d
- Sources (1): oklahoma_water_service_areas_owrb

`	ext
OWRB
`

### Group 73

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: A warranty disclaimer is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=2102826e218c4d36a24583613df76f0c
- Sources (1): oregon_electric_gas_areas_odoe

`	ext
Users are expected to review this message. By accessing and using information available through this product, you are accepting the terms of this disclaimer without modification. If you do not accept or agree with this disclaimer, you must not use this product or its contents, and discontinue use. This product contains data from many sources. Although steps have been taken to provide accurate information, errors and conditions originating from sources used to develop the data may be reflected in the information accessed. Users must be aware of possible conditions and bear responsibility with respect to errors, collection methodologies, currency, and other conditions related to this product. ODOE geospatial products are for informational purposes only and are not provided for, or and are not represented as suitable for legal, engineering, or surveying purposes. The Oregon Department of Energy, State of Oregon, and GEOHub data providers are not liable for any damages caused by or resulting from any use of the data, such as for any inaccuracies in the data, web services or applications. ODOE data, web services and applications are provided “as is,” and no representations or warranties are made with respect to the data, web services or applications, including but not limited to implied warranties of merchantability or fitness for a particular purpose. Users of this information are solely responsible for and should consult the applicable data custodian to ascertain the usability of the information. This information or data is provided with the understanding that conclusions drawn from such information are the responsibility of the user. Written release agreements for use of the geospatial data, web services, and applications found on the publicly accessible components of ODOE geospatial products are not required and will not be issued. The inclusion of trade names or use of commercial products does not constitute their endorsement by the Oregon Department of Energy, Oregon Geographic Information Council, GEOHub, or the State of Oregon. Use of the data, including for any commercial purpose, must not violate applicable laws or regulations.
`

### Group 74

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_access_information
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=bc7d5129eafb4e948749a27aad63d967
- Sources (1): puerto_rico_power_generation_fema_2022

`	ext
LUMA, PREPA and FEMA
`

### Group 75

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: layer_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.horrycounty.org/gispublic/rest/services/PlanningAndZoning/PZ_Layers/MapServer/6
- Sources (1): south_carolina_horry_water_sewer_areas

`	ext
Adapted from Grand Strand Water and Sewer data, incorporating updates from the City of Conway. Date: 2/11/2020. Contact Leigh Kane, Planning & Zoning 843-915-7917 with any questions. For verification of coverage, contact the water and sewer service provider.
`

### Group 76

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_licence_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=cc62b90b5775475c94f503cf225c5fd7
- Sources (1): tennessee_public_water_service_areas_tdec

`	ext
These data should not be used as an endpoint for decision making at local scales for water system infrastructure. These datasets are generated at a coarse scale not intended to be interpreted at local scales. More detailed information at a local scale for water utility service should be obtained from the local service providers in that area.
`

### Group 77

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_access_information
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=f52df8dc50a64ec9bff56c423703684d
- Sources (1): usvi_wastewater_plants_fema_viwma_2021

`	ext
Virgin Islands Waste Management Agency and FEMA
`

### Group 78

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: CC BY-SA is outside the licence vocabulary, so the source stays internal.
- Example URL: https://www.arcgis.com/home/item.html?id=dc62a286013f447e88fc45480077c944
- Sources (1): utah_culinary_water_areas_dwre

`	ext
CC BY-SA These boundaries or service areas are not legal descriptions, and are meant to generally represent service areas. No claim is made regarding boundary accuracy, and the data should be used with that understanding. This dataset may be shared, so long as sources and time relevance are cited. Be aware that this dataset is a work in progress, and does receive updates on at least an annual basis. For reference use only. Although this product represents the work of natural resource professionals, the Utah Department of Natural Resources, makes no warranty, expressed or implied, regarding its suitability for a particular use. The Utah Department of Natural Resources, shall not be liable under any circumstances for any direct, indirect, special, incidental, or consequential damages with respect to claims by users of this product.
`

### Group 79

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: A warranty disclaimer is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=92916071272248d48dcd546dd2ec72ec
- Sources (1): utah_electric_service_areas_ugrc

`	ext
The data, including but not limited to geographic data, tabular data, and analytical data, are provided "as is" and "as available", with no guarantees relating to the availability, completeness, or accuracy of data, and without any express or implied warranties. These data are provided as a public service for informational purposes only. You are solely responsible for obtaining the proper evaluation of a location and associated data by a qualified professional. UGRC reserves the right to change, revise, suspend or discontinue published data and services without notice at any time. Neither UGRC nor the State of Utah are responsible for any misuse or misrepresentation of the data. UGRC and the State of Utah are not obligated to provide you with any maintenance or support. The user assumes the entire risk as to the quality and performance of the data. You agree to hold the State of Utah harmless for any claims, liability, costs, and damages relating to your use of the data. You agree that your sole remedy for any dissatisfaction or claims is to discontinue use of the data. This work is licensed under a Creative Commons Attribution 4.0 International License .
`

### Group 80

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_licence_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=a0906e5184364ca3afecef163d25bb84
- Sources (1): virginia_fairfax_sewer_service_areas

`	ext
Please review the Fairfax County GIS Division disclaimer
`

### Group 81

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: service_copyright_text
- Why: The re-fetched text does not state a redistribution grant.
- Example URL: https://www.arcgis.com/home/item.html?id=2fc29eb87c094861a5c4872275d5f6b8
- Sources (1): washington_drinking_water_areas_doh

`	ext
WA Dept. of Ecology
`

### Group 82

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: low
- Quote source: item_licence_text
- Why: The record is a link without the grant on that page. The link was not used as the licence.
- Example URL: https://www.arcgis.com/home/item.html?id=c03ea3481bb74540a26b132f265ad49a
- Sources (1): washington_king_county_sewer_service_providers

`	ext
https://kingcounty.gov/en/dept/kcit/data-information-services/gis-center/about/terms-conditions-copyrights
`

### Group 83

- Proposed licence: unknown
- Proposed redistribution: internal_only
- Confidence: high
- Quote source: item_licence_text
- Why: A warranty disclaimer is not a licence grant.
- Example URL: https://www.arcgis.com/home/item.html?id=8d95d582e5fe47b79044cdca8aff98ca
- Sources (1): wisconsin_dane_carpc_sewer_service_areas

`	ext
Public data sets made available on the web portal or other means are provided for informational purposes. The Capital Area Regional Planning Commission (CARPC) does not warranty the completeness, accuracy, content or fitness for any particular purpose or use of any public data set made available on the web portal or transmitted by other means, nor are any such warranties to be implied or inferred with respect to the public data sets furnished therein. CARPC is not liable for any deficiencies in the completeness, accuracy, content or fitness for any particular purpose or use of an public data set, or application utilizing such data set, provided by any third party. Any maps, reports or publications created using data provided by CARPC shall give credit using the following statement: "This was created using CARPC digital data, but it is a secondary product that has not been verified or endorsed by CARPC". CARPC reserves the right to discontinue the availability of any data set at any time and for any reason.
`

## Sources outside the ArcGIS re-fetch

These sources were not in the ArcGIS evidence file. Their licence was not changed from the registry value, and a government publisher was not treated as a grant.

- census_tiger2025_tabblock20 driver http registry licence public_domain url https://www2.census.gov/geo/tiger/TIGER2025/TABBLOCK20/tl_2025_{statefp}_tabblock20.zip
- census_tiger2025_place driver http registry licence public_domain url https://www2.census.gov/geo/tiger/TIGER2025/PLACE/tl_2025_{statefp}_place.zip
- census_tiger2025_cousub driver http registry licence public_domain url https://www2.census.gov/geo/tiger/TIGER2025/COUSUB/tl_2025_{statefp}_cousub.zip
- census_tiger2025_tract driver http registry licence public_domain url https://www2.census.gov/geo/tiger/TIGER2025/TRACT/tl_2025_{statefp}_tract.zip
- census_tiger2025_zcta520 driver http registry licence public_domain url https://www2.census.gov/geo/tiger/TIGER2025/ZCTA520/tl_2025_us_zcta520.zip
- census_tiger2025_aiannh driver http registry licence public_domain url https://www2.census.gov/geo/tiger/TIGER2025/AIANNH/tl_2025_us_aiannh.zip
- census_tiger2025_county driver http registry licence public_domain url https://www2.census.gov/geo/tiger/TIGER2025/COUNTY/tl_2025_us_county.zip
- census_tiger2025_state driver http registry licence public_domain url https://www2.census.gov/geo/tiger/TIGER2025/STATE/tl_2025_us_state.zip
- census_baf2020 driver http registry licence public_domain url https://www2.census.gov/geo/docs/maps-data/data/baf2020/BlockAssign_ST{statefp}_{usps}.zip
- census_ct_county_crosswalk driver http registry licence public_domain url https://www2.census.gov/geo/docs/reference/ct_change/ct_cou_to_cousub_crosswalk.txt
- census_government_units_2025 driver http registry licence public_domain url https://www2.census.gov/programs-surveys/gus/datasets/2025/gov_units_2025.zip
- federal_eia176_ng_companies driver http registry licence unknown url https://www.eia.gov/naturalgas/ngqs/all_ng_data.zip
- federal_epa_cwns_2022 driver http registry licence unknown url https://sdwis.epa.gov/ords/sfdw_pub/r/sfdw/cwns_pub/data-download
- federal_epa_pws_boundaries_v3 driver http registry licence unknown url https://media.githubusercontent.com/media/USEPA/ORD_SAB_Model/main/Version_History/PWS_Boundaries_Latest.zip
- federal_epa_sdwa_2026q3 driver http registry licence unknown url https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip
- federal_epa_sewersheds_v1_3 driver http registry licence unknown url https://media.githubusercontent.com/media/USEPA/Sewersheds/main/Current_Release.zip
- state_mn_electric_service_areas driver http registry licence unknown url https://operations.gis.data.mn.gov/api/publicdownload/download/518/util_eusa.gpkg
- state_ny_electric_territories driver http registry licence unknown url https://data.ny.gov/api/v3/views/awza-4vgu/query.geojson?accessType=DOWNLOAD
- state_ny_gas_territories driver http registry licence unknown url https://data.ny.gov/api/v3/views/i7nm-ih89/query.geojson?accessType=DOWNLOAD
- ornl_hydrosource_ferc_mitigation driver None registry licence unknown url None
- ornl_hydrosource_relicensing_pipeline driver None registry licence unknown url None
- supplemental_alabama_power_service_territory driver http registry licence None url https://www.alabamapower.com/content/dam/alabama-power/pdfs-docs/company/service-territory-maps/alabamapowerserviceterritory.kmz
- supplemental_pws_community driver http registry licence None url https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/excel/pws_community.xlsx
- supplemental_pws_nontransient_noncommunity driver http registry licence None url https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/excel/pws_ntnc.xlsx
- supplemental_pws_transient_noncommunity driver http registry licence None url https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/excel/pws_tnc.xlsx
- supplemental_eia861m_2026_sales_ultimate_customers driver http registry licence None url https://www.eia.gov/electricity/data/eia861m/xls/sales_ult_cust_2026.xlsx
- supplemental_eia861m_2026_net_metering driver http registry licence None url https://www.eia.gov/electricity/data/eia861m/xls/net_metering2026.xlsx
- supplemental_eia861m_2026_non_net_metering driver http registry licence None url https://www.eia.gov/electricity/data/eia861m/xls/non_netmetering2026.xlsx
- supplemental_eia861m_2026_small_scale_solar driver http registry licence None url https://www.eia.gov/electricity/data/eia861m/xls/small_scale_solar_2026.xlsx
- supplemental_eia923_2025 driver http registry licence None url https://www.eia.gov/electricity/data/eia923/xls/f923_2025.zip
- supplemental_eia923_2026_monthly driver http registry licence None url https://www.eia.gov/electricity/data/eia923/xls/f923_2026.zip
- supplemental_epa_sewer_systems driver http registry licence None url https://echo.epa.gov/files/echodownloads/current_sewer_overflow_and_collection_systems_tables.zip
- supplemental_epa_sdwa_system_search driver http registry licence None url https://echo.epa.gov/files/echodownloads/SDWA_system_search_download.zip
- supplemental_ferc_active_hydro_exemptions_20261109 driver http registry licence None url https://data.ferc.gov/active-hydropower-projects/active-exemptions/
- supplemental_ferc_active_hydro_licenses_20261109 driver http registry licence None url https://data.ferc.gov/active-hydropower-projects/active-licenses/
- supplemental_ferc_cid_listing_aug2025 driver http registry licence None url https://www.ferc.gov/sites/default/files/2025-08/August_2025_CID.xlsx
- supplemental_cesspool_prioritization driver http registry licence None url https://files.hawaii.gov/dbedt/op/gis/data/hcpt_cesspool_data.shp.zip
- supplemental_offshore_sewer_lines driver http registry licence None url https://files.hawaii.gov/dbedt/op/gis/data/sewerlines.shp.zip
- supplemental_onsite_sewage_systems driver http registry licence None url https://files.hawaii.gov/dbedt/op/gis/data/osds.shp.zip
- supplemental_metc_musa_planning driver http registry licence internal_or_no_redistribution url https://gisdata.metc.state.mn.us/gisdata/Planning/musa.zip
- supplemental_metc_sanitary_sewersheds_public driver http registry licence internal_or_no_redistribution url https://gisdata.metc.state.mn.us/gisdata/Utility/sanitary_sewersheds.zip
- supplemental_metc_sewer_interceptors_public driver http registry licence internal_or_no_redistribution url https://gisdata.metc.state.mn.us/gisdata/Utility/sewer_interceptors.zip
- supplemental_metc_wastewater_treatment_plants_public driver http registry licence internal_or_no_redistribution url https://gisdata.metc.state.mn.us/gisdata/Utility/wastewater_treatment_plants.zip
- supplemental_electricity_tables_2024_deq driver http registry licence None url https://deq.mt.gov/files/Energy/Documents/Energy_Statistics/ElectricityTables2024.xlsx
- supplemental_natural_gas_tables_2024_deq driver http registry licence None url https://deq.mt.gov/files/Energy/Documents/Energy_Statistics/NaturalGasTables2024.xlsx
- supplemental_public_water_purveyors_2026_geodatabase driver http registry licence None url https://www.nj.gov/dep/gis/digidownload/zips/OpenData/Util_drinkingwater_PSA.zip
- supplemental_public_water_purveyors_2026_shapefile driver http registry licence None url https://www.nj.gov/dep/gis/digidownload/zips/OpenData/Util_drinkingwater_PSA_shp.zip
- supplemental_datapackage driver http registry licence None url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/zenodo/phmsagas/10.5281-zenodo.23296837/datapackage.json
- supplemental_phmsagas_gas_distribution_1970_2003 driver http registry licence None url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/zenodo/phmsagas/10.5281-zenodo.23296837/phmsagas_gas_distribution_1970_2003.zip
- supplemental_phmsagas_gas_distribution_2004_2009 driver http registry licence None url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/zenodo/phmsagas/10.5281-zenodo.23296837/phmsagas_gas_distribution_2004_2009.zip
- supplemental_phmsagas_gas_transmission_gathering_1970_2000 driver http registry licence None url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/zenodo/phmsagas/10.5281-zenodo.23296837/phmsagas_gas_transmission_gathering_1970_2000.zip
- supplemental_phmsagas_gas_transmission_gathering_2001_2009 driver http registry licence None url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/zenodo/phmsagas/10.5281-zenodo.23296837/phmsagas_gas_transmission_gathering_2001_2009.zip
- supplemental_phmsagas_hazardous_liquid_2004_2009 driver http registry licence None url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/zenodo/phmsagas/10.5281-zenodo.23296837/phmsagas_hazardous_liquid_2004_2009.zip
- supplemental_phmsagas_hazardous_liquid_2010_present driver http registry licence None url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/zenodo/phmsagas/10.5281-zenodo.23296837/phmsagas_hazardous_liquid_2010_present.zip
- supplemental_phmsagas_liquefied_natural_gas_2010_present driver http registry licence None url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/zenodo/phmsagas/10.5281-zenodo.23296837/phmsagas_liquefied_natural_gas_2010_present.zip
- supplemental_phmsagas_reporting_regulated_gas_gathering_2022_present driver http registry licence None url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/zenodo/phmsagas/10.5281-zenodo.23296837/phmsagas_reporting_regulated_gas_gathering_2022_present.zip
- supplemental_phmsagas_underground_natural_gas_storage_2017_present driver http registry licence None url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/zenodo/phmsagas/10.5281-zenodo.23296837/phmsagas_underground_natural_gas_storage_2017_present.zip
- supplemental_usgs_uspvdb_v4_20260414 driver http registry licence None url https://www.sciencebase.gov/catalog/file/get/6671c479d34e84915adb7536?f=__disk__ed%2F7b%2F9c%2Fed7b9ce6abb1fc8430fbfe830f8ee58e870c6af3
- supplemental_uswtdb_decommissioned_v9_1_20260928 driver http registry licence None url https://eta-publications.lbl.gov/sites/default/files/2026-10/uswtdb_decommissioned_20260928.csv
- supplemental_usgs_wsa_data_tables driver http registry licence None url https://www.sciencebase.gov/catalog/file/get/608035dcd34e8564d6835790?f=__disk__2b%2Fed%2Fc1%2F2bedc12834473a8e758cb718a4ff50ba70a04c09
- supplemental_usgs_wsa_geographic_units_2017 driver http registry licence None url https://www.sciencebase.gov/catalog/file/get/608035dcd34e8564d6835790?f=__disk__c3%2Fee%2Ff2%2Fc3eef28d5943dd88b57523d7c82ac23ed453b538
- supplemental_usgs_wsa_metadata driver http registry licence None url https://www.sciencebase.gov/catalog/file/get/608035dcd34e8564d6835790?f=__disk__68%2Ff1%2Ffa%2F68f1fac9507421b3848b8b18a6ca5123b681d3de
- pudl_v2026_10_0 driver http registry licence cc-by-4.0 url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/v2026.10.0/
- pudl_v2026_10_0_gas_and_rus driver http registry licence cc-by-4.0 url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/v2026.10.0/
- pudl_v2026_10_0_phmsagas driver http registry licence cc-by-4.0 url https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/v2026.10.0/
- state_tx_puct_water_ccn driver http registry licence unknown url https://ftp.puc.texas.gov/public/puct-info/industry/water/utilities/PUCT_CCN_WATER_TSMS.zip
- state_tx_puct_sewer_ccn driver http registry licence unknown url https://ftp.puc.texas.gov/public/puct-info/industry/water/utilities/PUCT_CCN_SEWER_TSMS.zip
- federal_eia861_2025 driver http registry licence None url None
- federal_eia860_2025 driver http registry licence None url None
- federal_eia860m_sept2026 driver http registry licence None url None
- federal_ferc_cid_2026 driver http registry licence None url None
- federal_phmsa_gas_distribution_2025 driver http registry licence None url None
- federal_phmsa_gas_transmission_2025 driver http registry licence None url None
- federal_usgs_wsa_2017 driver http registry licence None url None
- federal_epa_npdes_icis driver http registry licence None url None
- federal_epa_npdes_outfalls driver http registry licence None url None
- state_wi_psc_water_utilities_2025 driver http registry licence None url None
- state_co_special_districts_all driver http registry licence None url None
- state_co_special_districts_water_sanitation driver http registry licence None url None
- state_co_special_districts_metro driver http registry licence None url None
- state_hi_wastewater_treatment_plants driver http registry licence None url None
- state_fl_psc_county_lookup driver http registry licence None url None
- state_mo_psc_utility_lookup driver http registry licence None url None
- reference_census_2025_counties driver http registry licence None url None
- reference_census_2025_states driver http registry licence None url None
- federal_usgs_uswtdb_v9_1 driver http registry licence unknown url https://energy.usgs.gov/uswtdb/assets/data/uswtdbCSV.zip
- federal_usgs_uspvdb_v4_0 driver http registry licence unknown url https://www.sciencebase.gov/catalog/file/get/6671c479d34e84915adb7536?f=__disk__dc%2Fa5%2F48%2Fdca548712009dd78533a58851d0be28b7489cfc6
- state_wi_psc_electric_territories driver http registry licence unknown url https://psc.wi.gov/SiteAssets/Maps/EL_PSCW_ServTerr.zip
- state_wi_psc_natural_gas_territories driver http registry licence unknown url https://psc.wi.gov/SiteAssets/Maps/NG_PSCW_ServTerr.zip
