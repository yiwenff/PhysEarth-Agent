"""Scaffold for Fig. 2f; UNVERIFIED because no Dome C CFM profile has been obtained.

Input: profile.csv with columns depth_top_m,thickness_m,density_kg_m3,temperature_k
(CFM output for Dome C, 2014-01-01; merge to ~1 cm to 1 m, ~10 cm to 5 m, semi-infinite below).
Perturbation assumed: rho' = rho * (1 + p * (1 - rho/917)), p in -0.3..0.3.
"""
import sys, numpy as np, csv
from smrt import make_snowpack, make_model, sensor_list
rows = list(csv.DictReader(open(sys.argv[1])))
th = [float(r["thickness_m"]) for r in rows]; th[-1] = 200.0
rho = np.array([float(r["density_kg_m3"]) for r in rows]); T = [float(r["temperature_k"]) for r in rows]
sensor = sensor_list.passive(18.7e9, 55)
model = make_model("iba", "dort", emmodel_options=dict(dense_snow_correction="auto"))
for p in np.linspace(-0.3, 0.3, 13):
    r = model.run(sensor, make_snowpack(th, "exponential", density=rho * (1 + p * (1 - rho / 917.0)),
                                        temperature=T, corr_length=[0.25e-3] * len(th)))
    print("%+.2f %.2f %.2f" % (p, float(r.TbV()), float(r.TbH())))
