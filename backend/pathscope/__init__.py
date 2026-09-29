"""CV-Scope: configurable computer-vision monitoring and research platform."""

import os as _os

# OpenCV's Media Foundation backend (used for USB cameras on Windows) spends
# ~20 s opening a device while hardware transforms are enabled. The variable is
# read when OpenCV is first imported, so it is set here, before any CV-Scope
# module imports cv2. An explicit value in the environment wins.
_os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

__version__ = "0.1.0"
