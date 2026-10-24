# Blob fixups for ColorOS 17.0.0.101

This document describes the active fixups in `extract-files.py` for the OPPO
Find X9 Ultra (`CPH2841_17.0.0.101(EX01)`). It is a rebase guide: obfuscated
class names are recorded for this release, but they are not sufficient proof
that a patch still belongs in a later app.

## Rebase rule

For every new firmware:

1. Decode the stock APK/JAR and identify the source class, caller, branch, and
   Android/Oplus API involved in the behavior.
2. Confirm the patched method's inputs, output type, and side effects still
   have the same meaning. A matching method name or byte sequence is not
   enough.
3. Anchor a fixup to source metadata, a unique log/config string, and/or the
   relevant API chain. Let extraction fail when the anchor is absent.
4. Rebuild the modified APK/JAR with apktool. Then inspect the rebuilt smali or
   manifest to confirm the intended branch changed and adjacent behavior did
   not.
5. Run a clean extraction of the complete proprietary list. Do not accept an
   APK-level `fixed up` message as proof that every callback for that APK ran;
   another callback may be the only one that changed it.

## Camera and camera SDK

| Fixup | 17.0.0.101 semantic target | Effect |
| --- | --- | --- |
| Camera typeface fallback | The `TypeFaceUtil.a(Context)` method that reads `OplusBaseConfiguration`, `OplusExtraConfiguration`, and `OplusFontUtils`. | Returns `Typeface.DEFAULT`, avoiding an NPE/linkage failure when the complete Oplus font framework is unavailable. |
| Blur `segInit` guards | `OplusBlurProcess` (`hf/b`) and the size-change initializer (`jf/j`) call `OplusBlurPreviewHelper.segInit(...)`, save its `int[]`, and immediately dereference it. | Treats a null result as an unavailable blur engine. The synchronized process path exits its monitor and returns `false`; the size-change path returns `void`. |
| OEM wrapper shims | Calls to the Oplus wrapper forms of `SystemProperties`, `UserHandle`, `Trace`, and `Debug`. | Redirects them to the corresponding framework hidden APIs with the same signatures. This is used by SystemUIPlugin, Melody, and FileEncryption. |
| OEM component permissions | Component-level Oplus/Oppo/HeyTap permission gates in Camera, Gallery, and Melody manifests. | Removes gates whose OEM permission ownership is not reliable after platform resigning, while leaving the components registered. Review newly introduced app-owned permissions before broadening this rule. |
| Camera SDK sensor wait | `com.oplus.camera.unit.sdk.jar`; `BaseMode.isSensorModeNeedWait(II)`. | Disables the mode-3 sensor wait that stalls the port. COS17 rebuilds with its stock field initializers, so the old no-op initializer rewrites were removed. |
| Face-beauty probe | The guarded string probe for `libApsFaceBeautyPreviewProductJni.so`. | Changes `/product/lib64` to the library's port location, `/system_ext/lib64`. |
| APS Java HEIF handoff | `libAPSClient-cmd-jni.so`, pinned by stock and post-patch SHA-256 plus exact offsets. | Makes two optional native `dlopen` probes fail so APS follows its stock Java-reflection HEIF path instead of the accidentally enabled co-located native path. |

## FileEncryption

`BiometricsUnlockManager.kt` is `r9/a` in this firmware. Its stock face method
uses `OplusFaceManager` through Epona and its fingerprint method uses the Oplus
fingerprint wrapper (methods `c` and `d`, respectively). The fixup replaces
only those enrollment predicates with
the AOSP `FaceManager.hasEnrolledTemplates()` and
`FingerprintManager.isHardwareDetected()/hasEnrolledFingerprints()` calls.
Both paths fail closed on an exception. The manifest gains the biometric and
secure-settings permissions required by those calls.

The Private Safe unlock-method dialog uses the standalone preference fragment's
full-height floating toolbar layout. Its toolbar is not removed because the
fragment looks up the wrong ID. Adapted from OP15InfinityX commit
`73cae650db7c01cc66e273f00f400fbfd032f20d`, the dialog fixup removes the
real toolbar, sizes the preference list to its content, and lets the dialog
supply its own background. It also avoids COUI's vendor-only raw scroll path
when the framework lacks that API.

## Gallery

