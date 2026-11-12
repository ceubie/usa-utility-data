# Independent review gates

Cole directed that each plan review gate be performed by a subagent. Record
the reviewed state and any required follow-through here; a review does not
make unreviewed source entries eligible for a build.

| Gate | Result | Required follow-through |
| --- | --- | --- |
| Source promotion 2026-11-12 | Independent review [c448bba5](c448bba5-7068-4eab-8d48-baeb633e47b9). D1 opted in none. D2 keeps the three gas name tiers uncalibrated. Eleven sources were set back to draft and their declarations were kept. Approved service areas and the checked facility inventories stay reviewed. Sources the reviewer did not check were not given a new approval. | Do not build a refused source. Do not treat an unchecked promotion as approved by this gate. |
| Scope correction 2026-11-12: HIFLD electric and Iowa | Independent review [acfb5845](acfb5845-1e59-4123-948d-e61d1e244809). The promotion gate had set back two sources that the WP7 build already read. Their restoration was approved after these fixes. HIFLD electric now maps `TYPE` to a role: two marketer types are wholesale, the community choice aggregator is review_required, and the other seven types are retail. A utility whose bundled-plus-delivery sales exceed 2,500 MWh per customer in every measured year of the last three report years is never given a best area; on the saved data that withholds 11 gold territories, including WAPA, Bonneville, and TVA. Iowa's one null geometry (OBJECTID 1170) is rejected with reason `empty_geometry`, and electric layer rejects are now saved in `electric_boundary_rejects.parquet`. The boundary cache signature now includes input file hashes. The documentation edits were refused and then corrected. | The WP2 follow-throughs "do not mark a third-party compilation source reviewed" and "do not assign a retail role to a compilation" are overridden for `electric_retail_territories_hifld` only. It is read at `federal_modeled` authority with `footprint_verified` false, below utility, state regulator, and federal-submitted boundaries. The direct-service limit and window are uncalibrated starting values. Known misses: City of Escondido (5969), Philadelphia Authority for Industrial Development (61353), and TDX North Slope (19277), which have very few customers on a very large polygon. University of Illinois (19528) and Trinita Power (67636) are listed on one measured year. The 12 Canadian HIFLD features stay in the review queue every release. Release 2026Q4.1 was built before these rules; they take effect from 2026Q4.2. |
| Licence audit 2026-11-12 | Independent review [7087796b](7087796b-87fc-4154-bf07-89730f2d64b1). State of Michigan was not accepted as the grantor. Reclamation, six EIA Atlas layers, and the Colorado Platts layer are `internal_or_no_redistribution` and internal. Utah electric is `cc-by-4.0` and shareable. Other re-fetched sources with no grant stay `unknown` and internal. Michigan, the Illinois broadband layer, EPA community-water boundaries, and EPA sewersheds were left unchanged. | Do not mark Michigan shareable. Do not add MIT or CC BY-SA to the vocabulary. |
| Gold county coverage contracts | The three files in `contracts/gold` copy the water county-coverage columns already used by the approved water release. No new column was added. They were not checked against release 2026Q4.1 because that release does not contain the sector tables. | Run the gold contract check after 2026Q4.2 writes the three county coverage files. |
| WP1 contracts and checks | Approved after corrections to false path matches, strict validation, GeoParquet checks and the baseline. | Before WP6, provide inspection and narrowly scoped reviewed exceptions for ambiguous path candidates. |
| WP2 registry schema and first 20 water sources | Approved after correcting identifiers, unassigned areas, licence restrictions and geometry representation. | Complete the remaining source reviews; enforce identifier, unnamed-feature, licence and representation policies in WP4 and later products. |
| WP2 EPA archive declarations and snapshot checks | Approved after adding CSV and geospatial validation, archived-layer counts, copied-tree revalidation and final checksum checks. | Run a real freeze only after every source is reviewed and all collection files have a disposition. |
| WP2 saved-attribute validation | Approved after rejecting case-only field names, unmapped coded values including numeric zero, metadata-only review, and page files that are nested or differ in case from the snapshot list. | Do not declare Texas TWDB `ObjectId` or `ObjectID` until the metadata and saved features use the same spelling. |
| WP2 additional water declarations | Approved for Lee County water, DC Water pressure zones, and the Caledonia not-serviced water district. Refusals for Collier, Tioga, Texas TWDB, EPA noncommunity v1.1, West Virginia IJDC, and West Maui stay in the source notes. | Do not promote a service area while provider identity, authority, or boundary method is unresolved. |
| WP2 unambiguous non-water declarations | Approved after correcting the Michigan nuclear operating-status note and the USVI power facility-type note. Twenty-three sources with one clear identity and an explicit role were reviewed. | Do not mark a mixed, unnamed, empty-geometry, or third-party compilation source reviewed. Do not freeze while drafts remain. |
| WP2 facility and out-of-scope declarations | Approved after correcting the DC Water facility subtype note. Seventeen sources were reviewed. Facility inventories, pipeline networks, voice territories, drainage districts, and county solar totals were not given a retail role. | Keep mixed, unnamed, historical, and county-compiled service areas unreviewed. Do not freeze while drafts remain. |
| WP2 regulator areas and facility inventories | Approved after correcting the FERC surrender-order note, the Maui pump-station owner codes, and the South Dakota effective-date note. Seventeen sources were reviewed. | Do not review a service area when the saved attributes lack a provider name, mix sectors, or show a historical or estimated boundary. Do not freeze while drafts remain. |
| WP2 installations, networks, and town associations | Approved after correcting the New Jersey behind-the-meter geometry and naming the Metro sewer-device types from the subtype domains. Fifteen sources were reviewed. | Do not assign a retail role when confirmation, order codes, or publishing authority is unresolved. Do not freeze while drafts remain. |
| WP2 pipes, structures, and the dam inventory | Approved after recording the exact EIA transmission type strings. Fourteen sources were reviewed as networks, facilities, township associations, or a reference dam inventory. | Do not assign a retail role to a compilation, an unmapped order code, or a layer with blank provider names. Do not freeze while drafts remain. |
| WP2 Portland assets and remaining draft patterns | Eleven Portland layers were approved. Draft-pattern counts were corrected through the three-review cap. Two Arizona DEMA layers are counted under blank provider name because 16 names are blank, which comes before compilation. | Do not mark the 223 counted drafts reviewed. Do not freeze while drafts remain. |
| WP2 source review stopped | Recorded 2026-11-11. Review stopped on purpose at 343 sources: 120 reviewed and 223 drafts. Water is 36 reviewed and 48 draft. | Do not guess roles and do not mark the 223 drafts reviewed. Silver, Core, and Gold may consume reviewed sources only. The snapshot carries the 223 drafts as not buildable. Unassigned collection files still fail the freeze. |
| WP4 non-community replacement decision | Pending independent review. | Compare the newer archive and older source before choosing a replacement. |
| WP5 thresholds and sampled matches | Approved 2026-11-11. Independent review of the done-when checks, the review queue, and 50 sampled matches found no defects. The 200-pair sample was not hand-labelled, so the starting thresholds were not changed. | Do not change name 95, name-with-overlap 80, or IoU 0.5 until a measured 200-pair sample shows auto-accepted precision below 98 percent, and record that change as uncalibrated. |
| WP6 first release | Approved 2026-11-11. Independent review recomputed inactive coverage, shares at or below 1, Travis County (84 served systems), the population-within-25% table, and the header-only truth file. No defects. | Do not treat unknown or restricted licences as shareable. Do not claim non-modeled coverage while best-area representation is mixed or unknown. Texas CCN and TWDB remain draft. |
| WP7 electric sector | Built 2026-11-11 beside the water release. Independent review of the acceptance cases, the bundled-versus-energy sales rule, the HIFLD mailing-state rule, and draft-source exclusion found no defects. | Electric overlap 0.5 and name similarity 70 are starting values and are not calibrated. Do not add rows to `registry/truth/electric.csv`. Do not read draft or empty-geometry sources. `out_sec10k__parents_and_subsidiaries` is experimental through 2023 and is not complete. Michigan and Florida best-area polygon area divided by land area is 1.371 and 1.311 because the polygons include water; divided by the state outline those ratios are 0.802 and 0.985. |
| WP8 wastewater and natural gas | Built 2026-11-11 beside the water release. Independent review of the federal-link share, the 50-zone sample, the total-flow rule, and draft-source exclusion found no defects. | Wastewater sewershed overlap 0.5 is a starting value and is not calibrated. Do not add verified truth rows. Do not read draft or empty-geometry sources. CWNS flow uses the Total Flow row. A state or local zone links only when one sewershed covers at least half the zone, or the zone contains exactly one treatment plant. Gas name matches stay inside one state. `office_state` is not the service state. RUS tables were not downloaded. |
| WP9 cross-sector organizations, facilities, and networks | Built 2026-11-11 beside the existing sectors. Independent review of the facility-type vocabulary, the Michigan wind unit sum, the parent-file labeling, and draft-source exclusion found no defects. | Facility distance 500 m and name similarity 85 are starting values and are not calibrated. Do not mark `review/parents_top100.csv` hand-verified. `out_sec10k__parents_and_subsidiaries` stays experimental and incomplete through 2023-10-01. A cross-sector owner link requires the same `govid`. Michigan wind published capacity is the sum of turbine ratings, 3748.58 MW across 38 projects. The repeated project-capacity field sums to 3747.98 MW and is rejected. Stoney Corners is 60.6 MW of turbine ratings against a 60 MW plant total. Do not read draft or empty-geometry sources. |
| WP11 ontology and query language | Approved 2026-11-11. Independent review of the classes, links, servesCounty rule, and Travis County sets found no defects. Fuseki answered the Travis County water query with the same 84 systems as Gold. SPARQL is the query language for WP12. | Do not add Cypher. Do not put population share on servesCounty. SEC parent rows stay experimental and incomplete and are not verified. |
| WP13 D3 workbench | Checked 2026-11-11. `GET /api/geo/who-serves` takes `lat`, then `lon`. At latitude 38.9072 and longitude -77.0369, water returns `SYS_PWS_DC0000002` (D.C. Water and Sewer Authority) and electric returns `SYS_EIA_15270` (Potomac Electric Power Co). The frontend `whoServes(38.9072, -77.0369, "electric")` function returned that same electric system id as the HTTP response. Frontend code was left unchanged. Independent review 8fbfc998-65e2-4010-96a8-929334b06c94 had already found no frontend defects. | Live Ask remains unmet. `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, and `AZURE_OPENAI_API_KEY` are unset. |
| WP14 evaluation and hand-over | Measured 2026-11-11. The bank has 73 questions: 20 plan, 14 agent example, 39 release. 68 ran and passed. 3 stayed blocked because they need the Azure model. 2 stayed blocked because the release does not contain the fact (Aqua Texas certificated area; North St. Paul as one system). Through the local API, p50 was 16.4 ms and p95 was 676 ms. Aggregate p50 was 35.5 ms and aggregate p95 was 5183 ms, which is over 5 seconds. The same SPARQL adapter then timed those nine aggregate queries on Fuseki and on QLever. All nine counts matched. Fuseki aggregate p95 was 5191 ms. QLever aggregate p95 was 43.6 ms. The QLever server was stopped after that timing. [Review WP14](88e599ff-32c5-4467-8f30-47c3185e999a) found three defects in the runbook and the Kelly Lane check. [Re-review WP14](aeffbef3-85d9-4631-ac5f-c06680e9e8f1) found those fixes held and no new defect. | Cole sets the bar for wider use. Colleague questions were not collected. Live Ask remains unmet because the three Azure settings are unset. |

The approved PWSID exception and the evidence behind it are in
`registry/vocab/pwsid_policy.yaml` and `registry/pwsid_format_audit.json`.
Future transformation acceptance cases are in `docs/wp4-acceptance.md`.

## Source promotion gate (2026-11-12)

Independent review c448bba5-7068-4eab-8d48-baeb633e47b9 checked declarations
against saved features. D1 opted in no source. D2 keeps the three gas name-key
tiers and leaves `GAS_NAME_KEYS_CALIBRATED` false. The seven step-1 drafts stay
draft.

Refused, and set back to `reviewed: false` with the declaration kept:

- `indiana_electric_territories_iurc`: `utilityname` and `utilitytype` are null on 12 of 130.
- `texas_water_service_areas_twdb`: 31 features have empty geometry under an active retail role.
- `iowa_electric_service_areas_iuc`: geometry is null on 1 of 1,361. Superseded by the scope-correction gate: the null feature is rejected with a reason and the source is reviewed again.
- `state_ny_gas_territories`: one polygon has `comp_full` None, `comp_short` None, and `comp_id` 0.
- `electric_retail_territories_hifld`: mixed utility types, including a wholesale marketer, and 12 Canadian mailing countries, under one retail role. An earlier gate refused the compilation. Superseded by the scope-correction gate: `TYPE` now sets the role, and direct-service suppliers never get a best area.
- `natural_gas_ldc_territories_hifld`: `POSREL` is third party or notional. An earlier gate refused the compilation.
- `california_electric_iou_pou_load_serving_cec` and `california_natural_gas_cec`: earlier compilation refusals still hold. Gas `CATEGORY` is null on 1 of 13.
- `new_jersey_gas_territories_dep`: earlier compilation refusal still holds.
- `utah_electric_service_areas_ugrc`: 17 polygons say another provider serves part of the area, and an earlier gate classed the layer historical.
- `vermont_electric_service_areas_psd`: an earlier gate classed the 2015 layer historical.

Approved service areas: Texas water and sewer CCN, Minnesota electric, New York electric, Wisconsin electric and gas, Alabama Power territory, Alaska electric, gas, and sewer areas, California CPUC electric, gas, and voice, Colorado Metro members, Lee County water, Kentucky gas, Michigan electric and gas, Clean Water Services pump-station boundaries, South Dakota electric, Washington UTC gas, and both Caledonia not-serviced districts. Also approved: USPVDB, USWTDB, and five Reclamation facility layers (conveyance, dams, hydropower, pumping plants, reservoirs). `federal_epa_sewersheds_v1_3` was not checked. Other newly promoted facilities and networks were not checked and are not approved by this gate.

## WP2 review stop (2026-11-11)

Cole stopped WP2 source review on purpose. The registry is 343 sources: 120
reviewed and 223 drafts. Water is 36 reviewed and 48 draft. The 223 drafts stay
unreviewed. Roles are not guessed to shrink that count, and none of these drafts
are marked reviewed.

The pattern table below is the verified partition. Each draft is in exactly one
bucket: 14 attributes-only or no geometry, 28 planning or historical, 40 blank
provider name, 11 unmapped certificate or status code, 26 compilation whose
publisher does not establish authority, and 92 anything else. Those counts are
after the 2026-11-12 gate removed eight promoted ids and four ids reviewed by
the WP7 and WP8 builds. The 14
attributes-only layers are the spatial layers whose saved features have no
geometry. They were skipped during the 2026-11-11 review. Cole's instruction of
2026-11-12 supersedes the earlier do-not-re-download rule: `utilitydata refresh
--source` may collect one layer into the next snapshot. The re-collection stays
draft until reviewed and does not enter release 2026Q4.2. Arizona DEMA and
`arizona_electric_utility_areas_dema_source` stay under blank provider name:
`NAME` is a single space on 16 of 75 features.

Eleven Portland layers are reviewed. These three Portland layers stay draft:
`oregon_portland_connections`, `oregon_portland_lateral_cleanouts`, and
`oregon_portland_vaults_ponds_encasements`. A fourth Portland draft,
`oregon_portland_non_bes_ownership`, is under anything else.

This decision supersedes the earlier review follow-through that said not to
freeze while drafts remain. Downstream Silver, Core, and Gold builds may consume
reviewed sources only. The 223 drafts are carried in the snapshot as not
buildable. Their manifest status is `draft`, or `no_geometry` for the 14
empty-geometry spatial layers. Neither status is a reviewed build input.
`collected`, `partial_geometry`, and `nonspatial` are the only buildable
statuses, and only reviewed sources receive them. The two Massachusetts
unlocated tables stay reviewed nonspatial tables, not failed downloads. A
collection file that is not assigned to a source and is not listed in
`registry/unused.yaml` still fails the freeze.

WP3 adds Census reference entries with `storage: home`. They are not part of
the 223 utility drafts, and they are not marked reviewed. The reference build
reads those data-root paths. Silver, Core, and Gold still may consume reviewed
utility sources only.

## Remaining draft patterns

After the Portland asset review, 223 drafts remained. The 2026-11-12 promotion gate removed eight promoted ids from the anything-else list. Four more ids were reviewed by the WP7 and WP8 builds and are removed: HIFLD electric from compilation, and EIA-176, CWNS 2022, and EPA sewersheds v1.3 from anything else. The partition is now 211, and `tests/test_registry.py` checks that it lists every collection draft exactly once. Reference downloads with `storage: home` are not in it. Each remaining draft is counted once.
The first matching pattern wins, in this order: attributes-only or no geometry,
planning or historical, blank provider name, unmapped certificate or status code,
compilation whose publisher does not establish authority, then anything else.
The first five patterns use saved features or a source id that itself records a
2004 or 2017 survey. Anything else is the remainder: catalog seeds, archive
manifests, repeated ownership views, mixed-sector layers, and geocoder results
that were not given one of those five blockers. Apart from the twelve ids
removed above, no draft was marked reviewed; none of the 211 listed below is.

| Pattern | Drafts |
| --- | --- |
| Attributes-only or no geometry | 14 |
| Planning or historical | 28 |
| Blank provider name | 40 |
| Unmapped certificate or status code | 11 |
| Compilation whose publisher does not establish authority | 26 |
| Anything else | 92 |

Saved-feature checks moved drafts to an earlier pattern. Massachusetts community and nontransient water stay under unmapped confirmation status: every feature has a provider name, and `SERVCECONF` is Confirmed or Unconfirmed. Their notes also say that field does not identify small-circle placeholders. Delaware water, Mississippi water, and both West Virginia served layers have blank provider names, so that pattern wins over unmapped status codes. The Frederick sewer plans and the Metropolitan Council long-term and MUSA layers are planning stages. `MC_PLANT` is Y, N, or 2, not a utility name. The five Clean Water Services basins name plant basins rather than a utility. Colorado electric areas are a 2009 survey on all 57 features. Arizona DEMA and its source copy stay under blank provider name because `NAME` is a single space on 16 of 75 features, so that pattern wins over compilation. Seven layers with a provider name on every feature are compilations whose publisher does not establish each utility's authority: Pima water outside Tucson, California other load-serving entities, the HIFLD gas territories, New Jersey sewer service areas, Oregon electric and gas incentive areas, Horry water and sewer areas, and King County sewer providers. The HIFLD electric retail territories were in this group and are now reviewed under the scope-correction gate. New Jersey facility names are present, including TBD on 5, and the plan-agency field is blank on 23. Horry includes two polygons that name a water provider and a sewer provider together. The six counts are 14, 28, 40, 11, 26, and 92.

## attributes_only_or_no_geometry 14
colorado_metro_water_recovery_sewer_lines
south_carolina_conway_gravity_sewers
south_carolina_conway_sewer_force_mains
south_carolina_conway_water_lines
south_carolina_greer_electric_service_areas
south_carolina_greer_gas_service_areas
south_carolina_greer_sewer_service_areas
south_carolina_greer_water_service_areas
wyoming_laramie_electric_certificated_areas
wyoming_laramie_gas_certificated_areas
wyoming_laramie_high_west_power_lines
wyoming_laramie_telephone_certificated_areas
wyoming_laramie_wapa_power_lines
wyoming_laramie_wapa_substations
## planning_or_historical 28
colorado_electric_areas_cdot
florida_sfwmd_water_future
illinois_electric_territories_broadband_office
maine_electric_service_areas_puc_2020
maryland_frederick_city_sewer_service_plan
maryland_frederick_city_water_service_plan
maryland_frederick_county_sewer_service_plan
maryland_frederick_county_water_service_plan
minnesota_metc_long_term_wastewater_areas
minnesota_metc_musa_2030
minnesota_metc_musa_2040
minnesota_metc_musa_2050
minnesota_metc_musa_composite
minnesota_metc_musa_undesignated_reserve
north_carolina_sewer_current_2004
north_carolina_sewer_future_2004
north_carolina_stormwater_2004
north_carolina_water_current_2004
north_carolina_water_future_2004
tennessee_gallatin_water_service_areas
usbr_assets_under_construction
utah_electric_service_areas_ugrc
vermont_electric_service_areas_psd
washington_drinking_water_areas_doh
wisconsin_natural_gas_psc_2016
wisconsin_sewrpc_regional_sewer_plans_2025
wisconsin_washington_county_planned_sewer_areas
federal_usgs_wsa_2017
## blank_provider_name 40
arizona_electric_utility_areas_dema
arizona_electric_utility_areas_dema_source
arizona_pima_wastewater_service_areas
dc_electric_substations_1999_dcgis
delaware_water_certificated_areas_psc
florida_collier_wastewater_service_area
florida_collier_water_service_area
georgia_fulton_wastewater_pump_stations
hawaii_maui_sewer_lateral_lines
indiana_electric_territories_iurc
maryland_hagerstown_electric_service_area
mississippi_electric_certificated_areas_psc
mississippi_gas_certificated_areas_psc
mississippi_sewer_certificated_areas_psc
mississippi_telephone_certificated_areas_psc
mississippi_water_certificated_areas_psc
new_jersey_electric_territories_dep
new_jersey_utility_line_features_dep
new_jersey_wreck_pond_sanitary_sewer_lines_dep
new_york_tioga_sewer_service_areas
new_york_tioga_water_service_areas
north_carolina_greensboro_water_sewer_service_area
ohio_electric_certified_territories_puco
ohio_electric_overlap_areas_puco
oregon_clean_water_services_district_border
oregon_clean_water_services_treatment_plant_basins
oregon_portland_connections
oregon_portland_lateral_cleanouts
south_carolina_conway_utility_service_area
tennessee_gallatin_cumberland_electric_area
tennessee_gallatin_gas_service_area
tennessee_gallatin_nes_electric_area
tennessee_gallatin_sewer_service_area
vermont_electric_substations_psd
virginia_state_sewer_area_vdh_deq_2019
west_virginia_sewer_served_ijdc
west_virginia_water_served_ijdc
wisconsin_caledonia_sewer_service_area
wisconsin_caledonia_water_service_area
wyoming_laramie_wapa_microwave_towers
## unmapped_certificate_or_status 11
arizona_water_service_areas_adhs_2022
delaware_wastewater_certificated_areas_psc
florida_sfwmd_water_current
florida_sjrwmd_water_service_areas
massachusetts_sewer_nonpotw_massdep
massachusetts_sewer_potw_massdep
massachusetts_water_community_massdep
massachusetts_water_nontransient_massdep
national_epa_noncommunity_water_service_areas_v1_1
new_mexico_public_water_system_areas_ose
wisconsin_dane_carpc_sewer_service_areas
## compilation_authority 26
arizona_pima_water_provider_areas_except_tucson
california_electric_other_load_serving_cec
natural_gas_ldc_territories_hifld
new_jersey_sewer_service_areas_dep
oregon_electric_gas_areas_odoe
south_carolina_horry_water_sewer_areas
washington_king_county_sewer_service_providers
florida_broward_water_provider_areas
arizona_pima_electric_service_areas
arkansas_electric_territories_gis
california_electric_iou_pou_load_serving_cec
california_natural_gas_cec
connecticut_connected_sewer_areas
florida_broward_sewer_provider_areas
florida_orange_county_electric_service_areas
georgia_fulton_water_sewer_service_areas
hawaii_maui_west_water_service_areas
kentucky_electric_service_areas_dgi
louisiana_east_baton_rouge_electric_areas
nevada_electric_service_areas_ndom
new_jersey_gas_territories_dep
new_york_tioga_gas_service_areas
south_carolina_summerville_cpw_water_service_area
utah_culinary_water_areas_dwre
wisconsin_electric_municipal_psc
wisconsin_electric_psc
## other 92
supplemental_alabama_power_service_territory
supplemental_pws_community
supplemental_pws_nontransient_noncommunity
supplemental_pws_transient_noncommunity
supplemental_eia861m_2026_sales_ultimate_customers
supplemental_eia861m_2026_net_metering
supplemental_eia861m_2026_non_net_metering
supplemental_eia861m_2026_small_scale_solar
supplemental_eia923_2025
supplemental_eia923_2026_monthly
supplemental_epa_sewer_systems
supplemental_epa_sdwa_system_search
supplemental_ferc_active_hydro_exemptions_20261109
supplemental_ferc_active_hydro_licenses_20261109
supplemental_ferc_cid_listing_aug2025
supplemental_cesspool_prioritization
supplemental_offshore_sewer_lines
supplemental_onsite_sewage_systems
supplemental_metc_musa_planning
supplemental_metc_sanitary_sewersheds_public
supplemental_metc_sewer_interceptors_public
supplemental_metc_wastewater_treatment_plants_public
supplemental_electricity_tables_2024_deq
supplemental_natural_gas_tables_2024_deq
supplemental_public_water_purveyors_2026_geodatabase
supplemental_public_water_purveyors_2026_shapefile
supplemental_datapackage
supplemental_phmsagas_gas_distribution_1970_2003
supplemental_phmsagas_gas_distribution_2004_2009
supplemental_phmsagas_gas_transmission_gathering_1970_2000
supplemental_phmsagas_gas_transmission_gathering_2001_2009
supplemental_phmsagas_hazardous_liquid_2004_2009
supplemental_phmsagas_hazardous_liquid_2010_present
supplemental_phmsagas_liquefied_natural_gas_2010_present
supplemental_phmsagas_reporting_regulated_gas_gathering_2022_present
supplemental_phmsagas_underground_natural_gas_storage_2017_present
supplemental_usgs_uspvdb_v4_20260414
supplemental_uswtdb_decommissioned_v9_1_20260928
supplemental_usgs_wsa_data_tables
supplemental_usgs_wsa_geographic_units_2017
supplemental_usgs_wsa_metadata
california_broadband_territories_cpuc_2023
connecticut_exclusive_water_service_area_changes_dph
georgia_fulton_wastewater_pipes
georgia_fulton_wastewater_treatment_plants
georgia_fulton_water_hydrants
georgia_fulton_water_pipes
hawaii_maui_recycled_water_customers
kentucky_electric_service_boundary_lines_dgi
michigan_distributed_solar_2024_mpsc
minnesota_metc_current_sewersheds
minnesota_metc_sewer_interceptors
national_epa_noncommunity_water_service_centers_v1_1
new_jersey_hydropower_facilities_dep
oregon_clean_water_services_sewer_maintenance
oregon_eugene_waste_basin_studies
oregon_eugene_waste_system_plan
oregon_eugene_wastewater_basins
oregon_portland_non_bes_ownership
oregon_portland_vaults_ponds_encasements
south_carolina_summerville_cpw_sewer_service_area
texas_water_service_areas_twdb
usbr_water_treatment_facilities
vermont_gmp_distribution_lines_vcgi
vermont_gmp_poles_vcgi
vermont_gmp_underground_structures_vcgi
vermont_vec_distribution_lines_vcgi
vermont_vec_poles_vcgi
vermont_wec_distribution_lines_psd
vermont_wec_poles_psd
virginia_fairfax_sewer_service_areas
west_virginia_sewer_lines_ijdc
west_virginia_water_lines_ijdc
wisconsin_dane_carpc_sewer_service_amendments
federal_eia861_2025
federal_eia860_2025
federal_eia860m_sept2026
federal_ferc_cid_2026
federal_phmsa_gas_distribution_2025
federal_phmsa_gas_transmission_2025
federal_epa_npdes_icis
federal_epa_npdes_outfalls
state_ny_gas_territories
state_wi_psc_water_utilities_2025
state_co_special_districts_all
state_co_special_districts_water_sanitation
state_co_special_districts_metro
state_hi_wastewater_treatment_plants
state_fl_psc_county_lookup
state_mo_psc_utility_lookup
reference_census_2025_counties
reference_census_2025_states
