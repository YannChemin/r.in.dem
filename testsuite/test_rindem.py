"""Tests r.in.dem end-to-end against the real Copernicus GLO-30 DEM on
the public AWS Open Data registry (no account/API key needed -- see
r.in.dem.html). Network-dependent, so gated behind
R_IN_DEM_RUN_NETWORK_TESTS=1, same convention as
r.hydro.hbv/testsuite/test_karkheh_era5_v2.py's R_HYDRO_HBV_RUN_ERA5_TESTS.
"""

import os
import unittest

import grass.script as gs
from grass.gunittest.case import TestCase
from grass.gunittest.main import test


class TestRInDem(TestCase):
    output = "rindem_test_dem"

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("R_IN_DEM_RUN_NETWORK_TESTS"):
            raise unittest.SkipTest(
                "set R_IN_DEM_RUN_NETWORK_TESTS=1 to run the live "
                "Copernicus-DEM test (needs network access)"
            )
        cls.use_temp_region()
        # small (~0.2deg) region well within a single GLO-30 tile
        # (Zagros foothills, real land, real elevation variation)
        cls.runModule("g.region", n=33.3, s=33.1, e=47.8, w=47.6, res=0.002)

    @classmethod
    def tearDownClass(cls):
        if not os.environ.get("R_IN_DEM_RUN_NETWORK_TESTS"):
            return
        cls.del_temp_region()
        cls.runModule("g.remove", flags="f", type="raster", name=cls.output)

    def test_region_matched_import(self):
        self.assertModule(
            "r.in.dem",
            output=self.output,
            source="copernicus_glo30",
            overwrite=True,
        )
        self.assertRasterExists(self.output)

        stats = gs.parse_command("r.univar", map=self.output, flags="g")
        self.assertGreater(int(stats["n"]), 0)
        self.assertEqual(int(stats["null_cells"]), 0)
        # real terrain in this area is a few hundred to ~2000m, not a
        # placeholder/constant value
        self.assertGreater(float(stats["max"]), 100)
        self.assertGreater(float(stats["stddev"]), 1.0)


if __name__ == "__main__":
    test()