| Fixup | 17.0.0.101 semantic target | Effect |
| --- | --- | --- |
| Dynamic receiver flags | `BroadcastDispatcher.kt` (`foundation/uikit/broadcast/bus/a`) proxy registration and the concrete `ActionReceiver`. | Clears `RECEIVER_EXPORTED` and sets `RECEIVER_NOT_EXPORTED`, preserving unrelated flag bits. |
| Wallpaper intent | `PictureEditorDM.a(Activity, Uri, boolean)` is the method containing `getCropAndSetWallpaperIntent`. | Uses `ACTION_ATTACH_DATA` with `image/*`, URI read permission, and the existing activity instead of the unavailable Oplus wallpaper crop flow, while preserving the live-photo extra. |
| Safe Box capability | `ConfigAbilityWrapper.kt` (`n6b`), the global boolean accessor `b(String, boolean, boolean)`. | Returns true only for `feature_is_support_user_custom_safe_box`; all other config keys retain stock handling. |
| Google Photos verify listener | `GCloudPageHelper$launchBackupPage$1$1.a(boolean)`. | Continues into the existing page helper for either verification result so a failed first verification can reach consent. COS17 now propagates the failure through `GCloudSyncStatusManager` itself, so the old injected consent coroutine is no longer needed. |
| Hide Google Photos surfaces | The `action_backup_to_cloud` action-definition `LinkedHashMap` (`pqx`) and `SettingsActivity$SettingFragment`. | Removes the backup action ID from the photo-page menu map and removes `pref_category_cloud_sync_key` after Settings inflation. |
| System share | `ShareHelper.kt`, after the `feature_is_support_user_custom_gallery_share` gate. | Bypasses only the private Oplus share-page product flag and enters the existing system chooser. Its URI helper maps the local `o3q` media object's `A()` path through `GalleryFileProvider` (`j1i`), then retains the stock image/video MediaStore fallbacks. |
| Lighthouse QNN runtime | Gallery's manifest references nonexistent V75 `/odm/lib64/aiboost` paths, including a duplicate. | Removes the complete obsolete path family, declares the six root-level V81 libraries present in the Lighthouse dump, and embeds the exact dump binaries. |

Do not restore the old override of `vzt.m()`. In this Gallery build that method
decides whether an action must fetch low-quality media before execution; it no
longer controls backup-menu visibility. Overriding it would change unrelated
photo actions.

## File Manager

| Fixup | 17.0.0.101 semantic target | Effect |
| --- | --- | --- |
| Direct safe check | `JavaFileHelper` (`common/fileutils/e`), uniquely anchored by `safeCheck start`. | Executes the supplied Kotlin function directly and preserves its result/logging, avoiding an unavailable OEM safe-check wrapper. |
| Select-directory fallback | `SelectDirPathPanelFragment` click flow. | When its selected-path LiveData is null/empty, uses `BrowserPathBar.getCurrentPath()`, which is updated during navigation. |

## Other applications and manifests

| Package/file | Fixup and reason |
| --- | --- |
| SystemUIPlugin | Replaces Oplus wrapper API descriptors with the corresponding framework hidden APIs. |
| OplusGestureUI | Moves the private `com.oplus.gesture_nonIndexKey` cache in `GestureSettingsProviderUtils` (`lb/r`) from `Settings.System` to `Settings.Secure`. AOSP rejects app-defined System settings and otherwise propagates the provider exception into SettingsIntelligence during search indexing. Its 19 indexed preference XMLs also use unqualified `PreferenceScreen` roots so Google Settings Intelligence can parse them. |
| Melody | The methods semantically located in `RepackagingDetector.java` derive the AES key used for the bundled earphone whitelist from the signing certificate. Its certificate-hash methods return the verified stock SHA-256 hash `B0:A9:BB:FC:05:EE:E5:E7:D0:A2:C9:7C:03:05:86:E1:5B:B3:30:11:52:07:8F:54:47:3B:B8:2D:F6:D8:C8:18`; only the LSPatch predicate is forced false. |
| StdID | Converts both `AppApplication.onCreate()` dynamic receiver registrations to the flags overload with `RECEIVER_NOT_EXPORTED`, preserving the optional permission argument. |
| SafeCenter | Adds `RECEIVER_NOT_EXPORTED` to `BaseSelfFinishActivity`, semantically locates and forces the actual `OLockManager.isSupportOLock(Context)` predicate true, and supplies the missing OLock dark theme. |
| PhoneManager | Adds secure-settings permission, maps its Settings tile to AOSP's security/privacy category, and points the `MANAGE_PERMISSIONS` intent package from Google's permission controller to `com.android.permissioncontroller`. |
| AONService / AIUnit | Maps their OEM Settings metadata to AOSP's advanced-security category so TileUtils places them correctly. AIUnit also uses an unqualified `PreferenceScreen` root for its AI Service Engine XML so Google Settings Intelligence can index it without crashing. |
| UMS | Adds `SET_ACTIVITY_WATCHER` to both the manifest and its privapp allowlist. |
| SecurityPermission | Defines the Oplus/Oppo signature/privileged permissions referenced by the ported applications. |
| Cryptoeng permission XML | Merges the dump's two adjacent `<permissions>` roots into one valid document. |
| Cryptoeng init | Adds `restorecon_recursive` immediately after creating `/data/vendor_de/0/cryptoeng`; keeps the current init-language SM6450 property trigger unchanged. |
| Cryptoeng VINTF | Enables the HIDL 1.0 declaration alongside AIDL. The service binary links both `vendor.oplus.hardware.cryptoeng@1.0`/`libhidlbase` and the AIDL NDK interface. |
| Camera stubs library | Adds optional `oplus.camera.stubs` uses-library metadata to ported apps that resolve those framework stubs. |

## Dump/list audit notes

- The list uses the `mt120` Wi-Fi calibration XML present in this dump; the old
  `mt105` file is absent.
- Seven nonexistent 32-bit crypto/FIDO ODM libraries were removed from the
  list. Their 64-bit counterparts remain.
- The six `configs/lib64/libQnn*.so` files must hash-identically match
  `F9UEU/odm/lib64`, because Gallery copies them into its APK during fixup.
- A clean extraction must complete without missing-file reports, patch
  exceptions, or same-hash fixup warnings.
