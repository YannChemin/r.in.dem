# r.in.dem

A [GRASS GIS](https://grass.osgeo.org/) addon that imports a real DEM
for the current region — anywhere on Earth — with a single command and
**no account, API key, or signed request of any kind**.

```
g.region n=34 s=31 e=49 w=47 res=0:06
r.in.dem output=dem
```

## Why

Most global DEM sources (SRTM via OpenTopography, etc.) require a free
account and an API key before you can download anything, which is a
speed bump every time you want to point a workflow at a new study
area. `r.in.dem` instead reads the **Copernicus GLO-30/GLO-90** DEM
directly from its public AWS Open Data bucket — those tiles are plain,
publicly readable HTTPS objects, confirmed reachable with nothing more
than `curl`. Coverage is seamless over all land, including areas SRTM
lacks (above 60°N or below 56°S).

This was built as part of the [r.hydro.hbv](https://github.com/YannChemin/HBV)
ecosystem, so that `r.hydro.hbv`'s basin delineation
(`r.hydro.hbv.basins`) can be run against any catchment on Earth
without first having to source and import a DEM by hand.

## How it works

1. Works out which 1°×1° Copernicus DEM tiles overlap the requested
   area (the current region by default, or an explicit `area=`).
2. HEAD-checks each tile — ocean-only tiles simply don't exist in the
   bucket, and are skipped with a warning rather than failing the
   whole import.
3. Mosaics the tiles that do exist into a GDAL VRT over `/vsicurl/`
   (no bulk download — only the pixels actually needed are read).
4. By default, warps that VRT straight to the current project's
   CRS/extent/resolution via `gdal.Warp()`, then imports the (now
   small, local) result with `r.in.gdal`. Warping directly to the
   target resolution lets GDAL read each tile's internal Cloud-Optimized-GeoTIFF
   overview closest to that resolution instead of every native pixel —
   for a 3°×2° test area this was the difference between roughly 25
   seconds and roughly 8 minutes.
5. Pass `-n` to instead import at the DEM's full native resolution via
   `r.import`, trimmed to the region's extent. Only worth it when you
   actually need that much detail — it re-introduces the same
   per-pixel network cost the default path avoids.

## Options

| Option | Description |
|---|---|
| `output` | Name for the output raster map |
| `source` | `copernicus_glo30` (~30m, default) or `copernicus_glo90` (~90m) |
| `area` | `north,west,south,east` in WGS84 degrees; default derived from the current region |
| `resample` | Resampling method: `nearest`, `bilinear` (default), `bicubic`, `lanczos` |
| `cache_dir` | Directory to cache the mosaic VRT/warped GeoTIFF in; default a temporary, run-scoped directory |
| `-n` | Import at the DEM's native resolution instead of matching the current region (much slower over more than a small area) |

## Requirements

- GRASS GIS with `r.import`/`r.in.gdal` (core)
- GDAL Python bindings (`osgeo.gdal`)
- Network access to `*.s3.amazonaws.com` (no credentials needed)

## Install

```
g.extension extension=r.in.dem url=https://github.com/YannChemin/r.in.dem
```

## Testing

`testsuite/test_rindem.py` runs a real import against the live
Copernicus DEM bucket; it's gated behind an environment variable so it
doesn't run (and doesn't need network access) by default:

```
R_IN_DEM_RUN_NETWORK_TESTS=1 python3 -m grass.gunittest.main testsuite/test_rindem.py
```

## License

Public domain — see [LICENSE](LICENSE) (Unlicense).

## See also

- [r.hydro.hbv](https://github.com/YannChemin/HBV) — the HBV
  hydrological model this module was built to feed a DEM into
- [r.import](https://grass.osgeo.org/grass-stable/manuals/r.import.html)
