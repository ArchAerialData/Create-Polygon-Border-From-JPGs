# WWM facility regression fixture

`wwm_station_facilities_37_polygons.kmz` is an unchanged copy provided for multi-polygon import, buffer, sectioning, simplification, preview, and KMZ export regression tests.

- Original: `A:\z_TemporaryDailes_z\WWM - 37 Stations\Shapes\Final\WWM Station - Facilities (100ft Buffer) - Site Polygons Only.kmz`
- Size: 115,041 bytes
- SHA-256: `61bffe0f3a5aedb2318d21bb68e3eb17c277627177c0df9ccdd138c83aa679e1`
- Contents: `doc.kml`, 37 uniquely named Placemarks, 37 closed polygons, no LineStrings, no interior rings.
- Facility processing projections: EPSG:32613, EPSG:32614, and EPSG:32615.

Tests read this repository copy without external drives or network access. Outputs belong in temporary directories. Buffer settings add distance to the supplied geometry; the filename does not set a buffer automatically. Preserve this fixture and its checksum; add a separately named fixture if the source changes.
