#!/usr/bin/env python3
"""One-off: build the simplified India outline used by backend/services/geospatial_service.py.

Source: DataMeet `india-composite.geojson` (CC0) -- India's land area per the official
Survey of India boundary. Steps: buffer outward by BUFFER_DEG so coastal and border
towns are not rejected by simplification or by the ~45 km CAMS grid, then simplify.
"""
import json, sys
from shapely.geometry import shape, Point
from shapely.ops import unary_union

BUFFER_DEG, SIMPLIFY_DEG = 0.2, 0.04
src, out = sys.argv[1], sys.argv[2]
g = shape(json.load(open(src, encoding="utf-8"))["features"][0]["geometry"])
g = unary_union(g.buffer(0)).buffer(BUFFER_DEG).simplify(SIMPLIFY_DEG, preserve_topology=True)
polys = list(getattr(g, "geoms", [g]))
rings = [[[round(x, 3), round(y, 3)] for x, y in p.exterior.coords] for p in polys]   # holes dropped on purpose
doc = {"name": "India (official Survey of India boundary, simplified)",
       "source": "DataMeet india-composite.geojson, https://github.com/datameet/maps/tree/master/Country (CC0)",
       "buffer_degrees": BUFFER_DEG, "simplify_degrees": SIMPLIFY_DEG,
       "bbox": [round(v, 3) for v in g.bounds], "rings": rings}
json.dump(doc, open(out, "w", encoding="utf-8"), separators=(",", ":"))
print("polygons:", len(rings), "points:", sum(len(r) for r in rings), "bbox:", doc["bbox"])
for r in sorted(rings, key=len, reverse=True)[:12]:
    xs = [p[0] for p in r]; ys = [p[1] for p in r]
    print("  ring", len(r), "pts  lon %.1f..%.1f lat %.1f..%.1f" % (min(xs), max(xs), min(ys), max(ys)))
