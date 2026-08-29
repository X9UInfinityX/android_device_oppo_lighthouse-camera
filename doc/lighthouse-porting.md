# OPPO Find X9 Ultra Porting Notes

## Dump

- Device: OPPO Find X9 Ultra
- Model: `CPH2841`
- Firmware: `CPH2841_16.0.9.403(EX01)`
- Platform family: `OPSM8850`
- SoC: `SM8850`
- Android release: `16`

## Source-tree targets

Extract camera packages and supporting libraries into:

- `vendor/oppo/lighthouse-camera`
- `vendor/oppo/lighthouse`
- `vendor/oneplus/sm8850-common` for the shared SM8850 device layer

The device camera repository belongs at `device/oppo/lighthouse-camera`.
Its extractor generates `lighthouse-camera-vendor.mk` and imports the
lighthouse device vendor namespace.

The main device tree already carries the Qualcomm CAMX/HAL camera block and
`CAMERA_ICP` firmware. Do not duplicate modules from
`device/oppo/lighthouse`; duplicate prebuilt modules will conflict during the
build.

## Camera names

Lighthouse camera configuration and tuning payloads use names including:

- `lighthousefront`
- `lighthousemain`
- `lighthousetele`
- `lighthouseultratele`

Relevant stock locations include:

- `odm/lib64/camera`
- `odm/etc/camera/config`
- `odm/etc/camera`
- `my_product/app/OplusCamera/OplusCamera.apk`
- `my_product/lib64/libAPSClient*.so`
- `system_ext/lib64/libAPSClient-cmd-jni-extension.oplus.so`
- `system_ext/lib64/libsuperNight.oplus.so`
- `system_ext/lib64/vendor.oplus.hardware.cameraMDM@1.0.so`

After changing `proprietary-files.txt`, rerun `extract-files.py` against the
Find X9 Ultra dump so generated vendor makefiles and Android.bp modules use the
lighthouse paths.
