"""Distance (km) from each of the 38 locations to the open sea, using a 1 km land mask.
Water bodies not connected to the open ocean (lakes) are ignored."""
import json, sys
import numpy as np
from global_land_mask import globe
from scipy import ndimage

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from ml import config

lat = np.arange(4.0, 38.0, 0.04)
lon = np.arange(64.0, 100.0, 0.04)
LA, LO = np.meshgrid(lat, lon, indexing="ij")
water = ~globe.is_land(LA, LO)
lab, _ = ndimage.label(water)
ocean_label = lab[np.searchsorted(lat, 10.0), np.searchsorted(lon, 70.0)]  # Arabian Sea
ocean = lab == ocean_label
olat, olon = np.radians(LA[ocean]), np.radians(LO[ocean])


def coast_km(la, lo):
    la, lo = np.radians(la), np.radians(lo)
    a = np.sin((olat - la) / 2) ** 2 + np.cos(la) * np.cos(olat) * np.sin((olon - lo) / 2) ** 2
    return float(6371 * 2 * np.arcsin(np.sqrt(a)).min())


out = {l[0]: round(coast_km(l[3], l[4]), 1) for l in config.LOCATIONS}
json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "docs/experiments/coast_km.json", "w"), indent=1)
print(out)
