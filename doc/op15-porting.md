# OnePlus 15 Porting Notes

## Dump

- Source: `/home/koaan/Desktop/MIO-KITCHEN/OP15`
- Model/region observed: `CPH2745`
- Product type: `24863`
- Platform family: `OPSM8850`
- SoC property: `SM8850`
- Device OEM property: `OP611F`
- Display build: `CPH2745_11_A.01`
- Android release: `16`
- Security patch: `2026-04-01`

## First Porting Targets

The OnePlus 13 port used `dodge` and `sm8750-common`. The OnePlus 15 dump uses
`infiniti` naming throughout the camera stack, so extraction should target the
OnePlus 15 device/common trees:

- `vendor/oneplus/infiniti`
- `vendor/oneplus/sm8850-common`

The current OnePlus 13 `vendor/lib64/bm5a*.bin` entries are not present in the
OnePlus 15 dump. OnePlus 15 has these vendor camera binaries instead:

- `vendor/lib64/qsn1nrt430.bin`
- `vendor/lib64/qsn1nrt43270.bin`
- `vendor/lib64/qsn1rt1690_vga.bin`
- `vendor/lib64/qsn1rt169270_vga.bin`
- `vendor/lib64/qsn1rt430_vga.bin`
- `vendor/lib64/qsn1rt43270_vga.bin`
- `vendor/lib64/qsn2all.bin`
- `vendor/lib64/qsn3_video.bin`
- `vendor/lib64/qsn3all.bin`

The first `proprietary-files.txt` rewrite should add the OP15 sensor and tuning
payloads from:

- `odm/lib64/camera`
- `odm/etc/camera/config`
- `odm/etc/camera`
- `my_product/app/OplusCamera/OplusCamera.apk`
- `my_product/product_overlay/framework/com.oplus.camera.unit.sdk.jar`
- `my_product/product_overlay/framework/com.oplus.camera.unit.sdk.adapter.jar`
- `my_product/lib64/libAPSClient*.so`
- `odm/lib64/libAlgoProcess.so`
- `odm/lib64/libAlgoInterface.so`
- `odm/lib64/libcam.oplus.3a.v3.so`
- `odm/lib64/libcam.oplus.3a.v4.so`
- `odm/lib64/libOPAlgoCam*.so`
- `system_ext/lib64/libAPSClient-cmd-jni-extension.oplus.so`
- `system_ext/lib64/libsuperNight.oplus.so`
- `system_ext/lib64/vendor.oplus.hardware.cameraMDM@1.0.so`

The device tree at `device/oneplus/infiniti` already carries the large Qualcomm
CAMX/HAL camera block and `CAMERA_ICP` firmware. Do not duplicate that whole
block in this package unless the device vendor extraction is removed; duplicate
prebuilt modules will likely conflict at build time.

## Important OP15 Camera Names

Camera configs and tuning files use these names:

- `infinitifront`
- `infinitimain`
- `infinititele`
- `infinitiultrawide`

Relevant manifests/init files found in the dump:

- `vendor/etc/vintf/manifest/vendor.qti.camera.provider.xml`
- `vendor/etc/vintf/manifest/vendor.qti.camera.offlinecamera-impl.xml`
- `vendor/etc/vintf/manifest/vendor.qti.camera.aon-impl.xml`
- `odm/etc/vintf/manifest/manifest_oplus_camera_rfi.xml`
- `odm/etc/vintf/manifest/vendor.oplus.camera.aon-impl.xml`
- `vendor/etc/init/vendor.qti.camera.provider-service_64.rc`
- `odm/etc/init/init.camera_process.rc`
- `odm/etc/init/init.camera_debug_ui.rc`
- `odm/etc/init/init.camera_upate.rc`

## Build Properties To Mirror

The current `opluscamera.mk` already carries most camera properties from stock.
OP15 stock additionally confirms:

- `ro.com.google.lens.oem_image_package=com.oneplus.gallery,com.oplus.screenshot`
- `ro.camerax.extensions.enabled=true`
- `ro.camera.notify_nfc=1`
- `ro.oplus.camera.defercap.support=1`
- `ro.oplus.camera.defercap.all.quick.visible.support=1`
- `ro.oplus.camera.facing.front.need.disable.nfc=1`
- `oplus.software.camera.10bit=1`
