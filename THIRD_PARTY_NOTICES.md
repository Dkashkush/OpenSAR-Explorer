# Third-party notices

OpenSAR Explorer is Copyright © 2026 Deepa Kumari, all rights reserved (see [LICENSE](LICENSE)). It relies on the
data and software below, which are **not** covered by that copyright and remain under their owners' terms.

## Data

| Data | Owner and terms | Credit used in reports |
|---|---|---|
| NISAR L2 GUNW interferograms | NASA/ISRO; distributed by the ASF DAAC; free and open | "NISAR data: NASA/ISRO, distributed by the ASF DAAC" |
| NISAR L2 GCOV backscatter | NASA/ISRO; distributed by the ASF DAAC; free and open | "NISAR L2 GCOV data: NASA/ISRO, distributed by the ASF DAAC" |
| ESA WorldCover 10 m 2021 v200 | © ESA WorldCover project 2021, contains modified Copernicus Sentinel data (2021) processed by the ESA WorldCover consortium; CC BY 4.0 | Zanaga, D. et al. (2022), doi:10.5281/zenodo.7254221 |
| Global Forest Change 2000-2025 v1.13 | University of Maryland (Hansen et al.); CC BY 4.0 | "Source: Hansen/UMD/Google/USGS/NASA"; Hansen, M. C. et al. (2013), *Science* 342, 850-853 |
| ESA CCI Biomass v7.0 | ESA Climate Change Initiative, Biomass_cci (Santoro & Cartus); NERC EDS CEDA; ESA CCI data policy | dataset citation in each report |
| Sentinel-1 data | European Union, Copernicus programme (ESA); free, full and open | "Contains modified Copernicus Sentinel data" |
| ARIA S1 GUNW and OPERA DISP-S1 | NASA JPL; distributed by the ASF DAAC; free and open | "Sentinel-1 interferometric products (ARIA, OPERA (NASA JPL) or HyP3 (ASF)) distributed by the ASF DAAC" |
| ASF HyP3 on-demand interferograms | Processed by ASF's HyP3 service from Copernicus Sentinel-1 data | as above |
| LiCSAR interferograms | COMET (UK Centre for the Observation and Modelling of Earthquakes, Volcanoes and Tectonics); see the provider's licence | Lazecký, M., et al. (2020), *Remote Sensing*, 12(15), 2430, https://doi.org/10.3390/rs12152430 |
| EGMS Ortho maps | European Union, Copernicus Land Monitoring Service; free, full and open | "European Ground Motion Service (EGMS), Copernicus Land Monitoring Service" |
| GNSS time series | Nevada Geodetic Laboratory | Blewitt, G., Hammond, W. C., & Kreemer, C. (2018), *Eos*, 99 |
| Place search | OpenStreetMap Nominatim (data © OpenStreetMap contributors, ODbL); used under its usage policy (one request per search, identified by name) | "© OpenStreetMap contributors" |
| Map backgrounds | OpenStreetMap (ODbL) and Esri World Imagery (Esri and its data providers, Esri terms of use) | shown on every map |
| Published values (examples) | The cited papers; short factual values quoted with full citations | full citation in each report |

## Software

These packages are installed alongside OpenSAR Explorer (they are not part of this repository) and are used
under their own open-source licences, as stated in their package metadata (October 2026):

| Package | Licence |
|---|---|
| numpy | BSD-3-Clause (and bundled 0BSD, MIT, Zlib, CC0-1.0 parts) |
| scipy | BSD |
| xarray | Apache-2.0 |
| h5py | BSD-3-Clause |
| netCDF4 | MIT |
| rasterio | BSD |
| rioxarray | Apache |
| pyproj | MIT |
| shapely | BSD-3-Clause |
| matplotlib | Matplotlib license (PSF-based) |
| PyYAML | MIT |
| asf_search | BSD |
| fsspec | BSD-3-Clause |
| aiohttp | Apache-2.0 and MIT |
| requests | Apache-2.0 |
| streamlit | Apache-2.0 |
| folium, branca | MIT |
| streamlit-folium | see its project page (not stated in the installed package) |

Product reading follows the published conventions of MintPy (Yunjun et al., 2019) and opera-utils.

## Fonts

The web app serves two fonts from `static/fonts/` (only the Latin subsets, unchanged), so visitors' browsers do not
contact a font service:

| Font | Copyright and licence |
|---|---|
| Inter | Copyright 2020 The Inter Project Authors (https://github.com/rsms/inter); SIL Open Font License 1.1 (`static/fonts/Inter-OFL.txt`) |
| Plus Jakarta Sans | Copyright 2020 The Plus Jakarta Sans Project Authors (https://github.com/tokotype/PlusJakartaSans); SIL Open Font License 1.1 (`static/fonts/PlusJakartaSans-OFL.txt`) |
