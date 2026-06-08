# vendor_oplus_camera

Prebuilt stock oplus Camera to include in custom ROM builds.

### How to use?

1. Clone this repo to `vendor/oneplus/camera`

2. Inherit it from `device.mk` in device tree:

```
# Camera
$(call inherit-product-if-exists, vendor/oneplus/camera/opluscamera.mk)
```

3. Ensure that the PRODUCT_BRAND is either oneplus or oppo or realme and that it is not overriden by any of the safetynet hacks.

### How to extract proprietary files?

From the ROM source root, place or clone this repo at `vendor/oneplus/camera`,
then run:

```
cd vendor/oneplus/camera
./extract-files.py /path/to/OP15/dump
```

The extractor reads `proprietary-files.txt`, pulls the listed files from the
dump, applies the blob fixups in `extract-files.py`, and writes the results to:

```
vendor/oneplus/camera/camera/proprietary/
```

It also regenerates the generated build files under:

```
vendor/oneplus/camera/camera/
```

After changing `proprietary-files.txt`, rerun `./extract-files.py` against the
OP15 dump before building.
