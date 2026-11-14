# Shade Seeker — Agent Skills & Troubleshooting Log

## 1. Environment & Dependencies
* **Rule**: Always ensure dependencies like `pandas`, `pvlib`, and `timezonefinder` are installed in the active virtual environment before running test suites or app scripts.

## 2. API & Routing Quirks
* **Rule**: Google Routes API can return simplified polylines for `TRANSIT` modes compared to `DRIVE` modes. If a test or route looks linear between major transit hubs, this is expected behavior from transit data feeds.


* **Rule**: Ensure all required external libraries, such as `polyline`, are installed in the active virtual environment before executing tests.