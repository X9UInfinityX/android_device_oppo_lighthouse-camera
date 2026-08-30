# Blob fixups for ColorOS 16.0.9.403

This document describes the active fixups in `extract-files.py` for the OPPO
Find X9 Ultra (`CPH2841_16.0.9.403(EX01)`). It is a rebase guide: obfuscated
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

| Fixup | 16.0.9.403 semantic target | Effect |
| --- | --- | --- |
| Camera typeface fallback | `TypeFaceUtil.a(Context)` in `a8/v3` reads `OplusBaseConfiguration`, `OplusExtraConfiguration`, and `OplusFontUtils`. | Returns `Typeface.DEFAULT`, avoiding an NPE/linkage failure when the complete Oplus font framework is unavailable. |
| Blur `segInit` guards | `OplusBlurProcess` (`cc/b`) and the size-change initializer (`ec/i`) call `OplusBlurPreviewHelper.segInit(...)`, save its `int[]`, and immediately dereference it. | Treats a null result as an unavailable blur engine. The synchronized process path exits its monitor and returns `false`; the size-change path returns `void`. |
| OEM wrapper shims | Calls to the Oplus wrapper forms of `SystemProperties`, `UserHandle`, `Trace`, and `Debug`. | Redirects them to the corresponding framework hidden APIs with the same signatures. This is used by SystemUIPlugin, Melody, and FileEncryption. |
| OEM component permissions | Component-level Oplus/Oppo/HeyTap permission gates in Camera, Gallery, and Melody manifests. | Removes gates whose OEM permission ownership is not reliable after platform resigning, while leaving the components registered. Review newly introduced app-owned permissions before broadening this rule. |
| Camera SDK patch set | `com.oplus.camera.unit.sdk.jar`; the patch applies to named SDK classes, including `BaseMode.isSensorModeNeedWait(II)`. | Removes explicit false-valued smali field initializers that break the rebuild and disables the mode-3 sensor wait that stalls the port. |
| Face-beauty probe | The guarded string probe for `libApsFaceBeautyPreviewProductJni.so`. | Changes `/product/lib64` to the library's port location, `/system_ext/lib64`. |
| APS Java HEIF handoff | `libAPSClient-cmd-jni.so`, pinned by stock and post-patch SHA-256 plus exact offsets. | Makes two optional native `dlopen` probes fail so APS follows its stock Java-reflection HEIF path instead of the accidentally enabled co-located native path. |

## FileEncryption

`BiometricsUnlockManager.kt` is `x8/a` in this firmware. Its stock face method
uses `OplusFaceManager` through Epona and its fingerprint method uses the Oplus
fingerprint wrapper. The fixup replaces only those enrollment predicates with
the AOSP `FaceManager.hasEnrolledTemplates()` and
`FingerprintManager.isHardwareDetected()/hasEnrolledFingerprints()` calls.
Both paths fail closed on an exception. The manifest gains the biometric and
secure-settings permissions required by those calls.

## Gallery

| Fixup | 16.0.9.403 semantic target | Effect |
| --- | --- | --- |
| Dynamic receiver flags | `BroadcastDispatcher.kt` (`ay5`) proxy registration and the concrete `ActionReceiver`. | Clears `RECEIVER_EXPORTED` and sets `RECEIVER_NOT_EXPORTED`, preserving unrelated flag bits. |
| Wallpaper intent | `PictureEditorDM.a(Activity, Uri)` is the method containing `getCropAndSetWallpaperIntent`. | Uses `ACTION_ATTACH_DATA` with `image/*`, URI read permission, and the existing activity instead of the unavailable Oplus wallpaper crop flow. |
| Safe Box capability | `ConfigAbilityWrapper.kt` (`g19`), the global boolean accessor `c(String, boolean, boolean)`. | Returns true only for `feature_is_support_user_custom_safe_box`; all other config keys retain stock handling. |
| Google Photos verify listener | `GCloudPageHelper.kt` (`llf`), callback `a(boolean)` holding `mlf.e`. | Continues into the existing page helper for either verification result so a failed first verification can reach consent. |
| Google Photos consent coroutine | `GCloudSyncStatusManager$c`, uniquely anchored by `verifyAppState failure. e:` and `GooglePhotosBackupApiClient.verifyAppState`. | On the failure branch, launches the app's existing `gotoGrantConnectionConsent` coroutine (`fnf`) on its own scope (`dk3`) with `EntryPoint.SETTINGS`. |
| Hide Google Photos surfaces | The `action_backup_to_cloud` action-definition `LinkedHashMap` (`ncu`) and `SettingsActivity$SettingFragment`. | Removes the backup action ID from the photo-page menu map and removes `pref_category_cloud_sync_key` after Settings inflation. |
| System share | `ShareHelper.kt` (`z910`), after the `feature_is_support_user_custom_gallery_share` gate. | Bypasses only the private Oplus share-page product flag and enters the existing system chooser. Its URI helper first maps a local `qkm` media path through `GalleryFileProvider`, then retains the stock image/video MediaStore fallbacks. |
| Lighthouse QNN runtime | Gallery's manifest references nonexistent V75 `/odm/lib64/aiboost` paths, including a duplicate. | Removes the complete obsolete path family, declares the six root-level V81 libraries present in the Lighthouse dump, and embeds the exact dump binaries. |

