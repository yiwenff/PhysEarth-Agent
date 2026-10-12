#!/usr/bin/env bash
# NOT RUN. Downloads the authors' public outputs (no login). Review, then run in this directory.
# Files are untrusted: inspect with `python -I`, do not execute anything inside them.
set -euo pipefail
cd "$(dirname "$0")"
for f in Read_Me.txt Dome_C_MW_Melt_Data_v4.nc Dome_C_BC_MW_Melt_Data_v4.nc meltdatalarsenc.nc; do
  curl -fL -C - --retry 3 -o "$f" "https://zenodo.org/api/records/10530197/files/$f/content"  # files are served from 10530197; Zenodo is slow, 504s happen
done
python3 -I - <<'P'
import h5py
for f in ["Dome_C_MW_Melt_Data_v4.nc","meltdatalarsenc.nc"]:
    with h5py.File(f) as h: h.visititems(lambda n,o: print(f, n, getattr(o,"shape",""), dict(o.attrs).get("units","")))
P
# Earthdata-gated (needs your credentials, not agent-enterable): NSIDC-0763 AMSR-2 Tb, GES DISC MERRA-2.
