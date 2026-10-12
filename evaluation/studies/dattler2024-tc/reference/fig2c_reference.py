"""Reference for Dattler et al. 2024 (TC 18, 3613) Fig. 2c: Tb vs density, uniform snowpack.

Ground truth for scoring both arms. Run: .venv/bin/python -W ignore fig2c_reference.py
Config from the paper: SMRT, IBA, exponential microstructure, L_MW = 0.25 mm, T = 265 K,
18.7 GHz, 19V and 19H. Incidence angle (55 deg, the AMSR-2 value) and the semi-infinite
layer are NOT stated in the paper; they are assumptions recorded in the README.
The step near 458 kg/m3 only appears with dense_snow_correction="auto".
"""
import csv, pathlib
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from smrt import make_snowpack, make_model, sensor_list

out = pathlib.Path(__file__).parent
sensor = sensor_list.passive(18.7e9, 55)
rhos = np.arange(100, 801, 5.0)
rows = {}
for label, opts in {"with_switch": dict(dense_snow_correction="auto"), "default_no_switch": {}}.items():
    model = make_model("iba", "dort", emmodel_options=opts)
    tb = []
    for rho in rhos:
        sp = make_snowpack([200], "exponential", density=[rho], temperature=[265], corr_length=[0.25e-3])
        r = model.run(sensor, sp)
        tb.append((float(r.TbV()), float(r.TbH())))
    rows[label] = np.array(tb)

with open(out / "fig2c_reference.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["density_kg_m3", "tbv_switch", "tbh_switch", "tbv_noswitch", "tbh_noswitch"])
    for i, rho in enumerate(rhos):
        w.writerow([rho, *rows["with_switch"][i], *rows["default_no_switch"][i]])

fig, ax = plt.subplots(figsize=(5, 3.6))
ax.plot(rhos, rows["with_switch"][:, 0], c="C0", label="19V")
ax.plot(rhos, rows["with_switch"][:, 1], c="C1", label="19H")
ax.plot(rhos, rows["default_no_switch"][:, 0], c="C0", ls=":", lw=1, label="19V no switch")
ax.plot(rhos, rows["default_no_switch"][:, 1], c="C1", ls=":", lw=1, label="19H no switch")
ax.set(xlabel="Density (kg m$^{-3}$)", ylabel="Brightness temperature (K)", title="Fig. 2c reference (SMRT-IBA, 0.25 mm, 265 K)")
ax.legend(fontsize=7)
fig.tight_layout()
fig.savefig(out / "fig2c_reference.png", dpi=150)
i = int(np.argmax(np.abs(np.diff(rows["with_switch"][:, 0]))))
print("largest 19V step: %.1f K between %g and %g kg/m3" % (np.diff(rows["with_switch"][:, 0])[i], rhos[i], rhos[i + 1]))
