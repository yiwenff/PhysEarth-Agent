# Dattler et al. 2024 (TC 18, 3613) — Fig. 2c, 2f, 10c: Claude Code alone vs Claude Code + PhysEarth MCP

Paper: https://doi.org/10.5194/tc-18-3613-2024. Data: https://doi.org/10.5281/zenodo.10529574
(the paper's reference list cites 10530197; both records list the same 17 files).

## 1. What each panel needs

| Panel | Content | Needs |
|---|---|---|
| 2c | Tb(19V, 19H) vs density, uniform snow, L_MW 0.25 mm, 265 K | SMRT-IBA, exponential microstructure, **dense-snow ice/air switch** |
| 2f | Tb vs density perturbation on the Dome C CFM profile, 1 Jan 2014, L_MW 0.25 mm | SMRT on a **multi-layer** profile + CFM density/temperature profile (75.10 S, 123.35 E) |
| 10c | Larsen C map of L_MW (19V), 27 Oct–16 Dec 2013, 12.5 km grid | AMSR-2 Tb (NSIDC), MERRA-2 forcing, CFM per pixel, multi-layer SMRT, secant inversion |

## 2. What PhysEarth-Agent has and lacks (audited 2026-10-10)

| Item | Status | Evidence |
|---|---|---|
| SMRT 1.5.1, IBA, exponential, tb_v/tb_h, sweeps over density/frequency/angle/thickness | **Has** | `catalog/models/bundled/smrt/model_card.yaml` |
| Single homogeneous layer only | **Limit** | adapter builds one layer (`snowpack.layers[0]`); card has no layer list → blocks 2f, 10c |
| `dense_snow_correction="auto"` (the 450 kg m-3 switch) | **Missing** | no `emmodel_options` in `adapter.py`; without it Tb is smooth (I measured +1 K/5 kg m-3 across 458) |
| Card says Tb "saturates within a few metres" | **Wrong at 18.7 GHz** | 0.25 mm, 300 kg m-3: 5 m→153.7 K, 10 m→206.3 K, 50 m→227.0 K; the card's 1 m default is badly off |
| Community Firn Model | **Missing** | not in `catalog/models/bundled` |
| MERRA-2 forcing, AMSR-2 L3 Tb, MOA | **Missing** | no data tools; all three need Earthdata login |
| Secant-method L_MW inversion | **Missing** (could be an approved analysis script) | `run_analysis_script` exists per memory notes |
| Paper in literature corpus | **No** (smrt-v1 only) | `catalog/knowledge/literature/` — and Dattler is never to be added together with authors' notebooks |

## 3. Can the missing pieces be obtained publicly?

| Piece | Source | Open? | Verdict |
|---|---|---|---|
| CFM code | github.com/UWGlaciology/CommunityFirnModel (MIT) | yes | install is feasible; Dome C 1 Jan 2014 profile still needs forcing |
| MERRA-2 precip + skin T | NASA GES DISC (M2T1NXFLX etc.) | Earthdata login | **user must supply credentials**; not enterable by an agent |
| AMSR-2 daily 12.5 km Tb | NSIDC-0763 (AU_SI12) | Earthdata login | same |
| MOA grain size (10a/b) | NSIDC-0593 | Earthdata login | not needed for 10c |
| Authors' outputs | Zenodo 10529574: 13 site `*_MW_Melt_Data_v4.nc` (~1 MB each, Dome C incl.) + `meltdatalarsenc.nc` (2.7 MB) | **no login** | **Downloaded and inspected 2026-10-10.** Dome C: daily series 2012-07..2019-06 (AMSR-2 and modeled 18H Tb, threshold, melt flag, L_MW 18H/18V). Larsen C: `micrograinsize` (m) and `melt_detection` for 447 pixels x 365 days from 1 Jun 2013. **No density/temperature profiles anywhere** → 2f is not recoverable from Zenodo. 10c *can* be replotted (`reference/fig10c_replot.py`) |
| Dattler analysis code | none found on GitHub search; paper has no code statement | — | the inversion must be re-implemented from Sect. 3.3 |
| Zenodo Read_Me.txt | in the record | — | open it before choosing the 10c route |

Realistic reproduction levels: **2c full**; **2f** = full only if the Dome C profile is rebuilt (CFM + MERRA-2, needs login); the Zenodo files do not contain it, so otherwise partial with a clearly labelled stand-in profile; **10c** = replot of authors' L_MW (level R) or full recompute (level F, multi-day effort, needs login).

## 4. Unknowns in the paper (both arms must state their assumptions)
- Incidence angle (assume 55°, AMSR-2), substrate, DORT streams, polydispersity K (not needed for 2c/2f since L_MW is given).
- 2f perturbation formula: "percentage × air volume fraction" — assumed rho' = rho·(1 + p·(1−rho/917)); check against the figure.
- Text refers to "Fig. 4d–f" for Dome C sensitivity, a typo for 2d–f.
- The text gives 18.7 GHz and 19 GHz for the same channel; use 18.7.

## 5. Expected outcomes (hypotheses to test, not results)
- **2c, Claude Code alone**: easy to get a smooth curve (`pip install smrt`); likely **misses the switch** unless it knows `dense_snow_correction`, and may use a thin layer. A silent-fidelity failure, which is the useful one.
- **2f, alone**: task-heavy: no CFM profile; likely invents a profile or stops. Good failure/honesty test.
- **10c, alone**: expected to fail or fall back to replotting Zenodo data; tests whether it states which.
- **MCP today**: 2c close but needs the adapter fix; 2f/10c blocked by capability gaps — the improvement backlog in section 7.

## 6. Protocol
1. Same model both arms: Sonnet 5.5. Same prompts (`prompts/`), fresh session each, no hints.
2. Arm A: plain Claude Code in an empty scratch dir, no PhysEarth MCP (`claude --strict-mcp-config`), internet allowed, pip allowed, **no Earthdata credentials** for either arm unless you decide to supply them to both.
3. Arm B: Claude Code with the physearth MCP installed (`integrations/claude-code/install.sh`), same dir rules. Run once in `PHYSEARTH_ROUTER=rules` mode.
4. Do not give either arm `reference/` or this README. Save transcripts, produced files and wall-time/tokens into `runs/{A,B}/{2c,2f,10c}/`.
5. Score with `rubric.md`. Note that `reference/` is the answer key for 2c only; 2f/10c have no verified numeric key until data is obtained.

## 7. MCP improvement backlog (what a failing Arm B should point at)
1. ~~Expose `dense_snow_correction`; correct the "saturates in a few metres" text.~~ **Done 2026-10-10** (card parameter `dense_snow_correction` none|auto, default none; thickness guidance now frequency-specific). **Arm B is therefore no longer the "before" state for 2c**: to capture the pre-fix MCP, run Arm B on the commit before this change (`git stash` the card/adapter edits or check out the parent).
2. Multi-layer snowpack input (list of thickness/density/temperature/corr_length) in the SMRT card.
3. A CFM adapter (or accept a CFM profile file) and a dataset tool for Zenodo/NSIDC that asks for credentials from the user.
4. An inversion/secant-method analysis template; add the paper to the literature corpus only if it is not used as evaluation material.
5. Honest capability report: the agent should say "2f/10c unavailable" before running (the Fig. 6 guided demo shows this pattern).

## 8. Findings from the Zenodo check (2026-10-10)
- Not in Zenodo: any CFM density/temperature profile, MERRA-2 forcing, or AMSR-2 Tb for Larsen C. Fig. 2f cannot be reproduced from public no-login data.
- Dome C on 2014-01-01 (index 548): AMSR-2 19H 173.8 K = modeled 173.80 K (the inversion converged), L_MW 19V 0.167 mm, 19H 0.217 mm; 19V mean over the record 0.176 mm (paper: 0.18). This is a consistency check on the *fitted* grain size, not the 0.25 mm used in Fig. 2f.
- Larsen C mean L_MW 27 Oct-16 Dec 2013: 0.29-0.50 mm over 356 pixels that were run (91 are NaN = not run, per Read_Me; `micrograinsize` is the 18V product), higher toward the upper-left of the plot (lower latitude). The paper reports weak correlation (r=0.34) with MOA, so the map shape is the check, not exact values.
- Unknown: whether the Larsen file's day axis starts on 2013-06-01 as its units say (assumed); the paper's colour scale for Fig. 10c.
