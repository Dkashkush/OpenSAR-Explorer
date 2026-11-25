# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Module 2, Forests & Biomass: forest biomass and deforestation from NISAR L-band backscatter (L2 GCOV).

* ``gcov``: find NISAR GCOV images on ASF and read HH/HV backscatter over an area (remote, partial reads)
* ``reference``: independent forest data (ESA WorldCover, Hansen Global Forest Change, ESA CCI Biomass)
* ``analysis``: HV -> above-ground biomass calibration with a saturation limit and held-out validation;
  forest loss since 2021, new clearing during the NISAR period, and deforestation zones
* ``pipeline``: runs it all for one area and writes maps, tables and a report
"""
