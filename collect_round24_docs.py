"""Download FERC's source documentation and its public legacy data files."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from collect import ROOT, download
import json

SOURCES = [
 ('ferc/official/pumped_storage_licensed_20261006.pdf', 'https://www.ferc.gov/sites/default/files/2026-10/Licensed_PS_10.6.26.pdf'),
 ('ferc/official/pumped_storage_pending_licenses_20261006.pdf', 'https://www.ferc.gov/sites/default/files/2026-10/Pending_PS_License_10.6.26.pdf'),
 ('ferc/official/pumped_storage_issued_preliminary_permits_20261014.pdf', 'https://www.ferc.gov/sites/default/files/2026-10/Active_PS_Permit_10.14.26.pdf'),
 ('ferc/official/pumped_storage_pending_preliminary_permits_20261014.pdf', 'https://www.ferc.gov/sites/default/files/2026-10/Pending_PS_Permit_10.14.26.pdf'),
 ('documentation/usace_nid_data_dictionary_aug2023.pdf', 'https://usace-cwbi-prod-il2-nld2-docs.s3.us-gov-west-1.amazonaws.com/0f6b4388-dafb-4ae4-84b4-416ad30b08e5/NID%20Data%20Dictionary%20August%202023.pdf'),
 ('documentation/ferc_hydropower_projects_item.json', 'https://www.arcgis.com/sharing/rest/content/items/c95891254aa349389135752a137670c5?f=json'),
 ('documentation/ferc_hydropower_projects_service.json', 'https://services6.arcgis.com/j2rhFudpKDsF5x0m/arcgis/rest/services/Projects_PublicView/FeatureServer?f=json'),
 ('documentation/usace_nid_public_service.json', 'https://geospatial.sec.usace.army.mil/dls/rest/services/NID/National_Inventory_of_Dams_Public_Service/FeatureServer?f=json'),
 ('documentation/usace_nid_landing.html', 'https://nid.sec.usace.army.mil/nid/'),
 ('ferc/official/form714_2006_2020_csv_june2021.zip', 'https://ferc.gov/sites/default/files/2021-06/Form-714-csv-files-June-2021.zip'),
 ('ferc/official/ferc_cid_listing_aug2025.xlsx', 'https://www.ferc.gov/sites/default/files/2025-08/August_2025_CID.xlsx'),
 ('documentation/ferc_cid_listing_page.html', 'https://www.ferc.gov/media/ferc-cid-listing'),
 ('documentation/ferc_cid_data_2026_catalog.html', 'https://data.ferc.gov/company-registration/ferc-company-identifier-listing/'),
 ('documentation/ferc_form1_catalog.html', 'https://data.ferc.gov/ferc-form-no.-1-annual-report-of-major-electric-utilities'),
 ('documentation/ferc_natural_gas_forms.html', 'https://www.ferc.gov/industries-data/natural-gas/industry-forms'),
 ('documentation/ferc_form6_catalog.html', 'https://data.ferc.gov/ferc-form-no.-6-annual-report-of-oil-pipeline-companies'),
 ('documentation/ferc_service_company_forms.html', 'https://www.ferc.gov/filing-forms/service-companies-filing-forms'),
 ('documentation/ferc_form714_data.html', 'https://ferc.gov/industries-data/electric/general-information/electric-industry-forms/form-no-714-annual-electric/data'),
 ('documentation/ferc_eforms_refresh.html', 'https://www.ferc.gov/filing-forms/eforms-refresh'),
]

if __name__ == '__main__':
 rows = []
 with ThreadPoolExecutor(max_workers=4) as pool:
  for f in as_completed([pool.submit(download, source) for source in SOURCES]):
   row = f.result(); rows.append(row)
   print(row['status'], row['path'], row.get('error', row.get('bytes')), flush=True)
 (ROOT/'data'/'manifest_round24_docs.json').write_text(json.dumps(sorted(rows, key=lambda r:r['path']), indent=2), encoding='utf8')
