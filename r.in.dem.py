#!/usr/bin/env python3
############################################################################
#
# MODULE:       r.in.dem
# AUTHOR:       Yann Chemin
# PURPOSE:      Imports a DEM covering the current region (or an
#               explicit area) from a global, no-authentication-needed
#               online source -- the Copernicus GLO-30/GLO-90 DEM,
#               published as Cloud-Optimized GeoTIFFs on the public AWS
#               Open Data registry -- so that r.hydro.hbv.basins (and
#               anything else needing a DEM) can be pointed at any
#               study area on Earth without the user having to already
#               have local elevation data.
# COPYRIGHT:    (C) 2026 by Yann Chemin
#               Released into the public domain -- see LICENSE (Unlicense).
#
############################################################################

# %module
# % description: Imports a DEM covering the current region (or an explicit area) from the Copernicus GLO-30/GLO-90 global DEM (public, no account/API-key needed), reprojecting on the fly.
# % keyword: raster
# % keyword: import
# % keyword: elevation
# % keyword: DEM
# %end
# %option G_OPT_R_OUTPUT
# %end
# %option
# % key: source
# % type: string
# % required: yes
# % options: copernicus_glo30,copernicus_glo90
# % answer: copernicus_glo30
# % description: DEM source (GLO-30 ~30m, GLO-90 ~90m; both are seamless global land coverage, including areas SRTM lacks such as high latitudes)
# %end
# %option
# % key: area
# % type: string
# % required: no
# % key_desc: north,west,south,east
# % description: Bounding box in WGS84 degrees (north,west,south,east); default derived from the current region
# %end
# %option
# % key: resample
# % type: string
# % required: yes
# % options: nearest,bilinear,bicubic,lanczos
# % answer: bilinear
# % description: Resampling method used by r.import while reprojecting
# %end
# %option G_OPT_M_DIR
# % key: cache_dir
# % required: no
# % description: Directory to cache the mosaic VRT/tile index in (default a temporary, run-scoped directory)
# %end
# %flag
# % key: n
# % description: Import at the DEM's native resolution instead of the current region's (much slower over more than a small area -- every pixel is a separate network read; default matches the region's resolution/extent, which GDAL can serve from coarser overviews and is dramatically faster)
# %end

import atexit
import math
import os
import shutil
import sys
import urllib.request

import grass.script as gs

TMP_DIR = None

SOURCES = {
    "copernicus_glo30": dict(
        bucket="copernicus-dem-30m",
        code="10",
        description="Copernicus GLO-30 (~30m)",
    ),
    "copernicus_glo90": dict(
        bucket="copernicus-dem-90m",
        code="30",
        description="Copernicus GLO-90 (~90m)",
    ),
}


def cleanup():
    if TMP_DIR and os.path.isdir(TMP_DIR):
        shutil.rmtree(TMP_DIR, ignore_errors=True)


def default_area():
    info = gs.parse_command("g.region", flags="bg")
    return [
        float(info["ll_n"]),
        float(info["ll_w"]),
        float(info["ll_s"]),
        float(info["ll_e"]),
    ]


def tile_name(lat, lon, code):
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return "Copernicus_DSM_COG_%s_%s%02d_00_%s%03d_00_DEM" % (
        code,
        ns,
        abs(lat),
        ew,
        abs(lon),
    )


def tiles_for_area(north, west, south, east):
    """Yields (lat, lon) for every 1-degree tile (identified by its
    south-west corner) overlapping [south, north] x [west, east]."""
    lat0 = int(math.floor(south))
    lat1 = int(math.floor(north - 1e-9))
    lon0 = int(math.floor(west))
    lon1 = int(math.floor(east - 1e-9))
    for lat in range(lat0, lat1 + 1):
        for lon in range(lon0, lon1 + 1):
            yield lat, lon


def tile_exists(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception:
        return False


def main():
    options, flags = gs.parser()

    global TMP_DIR
    source = SOURCES[options["source"]]

    if options["area"]:
        area = [float(v) for v in options["area"].split(",")]
        if len(area) != 4:
            gs.fatal("area must be 'north,west,south,east'")
    else:
        area = default_area()
    north, west, south, east = area

    cache_dir = options["cache_dir"]
    if not cache_dir:
        cache_dir = gs.tempdir()
        TMP_DIR = cache_dir
    os.makedirs(cache_dir, exist_ok=True)

    urls = []
    missing = []
    for lat, lon in tiles_for_area(north, west, south, east):
        name = tile_name(lat, lon, source["code"])
        https_url = "https://%s.s3.amazonaws.com/%s/%s.tif" % (
            source["bucket"],
            name,
            name,
        )
        if tile_exists(https_url):
            urls.append("/vsicurl/" + https_url)
        else:
            missing.append(name)

    if missing:
        gs.warning(
            "%d tile(s) not present in %s (likely ocean-only, no land "
            "elevation there): %s"
            % (len(missing), source["description"], ", ".join(missing))
        )
    if not urls:
        gs.fatal(
            "No %s tiles found for area (%.4f,%.4f,%.4f,%.4f) -- check "
            "the region/area is actually over land"
            % (source["description"], north, west, south, east)
        )

    from osgeo import gdal

    vrt_path = os.path.join(cache_dir, "dem_mosaic.vrt")
    gdal.BuildVRT(vrt_path, urls)

    gs.message(
        "Importing %d %s tile(s)..." % (len(urls), source["description"])
    )

    if flags["n"]:
        # every output pixel is its own network read at the DEM's full
        # native resolution -- correct, but only practical over a small
        # area (a few minutes even for a handful of tiles).
        gs.run_command(
            "r.import",
            input=vrt_path,
            output=options["output"],
            resample=options["resample"],
            extent="input",
            resolution="estimated",
            overwrite=gs.overwrite(),
        )
    else:
        # gdal.Warp() straight to the project's own CRS/extent/resolution
        # lets GDAL read each remote COG's internal overview closest to
        # the requested resolution instead of every full-resolution
        # pixel -- r.import's extent=region/resolution=region alone
        # does *not* get this for free (it still asked for the VRT's
        # native pixels first, then resampled locally), which is why
        # this path exists rather than just passing those options
        # through to r.import.
        region = gs.parse_command("g.region", flags="g")
        proj_wkt = gs.read_command("g.proj", flags="w")
        resample_alg = {
            "nearest": "near",
            "bilinear": "bilinear",
            "bicubic": "cubic",
            "lanczos": "lanczos",
        }[options["resample"]]

        dst_path = os.path.join(cache_dir, "dem_region.tif")
        gdal.Warp(
            dst_path,
            vrt_path,
            srcSRS="EPSG:4326",
            dstSRS=proj_wkt,
            outputBounds=(
                float(region["w"]),
                float(region["s"]),
                float(region["e"]),
                float(region["n"]),
            ),
            xRes=float(region["ewres"]),
            yRes=float(region["nsres"]),
            resampleAlg=resample_alg,
        )
        gs.run_command(
            "r.in.gdal",
            input=dst_path,
            output=options["output"],
            overwrite=gs.overwrite(),
        )

    gs.run_command("r.colors", map=options["output"], color="elevation")

    gs.message(
        "Imported <%s> from %d %s tile(s)"
        % (options["output"], len(urls), source["description"])
    )


if __name__ == "__main__":
    atexit.register(cleanup)
    sys.exit(main())
