"""Level-R reference for Fig. 10c: REPLOT of the authors' published L_MW, not a recomputation.
Mean micrograinsize over 27 Oct-16 Dec 2013 (day 148..198 since 1 Jun 2013, 0-based) per pixel.
Run: python -I fig10c_replot.py   (reads ../data/meltdatalarsenc.nc)
"""
import pathlib, h5py, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
here = pathlib.Path(__file__).parent
with h5py.File(here.parent / "data" / "meltdatalarsenc.nc") as h:
    lat, lon = h["lat"][:], h["lon"][:]
    g = h["micrograinsize"][:] * 1e3  # mm
d0, d1 = 148, 198  # 2013-06-01 + 148 = 2013-10-27 ; +198 = 2013-12-16
m_all = np.nanmean(g[:, d0:d1 + 1], axis=1)
# polar stereographic, true scale at 71 S (EPSG:3031), spherical approximation (good to ~km)
R, phi_c = 6378137.0, np.radians(71)
rho = 2 * R * np.tan(np.pi / 4 - np.radians(-lat) / 2) * (1 + np.sin(phi_c)) / 2
x, y = rho * np.sin(np.radians(lon)), rho * np.cos(np.radians(lon))
fig, ax = plt.subplots(figsize=(5, 5))
s = ax.scatter(x / 1e3, y / 1e3, c=m_all, s=22, cmap="viridis", marker="s")
ax.set(aspect="equal", xlabel="x (km)", ylabel="y (km)", title="Fig. 10c replot, mean L_MW (mm)\n27 Oct-16 Dec 2013", )
fig.colorbar(s, label="L_MW (mm)"); fig.tight_layout(); fig.savefig(here / "fig10c_replot.png", dpi=150)
np.savetxt(here / "fig10c_replot.csv", np.c_[lat, lon, m_all], delimiter=",", header="lat,lon,L_MW_mm_mean", comments="")
# 91 of 447 pixels are NaN on every day in the file (Read_Me: "sites that show NaN have not been run"); micrograinsize is the 18V product, as in Fig. 10c
print("pixels", lat.size, "L_MW mm min/mean/max %.3f %.3f %.3f" % (np.nanmin(m_all), np.nanmean(m_all), np.nanmax(m_all)),
      "| lat range", lat.min(), lat.max(), "| nan pixels", int(np.isnan(m_all).sum()))