Do not restore the old override of `vzt.m()`. In this Gallery build that method
decides whether an action must fetch low-quality media before execution; it no
longer controls backup-menu visibility. Overriding it would change unrelated
photo actions.

## File Manager

| Fixup | 16.0.9.403 semantic target | Effect |
| --- | --- | --- |
| Direct safe check | `JavaFileHelper` (`common/fileutils/e`), uniquely anchored by `safeCheck start`. | Executes the supplied Kotlin function directly and preserves its result/logging, avoiding an unavailable OEM safe-check wrapper. |
| Select-directory fallback | `SelectDirPathPanelFragment` click flow. | When its selected-path LiveData is null/empty, uses `BrowserPathBar.getCurrentPath()`, which is updated during navigation. |
| Same-volume cut | `FileActionCut.V()` obtains the same-volume boolean from `cut/g.j()`; the later branch calls `K0()` for cross-device handling. | Skips `K0()` only when the derived same-volume field is true. Cross-volume moves retain stock behavior. |
| Super App archive preview | Initial entry of `SuperListFragment$n.invokeSuspend`; `c.v() == 0x80` is the app's archive type and `ga/a.Q0(...)` creates `ACTION_COMPRESS_PREVIEW`. | Opens an archive directly in the built-in preview flow and returns Kotlin `Unit`; all non-archive items continue through the stock coroutine. |

The two older OSense no-op patches are intentionally inactive. In this build,
`w8/b.f()` already checks the app's AOSP predicate (`q8/k.b()`) before calling
the scene API. Replacing `FileActionBaseCopyCut.c0()` or the whole scene helper
would now suppress valid file-operation behavior.

## Other applications and manifests

| Package/file | Fixup and reason |
| --- | --- |
| SystemUIPlugin | Replaces Oplus wrapper API descriptors. The old `k9/b`/`t4/h` inflater patch is retired: those classes now represent unrelated constants and a `CompositionSamplingListener`, while the current plugin uses `ContextHandler` directly. |
| Melody | `RepackagingDetector.java` (`com/oplus/melody/common/util/N`) derives the AES key used for the bundled earphone whitelist from the signing certificate. Methods `b/c/d(Context)` return the verified stock SHA-256 certificate hash `B0:A9:BB:FC:05:EE:E5:E7:D0:A2:C9:7C:03:05:86:E1:5B:B3:30:11:52:07:8F:54:47:3B:B8:2D:F6:D8:C8:18`; only `e(Context)`, the LSPatch predicate, is forced false. |
| StdID | Converts both `AppApplication.onCreate()` dynamic receiver registrations to the flags overload with `RECEIVER_NOT_EXPORTED`, preserving the optional permission argument. |
| SafeCenter | Adds `RECEIVER_NOT_EXPORTED` to `BaseSelfFinishActivity`, forces the actual `OLockManager.isSupportOLock` predicate `j7/k.J(Context)` true, and supplies the missing OLock dark theme. |
| PhoneManager | Adds secure-settings permission, maps its Settings tile to AOSP's security/privacy category, and points the `MANAGE_PERMISSIONS` intent package from Google's permission controller to `com.android.permissioncontroller`. |
| AONService / AIUnit | Maps their OEM Settings metadata to AOSP's advanced-security category so TileUtils places them correctly. |
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
