"""The brush swirl's envelope reaches sin(pi * t / t[-1]) = sin(pi) at its last sample; rounding sometimes puts the
angle a hair past pi, the sine a tiny negative number, and a negative number to the power 1.5 is NaN. It must stay
finite (silence, not NaN, at the end)."""
import warnings

import numpy as np

from gentle_stream import genres
from gentle_stream.engine import SR


def test_the_brush_swirl_is_finite_to_its_last_sample():
    voices = genres.get("jazz").instruments(np.random.default_rng(0), SR, None)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)       # "invalid value encountered in power" fails the test
        for dur in (0.012, 0.027, 0.172, 0.2, 0.5, 1.0):     # the first three rounded past pi
            x = voices.swirl(dur)
            assert np.isfinite(x).all() and abs(float(x[-1])) < 1e-6
