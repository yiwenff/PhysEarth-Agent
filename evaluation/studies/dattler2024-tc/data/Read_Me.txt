This repository contains 13 Antarctic point locations and their associated melt detection by the Hybrid Method. There are 14 files as 2 of the files are run using bias corrected (BC) MERRA-2 skin temperature forcing. 

Variables are labeled as follows:

p_exp_18H: Exponential correlation length as derived from 18H AMSR-2 (mm)
p_exp_18V: Exponential correlation length as derived from 18V AMSR-2 (mm)
sigma_p_exp_18H: 31-day mean running standard deviation of the exponential correlation length for 18H AMSR-2 (mm)
TB_18H_modeled: Modelled dry snow brightness temperature for 18H (K)
TB_18H_amsr2: AMSR-2 brightness temperature for 18H (K)
melt_detect_18H: Melt days are (1) and dry days are (0) based off the hybrid method using 18H.

The Larsen C data are as follows:
Sites that show NaN have not been run

melt_detection: 0 for non-melt day, 1 for melt day
micrograinsize: Exponential correlation length/microwave grain size as derived from 18V AMSR-2 (m)