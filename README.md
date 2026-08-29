# android_device_oppo_lighthouse-camera

Prebuilt stock oplus Camera to include in custom ROM builds.

### How to use?

1. Clone this repo to `device/oppo/lighthouse-camera`

2. Inherit it from `device.mk` in device tree:

```
# Camera
$(call inherit-product-if-exists, device/oppo/lighthouse-camera/opluscamera.mk)
```

3. Ensure that the PRODUCT_BRAND is either oneplus or oppo or realme and that it is not overriden by any of the safetynet hacks.

### How to extract proprietary files?

From the ROM source root, place or clone this repo at `device/oppo/lighthouse-camera`,
then run:

```
cd device/oppo/lighthouse-camera
./extract-files.py /path/to/CPH2841/dump
```

The extractor reads `proprietary-files.txt`, pulls the listed files from the
dump, applies the blob fixups in `extract-files.py`, and writes the results to:

```
vendor/oppo/lighthouse-camera/proprietary
```

It also regenerates the generated build files under:

```
vendor/oppo/lighthouse-camera
```

After changing `proprietary-files.txt`, rerun `./extract-files.py` against the
OPPO Find X9 Ultra dump before building.
