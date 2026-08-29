#!/usr/bin/env -S PYTHONPATH=../../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: 2016 The CyanogenMod Project
# SPDX-FileCopyrightText: 2017-2024 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

from extract_utils.fixups_lib import (
    lib_fixups,
    lib_fixups_user_type,
)
from extract_utils.fixups_blob import (
    apktool_path,
    blob_fixup,
    blob_fixups_user_type,
    java_path,
)
from extract_utils.main import (
    ExtractUtils,
    ExtractUtilsModule,
)
from extract_utils.utils import run_cmd
from hashlib import sha256
from pathlib import Path
import glob
import re
import shutil


APSCLIENT_STOCK_SHA256 = 'b6669463a2dbdc22d20d0bb1a565ef9f1cc058f5f34c627a8d49971f7c509bec'
APSCLIENT_PATCHED_SHA256 = 'fadd66bfe6344294fa0d3055382b1506e8432d01a562849478be82973e5974f8'
APSCLIENT_HEIF_DLOPEN_TARGETS = (
    (0x4C11B, b'libHeifEncoderWrapper.so', b'xibHeifEncoderWrapper.so'),
    (0x48551, b'libNativeWinBuffExchange.so', b'xibNativeWinBuffExchange.so'),
)


def lib_fixup_system_ext_suffix(lib: str, partition: str, *args, **kwargs):
    """
    Mirrors lib_to_package_fixup_system_ext_variants from the old setup-makefiles.sh.
    These libs exist as system_ext variants and need a _system_ext suffix
    when pulled from that partition.
    """
    if partition != 'system_ext':
        return None

    system_ext_libs = {
        'libSuperTextWrapper',
        'libXDocProcessSDK',
        'libYTCommon',
        'libmpbase',
        'libextendfile',
    }

    return f'{lib}_system_ext' if lib in system_ext_libs else None


def _noop_smali_method(data: str, signature: str) -> str:
    return re.sub(
        rf'(?ms)^\.method {re.escape(signature)}\n.*?^\.end method',
        f'.method {signature}\n'
        '    .locals 0\n'
        '\n'
        '    return-void\n'
        '.end method',
        data,
    )


def _replace_smali_method(data: str, signature: str, body: str) -> str:
    return re.sub(
        rf'(?ms)^\.method {re.escape(signature)}\n.*?^\.end method',
        f'.method {signature}\n{body}.end method',
        data,
    )


def _empty_map_smali_body() -> str:
    return (
        '    .locals 1\n'
        '\n'
        '    invoke-static {}, Ljava/util/Collections;->emptyMap()Ljava/util/Map;\n'
        '\n'
        '    move-result-object v0\n'
        '\n'
        '    return-object v0\n'
    )


def blob_fixup_apktool_unpack_src(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    run_cmd([
        java_path,
        '-Xmx8g',
        '-jar',
        apktool_path,
        'd',
        file_path,
        '-o',
        tmp_dir,
        '-f',
        '--no-res',
    ])


def blob_fixup_apktool_unpack_full(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    run_cmd([
        java_path,
        '-Xmx8g',
        '-jar',
        apktool_path,
        'd',
        file_path,
        '-o',
        tmp_dir,
        '-f',
    ])


def blob_fixup_apktool_unpack_manifest(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    run_cmd([
        java_path,
        '-Xmx8g',
        '-jar',
        apktool_path,
        'd',
        file_path,
        '-o',
        tmp_dir,
        '-f',
        '-s',
    ])


def blob_fixup_opluscamera_font(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # OEM camera font-NPE neutralizer. The TypeFaceUtil static
    # a(Context)->Typeface path reads OEM font framework state that is absent
    # on LineageOS; return Typeface.DEFAULT instead.
    if tmp_dir is None:
        return

    signature = 'public static a(Landroid/content/Context;)Landroid/graphics/Typeface;'
    body = (
        '    .locals 1\n'
        '\n'
        '    sget-object v0, Landroid/graphics/Typeface;->DEFAULT:Landroid/graphics/Typeface;\n'
        '\n'
        '    return-object v0\n'
    )

    for smali in Path(tmp_dir).glob('smali*/**/*.smali'):
        data = smali.read_text(encoding='utf-8', errors='ignore')
        if '"TypeFaceUtil"' not in data or f'.method {signature}' not in data:
            continue
        fixed = _replace_smali_method(data, signature, body)
        if fixed != data:
            smali.write_text(fixed, encoding='utf-8')
        return


def blob_fixup_opluscamera_blur_seginit_guard(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # Portrait blur initialization can fail when the OEM segmentation stack is
    # incomplete. The app normally dereferences the returned int[] without a
    # null check, crashing on front-camera portrait. Treat a null segInit()
    # result as an unavailable blur engine instead.
    if tmp_dir is None:
        return

    process_smali = next(Path(tmp_dir).glob('smali*/ub/b.smali'), None)
    if process_smali is None:
        raise ValueError('OplusCamera blur process smali not found')

    data = process_smali.read_text(encoding='utf-8', errors='ignore')
    if '/odm/etc/camera/singleblur/personseg.bin' not in data:
        raise ValueError('OplusCamera blur process segInit anchor not found')

    fixed, count = re.subn(
        r'(?s)(invoke-virtual/range \{v1 \.\. v7\}, Lcom/oplus/ocs/camera/OplusBlurPreviewHelper;->segInit\(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;II\)\[I.*?'
        r'move-result-object v0.*?'
        r'sput-object v0, Lub/b;->w:\[I)',
        r'\1'
        '\n\n'
        '    if-nez v0, :cond_codex_blur_seginit_ok\n'
        '\n'
        '    monitor-exit v10\n'
        '\n'
        '    return v12\n'
        '\n'
        '    :cond_codex_blur_seginit_ok',
        data,
        count=1,
    )
    if count != 1:
        raise ValueError('OplusCamera blur process segInit write not patched')
    process_smali.write_text(fixed, encoding='utf-8')

    texture_smali = next(Path(tmp_dir).glob('smali*/wb/k.smali'), None)
    if texture_smali is None:
        raise ValueError('OplusCamera blur texture smali not found')

    data = texture_smali.read_text(encoding='utf-8', errors='ignore')
    if 'initSegForSizeChange, segInit, cost: ' not in data:
        raise ValueError('OplusCamera blur size-change segInit anchor not found')

    fixed, count = re.subn(
        r'(?s)(invoke-virtual/range \{v3 \.\. v9\}, Lcom/oplus/ocs/camera/OplusBlurPreviewHelper;->segInit\(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;II\)\[I.*?'
        r'move-result-object p0.*?'
        r'sput-object p0, Lub/b;->w:\[I)',
        r'\1'
        '\n\n'
        '    if-nez p0, :cond_codex_blur_size_seginit_ok\n'
        '\n'
        '    return-void\n'
        '\n'
        '    :cond_codex_blur_size_seginit_ok',
        data,
        count=1,
    )
    if count != 1:
        raise ValueError('OplusCamera blur size-change segInit write not patched')
    texture_smali.write_text(fixed, encoding='utf-8')


def blob_fixup_strip_oem_permissions(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # Strip undefined OEM permission gates from component declarations while
    # keeping the components registered.
    if tmp_dir is None:
        return

    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    if not manifest.exists():
        return

    data = manifest.read_text(encoding='utf-8')
    fixed = re.sub(
        r'\s+android:permission="(?:oplus|oppo|com\.oplus|com\.oppo|com\.heytap)[^"]*"',
        '',
        data,
    )
    if fixed != data:
        manifest.write_text(fixed, encoding='utf-8')


def blob_fixup_systemuiplugin_plugin_context_inflater(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali' / 'k9' / 'b.smali'
    data = smali.read_text(encoding='utf-8')
    old = """.method public W0(Landroid/content/Context;)Lt4/h;
    .locals 1

    const-string v0, "context"

    invoke-static {p1, v0}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullParameter(Ljava/lang/Object;Ljava/lang/String;)V

    sget-object v0, Lt4/h;->m:Lt4/h;

    if-nez v0, :cond_1

    monitor-enter p0

    :try_start_0
    sget-object v0, Lt4/h;->m:Lt4/h;

    if-nez v0, :cond_0

    new-instance v0, Lt4/h;

    invoke-direct {v0, p1}, Lt4/h;-><init>(Landroid/content/Context;)V

    sput-object v0, Lt4/h;->m:Lt4/h;
    :try_end_0
    .catchall {:try_start_0 .. :try_end_0} :catchall_0

    :cond_0
    monitor-exit p0

    goto :goto_0

    :catchall_0
    move-exception p1

    monitor-exit p0

    throw p1

    :cond_1
    :goto_0
    return-object v0
.end method"""
    new = """.method public W0(Landroid/content/Context;)Lt4/h;
    .locals 2

    const-string v0, "context"

    invoke-static {p1, v0}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullParameter(Ljava/lang/Object;Ljava/lang/String;)V

    sget-object v0, Lt4/h;->m:Lt4/h;

    if-nez v0, :cond_2

    monitor-enter p0

    :try_start_0
    sget-object v0, Lt4/h;->m:Lt4/h;

    if-nez v0, :cond_1

    sget-object v0, Lcom/oplus/systemui/plugins/seedling/plugin/ContextHandler;->Companion:Lcom/oplus/systemui/plugins/seedling/plugin/ContextHandler$Companion;

    invoke-virtual {v0}, Lcom/oplus/systemui/plugins/seedling/plugin/ContextHandler$Companion;->getInstance()Lcom/oplus/systemui/plugins/seedling/plugin/ContextHandler;

    move-result-object v0

    invoke-virtual {v0}, Lcom/oplus/systemui/plugins/seedling/plugin/ContextHandler;->getPluginCtx()Landroid/content/Context;

    move-result-object v1

    if-eqz v1, :cond_0

    move-object p1, v1

    :cond_0
    new-instance v0, Lt4/h;

    invoke-direct {v0, p1}, Lt4/h;-><init>(Landroid/content/Context;)V

    sput-object v0, Lt4/h;->m:Lt4/h;

    :cond_1
    monitor-exit p0

    goto :goto_0

    :catchall_0
    move-exception p1

    monitor-exit p0
    :try_end_0
    .catchall {:try_start_0 .. :try_end_0} :catchall_0

    throw p1

    :cond_2
    :goto_0
    sget-object v0, Lt4/h;->m:Lt4/h;

    return-object v0
.end method"""
    if old in data:
        data = data.replace(old, new, 1)
    elif new not in data:
        pass  # Updated SystemUIPlugin no longer has this old patch point
    smali.write_text(data, encoding='utf-8')

    smali = Path(tmp_dir) / 'smali' / 't4' / 'h.smali'
    data = smali.read_text(encoding='utf-8')
    old = """    invoke-direct {v1, v0}, Lq4/d;-><init>(Landroid/content/Context;)V

    iget-object v2, p0, Lt4/h;->a:Landroid/content/Context;
"""
    new = """    iget-object v2, p0, Lt4/h;->a:Landroid/content/Context;

    invoke-direct {v1, v2}, Lq4/d;-><init>(Landroid/content/Context;)V
"""
    if old in data:
        data = data.replace(old, new, 1)
    elif new not in data:
        pass  # Updated SystemUIPlugin no longer has this old patch point
    old = """    const v3, 0x7f0c008c

    invoke-static {v2, v3, v1}, Landroid/view/View;->inflate(Landroid/content/Context;ILandroid/view/ViewGroup;)Landroid/view/View;

    const/4 v3, 0x0
"""
    new = """    const v3, 0x7f0c008c

    invoke-static {v2}, Landroid/view/LayoutInflater;->from(Landroid/content/Context;)Landroid/view/LayoutInflater;

    move-result-object v8

    const/4 v4, 0x1

    invoke-virtual {v8, v3, v1, v4}, Landroid/view/LayoutInflater;->inflate(ILandroid/view/ViewGroup;Z)Landroid/view/View;

    const/4 v3, 0x0
"""
    if old in data:
        data = data.replace(old, new, 1)
    elif new not in data:
        pass  # Updated SystemUIPlugin no longer has this old patch point
    smali.write_text(data, encoding='utf-8')


def blob_fixup_opluscamera_oppo_component_safe(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    data = manifest.read_text(encoding='utf-8') if manifest.exists() else ''
    permission = '    <uses-permission android:name="oppo.permission.OPPO_COMPONENT_SAFE"/>\n'
    if 'oppo.permission.OPPO_COMPONENT_SAFE' not in data:
        data = data.replace(
            '    <uses-permission android:name="oplus.permission.OPLUS_COMPONENT_SAFE"/>\n',
            '    <uses-permission android:name="oplus.permission.OPLUS_COMPONENT_SAFE"/>\n'
            + permission,
            1,
        )
        manifest.write_text(data, encoding='utf-8')


def blob_fixup_opluscamera_uses_library(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    data = manifest.read_text(encoding='utf-8') if manifest.exists() else ''
    if not data or 'oplus.camera.stubs' in data:
        return

    entry = '        <uses-library android:name="oplus.camera.stubs" android:required="false"/>\n'
    sdk_entry = '        <uses-library android:name="com.oplus.camera.unit.sdk" android:required="false"/>\n'
    if sdk_entry in data:
        data = data.replace(sdk_entry, entry + sdk_entry, 1)
        manifest.write_text(data, encoding='utf-8')
    elif '</application>' in data:
        data = data.replace('</application>', entry + '    </application>', 1)
        manifest.write_text(data, encoding='utf-8')


def blob_fixup_fileencryption_secure_settings_permission(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    data = manifest.read_text(encoding='utf-8') if manifest.exists() else ''
    permissions = (
        'android.permission.USE_BIOMETRIC',
        'android.permission.USE_FINGERPRINT',
        'android.permission.WRITE_SECURE_SETTINGS',
    )
    entries = ''.join(
        f'    <uses-permission android:name="{permission}"/>\n'
        for permission in permissions
        if permission not in data
    )
    if data and entries:
        data = data.replace('<application ', entries + '    <application ', 1)
        manifest.write_text(data, encoding='utf-8')


def blob_fixup_fileencryption_biometric_enrollment_checks(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali/c9/a.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    if not data:
        raise ValueError('FileEncryption biometric helper not found')

    face_body = (
        '    .locals 2\n'
        '\n'
        '    :try_start_0\n'
        '    const-string v0, "face"\n'
        '\n'
        '    invoke-virtual {p0, v0}, Landroid/content/Context;->getSystemService(Ljava/lang/String;)Ljava/lang/Object;\n'
        '\n'
        '    move-result-object p0\n'
        '\n'
        '    instance-of v0, p0, Landroid/hardware/face/FaceManager;\n'
        '\n'
        '    if-eqz v0, :cond_0\n'
        '\n'
        '    check-cast p0, Landroid/hardware/face/FaceManager;\n'
        '\n'
        '    invoke-virtual {p0}, Landroid/hardware/face/FaceManager;->hasEnrolledTemplates()Z\n'
        '\n'
        '    move-result p0\n'
        '\n'
        '    return p0\n'
        '    :try_end_0\n'
        '    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0\n'
        '\n'
        '    :catch_0\n'
        '    move-exception p0\n'
        '\n'
        '    :cond_0\n'
        '    const/4 p0, 0x0\n'
        '\n'
        '    return p0\n'
    )
    fingerprint_body = (
        '    .locals 2\n'
        '\n'
        '    :try_start_0\n'
        '    const-string v0, "fingerprint"\n'
        '\n'
        '    invoke-virtual {p0, v0}, Landroid/content/Context;->getSystemService(Ljava/lang/String;)Ljava/lang/Object;\n'
        '\n'
        '    move-result-object p0\n'
        '\n'
        '    instance-of v0, p0, Landroid/hardware/fingerprint/FingerprintManager;\n'
        '\n'
        '    if-eqz v0, :cond_0\n'
        '\n'
        '    check-cast p0, Landroid/hardware/fingerprint/FingerprintManager;\n'
        '\n'
        '    invoke-virtual {p0}, Landroid/hardware/fingerprint/FingerprintManager;->isHardwareDetected()Z\n'
        '\n'
        '    move-result v0\n'
        '\n'
        '    if-eqz v0, :cond_0\n'
        '\n'
        '    invoke-virtual {p0}, Landroid/hardware/fingerprint/FingerprintManager;->hasEnrolledFingerprints()Z\n'
        '\n'
        '    move-result p0\n'
        '\n'
        '    return p0\n'
        '    :try_end_0\n'
        '    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0\n'
        '\n'
        '    :catch_0\n'
        '    move-exception p0\n'
        '\n'
        '    :cond_0\n'
        '    const/4 p0, 0x0\n'
        '\n'
        '    return p0\n'
    )
    fixed = _replace_smali_method(data, 'public static final b(Landroid/content/Context;)Z', face_body)
    fixed = _replace_smali_method(fixed, 'public static final c(Landroid/content/Context;)Z', fingerprint_body)
    if fixed == data:
        raise ValueError('FileEncryption biometric enrollment checks not patched')
    smali.write_text(fixed, encoding='utf-8')


def blob_fixup_phonemanager_secure_settings_permission(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    data = manifest.read_text(encoding='utf-8') if manifest.exists() else ''
    permission = '    <uses-permission android:name="android.permission.WRITE_SECURE_SETTINGS"/>\n'
    if data and 'android.permission.WRITE_SECURE_SETTINGS' not in data:
        data = data.replace('<application ', permission + '    <application ', 1)
        manifest.write_text(data, encoding='utf-8')


def blob_fixup_ums_activity_watcher_permission(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    data = manifest.read_text(encoding='utf-8') if manifest.exists() else ''
    permission = '    <uses-permission android:name="android.permission.SET_ACTIVITY_WATCHER"/>\n'
    if data and 'android.permission.SET_ACTIVITY_WATCHER' not in data:
        data = data.replace('<application ', permission + '    <application ', 1)
        manifest.write_text(data, encoding='utf-8')


def blob_fixup_phonemanager_settings_category(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    data = manifest.read_text(encoding='utf-8') if manifest.exists() else ''
    if not data:
        return

    old = 'android:value="com.oplus.settings.category.ia.phone_manager"'
    new = 'android:value="com.android.settings.category.ia.more_security_privacy_settings"'
    fixed = data.replace(old, new, 1)
    if fixed != data:
        manifest.write_text(fixed, encoding='utf-8')
    elif new not in data:
        raise ValueError('PhoneManager Settings category metadata not found')


_SETTINGS_CATEGORY_ADVANCED_SECURITY_META = (
    '<meta-data android:name="com.android.settings.category" '
    'android:value="com.android.settings.category.ia.advanced_security"/>'
)


def blob_fixup_aonservice_settings_category(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # AONService's EZ Pay tile declares MANUFACTURER_APPLICATION_SETTING without
    # an AOSP Settings category, so TileUtils can surface it on unrelated pages.
    if tmp_dir is None:
        return

    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    data = manifest.read_text(encoding='utf-8') if manifest.exists() else ''
    if not data or _SETTINGS_CATEGORY_ADVANCED_SECURITY_META in data:
        return

    anchor = (
        '<meta-data android:name="com.android.settings.title" '
        'android:resource="@string/intelligent_perception_title_new"/>'
    )
    if anchor not in data:
        raise ValueError('AONService Settings title metadata not found')

    manifest.write_text(
        data.replace(anchor, anchor + '\n            ' + _SETTINGS_CATEGORY_ADVANCED_SECURITY_META, 1),
        encoding='utf-8',
    )


def blob_fixup_aiunit_settings_category(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # AIUnit's AI Service Engine tile uses the Oplus-only
    # com.android.settings.category.export key, which AOSP TileUtils ignores.
    if tmp_dir is None:
        return

    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    data = manifest.read_text(encoding='utf-8') if manifest.exists() else ''
    if not data or _SETTINGS_CATEGORY_ADVANCED_SECURITY_META in data:
        return

    old = (
        '<meta-data android:name="com.android.settings.category.export" '
        'android:value="com.oplus.settings.category.ia.strengthen_service"/>'
    )
    if old not in data:
        raise ValueError('AIUnit Settings category metadata not found')

    manifest.write_text(data.replace(old, _SETTINGS_CATEGORY_ADVANCED_SECURITY_META, 1), encoding='utf-8')


def blob_fixup_phonemanager_permission_controller_package(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    old = 'com.google.android.permissioncontroller'
    new = 'com.android.permissioncontroller'
    replaced = False
    for path in Path(tmp_dir).glob('**/*'):
        if not path.is_file() or path.suffix not in {'.smali', '.xml'}:
            continue
        data = path.read_text(encoding='utf-8', errors='ignore')
        if old not in data:
            continue
        path.write_text(data.replace(old, new), encoding='utf-8')
        replaced = True

    if not replaced:
        raise ValueError('PhoneManager permission controller package string not found')


def blob_fixup_cryptoeng_permissions_xml(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    path = Path(file_path)
    data = path.read_text(encoding='utf-8')
    fixed = data.replace('\n</permissions>\n\n<permissions>\n', '\n')
    if fixed != data:
        path.write_text(fixed, encoding='utf-8')


def blob_fixup_cryptoeng_init_rc(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    path = Path(file_path)
    data = path.read_text(encoding='utf-8')
    data = data.replace(
        '    mkdir /data/vendor_de/0/cryptoeng 0770 system system encryption=None\n',
        '    mkdir /data/vendor_de/0/cryptoeng 0770 system system encryption=None\n'
        '    restorecon_recursive /data/vendor_de/0/cryptoeng\n',
        1,
    )
    old = (
        '    if [ "$(getprop ro.soc.model)" = "SM6450" ]; then\n'
        '        copy /vendor/etc/oplus_PPID_licenses.pfm /mnt/vendor/persist/data/pfm/licenses/oplus_PPID_licenses.pfm\n'
        '        chmod 0600 /mnt/vendor/persist/data/pfm/licenses/oplus_PPID_licenses.pfm\n'
        '        chown system system /mnt/vendor/persist/data/pfm/licenses/oplus_PPID_licenses.pfm\n'
        '    fi\n'
    )
    fixed = data.replace(old, '')
    if fixed != data:
        path.write_text(fixed, encoding='utf-8')


def blob_fixup_cryptoeng_manifest(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    path = Path(file_path)
    data = path.read_text(encoding='utf-8')
    data = data.replace('<!--\n    <hal format="hidl">', '    <hal format="hidl">')
    data = data.replace('    </hal>\n-->\n    <hal format="aidl">', '    </hal>\n    <hal format="aidl">')
    path.write_text(data, encoding='utf-8')


def blob_fixup_safecenter_receiver_flags(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes2/com/oplus/safecenter/privacy/view/BaseSelfFinishActivity.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    fixed = data.replace(
        '.method protected onCreate(Landroid/os/Bundle;)V\n'
        '    .locals 3\n',
        '.method protected onCreate(Landroid/os/Bundle;)V\n'
        '    .locals 10\n',
        1,
    )
    old = (
        '    const/4 v2, 0x0\n'
        '\n'
        '    invoke-virtual {p0, v0, p1, v1, v2}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;)Landroid/content/Intent;\n'
    )
    new = (
        '    const/4 v2, 0x0\n'
        '\n'
        '    move-object v4, p0\n'
        '\n'
        '    move-object v5, v0\n'
        '\n'
        '    move-object v6, p1\n'
        '\n'
        '    move-object v7, v1\n'
        '\n'
        '    move-object v8, v2\n'
        '\n'
        '    const/4 v9, 0x4\n'
        '\n'
        '    invoke-virtual/range {v4 .. v9}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;I)Landroid/content/Intent;\n'
    )
    fixed = fixed.replace(old, new, 1)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')
    elif 'registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;I)' not in data:
        raise ValueError('SafeCenter receiver flag patch point not found')


def blob_fixup_safecenter_olock_support(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes2/j7/k.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    fixed = _replace_smali_method(
        data,
        'public final J(Landroid/content/Context;)Z',
        '    .locals 2\n'
        '\n'
        '    const-string p0, "OLockManager"\n'
        '\n'
        '    const-string p1, "[isSupportOLock] force enabled for port"\n'
        '\n'
        '    invoke-static {p0, p1}, Lx6/a;->h(Ljava/lang/String;Ljava/lang/String;)V\n'
        '\n'
        '    const/4 v0, 0x1\n'
        '\n'
        '    return v0\n',
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')
    else:
        raise ValueError('SafeCenter OLock support patch point not found')


def blob_fixup_safecenter_olock_theft_dark_theme(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    values_night = Path(tmp_dir) / 'res/values-night/styles.xml'
    data = values_night.read_text(encoding='utf-8') if values_night.exists() else ''
    style = (
        '    <style name="AppTheme.OlockSettingTheme" parent="@style/Theme.COUI.Dark">\n'
        '        <item name="android:windowBackground">?couiColorBackgroundWithCard</item>\n'
        '        <item name="android:statusBarColor">?couiColorBackgroundWithCard</item>\n'
        '        <item name="android:navigationBarColor">?couiColorBackgroundWithCard</item>\n'
        '        <item name="android:isLightTheme">false</item>\n'
        '        <item name="android:windowDisablePreview">true</item>\n'
        '        <item name="enableFollowSystemForceDarkRank">true</item>\n'
        '        <item name="preferenceTheme">@style/PreferenceThemeOverlay.COUITheme</item>\n'
        '        <item name="viewInflaterClass">@string/coui_view_inflater_class</item>\n'
        '        <item name="windowActionBar">false</item>\n'
        '        <item name="windowNoTitle">true</item>\n'
        '        <item name="windowPreviewType">0</item>\n'
        '    </style>\n'
    )
    if 'name="AppTheme.OlockSettingTheme"' not in data:
        fixed = data.replace('    <style name="Theme.AppCompat.DayNight"', style + '    <style name="Theme.AppCompat.DayNight"', 1)
        if fixed == data:
            raise ValueError('SafeCenter OLock night theme patch point not found')
        values_night.write_text(fixed, encoding='utf-8')



def blob_fixup_securitypermission_safe_permissions(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    data = manifest.read_text(encoding='utf-8')
    permissions = [
        'oplus.permission.OPLUS_COMPONENT_SAFE',
        'oppo.permission.OPPO_COMPONENT_SAFE',
        'com.oplus.permission.safe.AI_APP',
        'com.oplus.permission.safe.APP_MANAGER',
        'com.oplus.permission.safe.ASSISTANT',
        'com.oplus.permission.safe.AUTHENTICATE',
        'com.oplus.permission.safe.BACKUP',
        'com.oplus.permission.safe.BLUETOOTH',
        'com.oplus.permission.safe.CAMERA',
        'com.oplus.permission.safe.CAR_LINK',
        'com.oplus.permission.safe.CONNECTIVITY',
        'com.oplus.permission.safe.IOT',
        'com.oplus.permission.safe.LOG',
        'com.oplus.permission.safe.MEDIA',
        'com.oplus.permission.safe.PERSISTENT',
        'com.oplus.permission.safe.PHONE',
        'com.oplus.permission.safe.PICTURE',
        'com.oplus.permission.safe.POWER',
        'com.oplus.permission.safe.PRIVATE',
        'com.oplus.permission.safe.PROTECT',
        'com.oplus.permission.safe.READ_COMMON',
        'com.oplus.permission.safe.SAFE_MANAGER',
        'com.oplus.permission.safe.SAU',
        'com.oplus.permission.safe.SECURITY',
        'com.oplus.permission.safe.SETTINGS',
        'com.oplus.permission.safe.SETTINGS_SEARCH',
        'com.oplus.permission.safe.WINDOW',
        'com.oppo.permission.safe.AI_APP',
        'com.oppo.permission.safe.AUTHENTICATE',
        'com.oppo.permission.safe.CAMERA',
        'com.oppo.permission.safe.IOT',
        'com.oppo.permission.safe.PRIVATE',
        'com.oppo.permission.safe.SAU',
        'com.oppo.permission.safe.SECURITY',
        'oplus.permission.settings.LAUNCH_FOR_EXPORT',
        'com.oplus.metis.factdata.permission.DATABASE',
        'com.oplus.flashback.permission.FLASH_VIEWS_SERVICE',
        'heytap.speechassist.permission.ACTIVATE_SPEECH_ASSIST',
    ]
    block = ''.join(
        f'    <permission android:name="{permission}" android:protectionLevel="signature|privileged" />\n'
        for permission in permissions
        if f'<permission android:name="{permission}"' not in data
    )
    if block:
        data = data.replace('<application ', block + '\n    <application ', 1)
        manifest.write_text(data, encoding='utf-8')


def blob_fixup_oppogallery_receiver_flags(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes8/com/oplus/aiunit/vision/ey.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    old = (
        '    iget v6, v0, Lcom/oplus/aiunit/vision/gy;->c:I\n'
        '\n'
        '    invoke-virtual/range {v1 .. v6}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;I)Landroid/content/Intent;\n'
    )
    new = (
        '    iget v6, v0, Lcom/oplus/aiunit/vision/gy;->c:I\n'
        '\n'
        '    and-int/lit8 v6, v6, -0x3\n'
        '\n'
        '    or-int/lit8 v6, v6, 0x4\n'
        '\n'
        '    invoke-virtual/range {v1 .. v6}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;I)Landroid/content/Intent;\n'
    )
    fixed = data.replace(old, new)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')

    smali = Path(tmp_dir) / 'smali_classes9/com/oplus/gallery/foundation/uikit/broadcast/bus/ActionReceiver.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    old = (
        '    iget v7, v0, Lcom/oplus/aiunit/vision/a10;->c:I\n'
        '\n'
        '    .line 62\n'
        '    .line 63\n'
        '    move-object v3, p0\n'
        '\n'
        '    .line 64\n'
        '    invoke-virtual/range {v2 .. v7}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;I)Landroid/content/Intent;\n'
    )
    new = (
        '    iget v7, v0, Lcom/oplus/aiunit/vision/a10;->c:I\n'
        '\n'
        '    and-int/lit8 v7, v7, -0x3\n'
        '\n'
        '    or-int/lit8 v7, v7, 0x4\n'
        '\n'
        '    .line 62\n'
        '    .line 63\n'
        '    move-object v3, p0\n'
        '\n'
        '    .line 64\n'
        '    invoke-virtual/range {v2 .. v7}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;I)Landroid/content/Intent;\n'
    )
    fixed = data.replace(old, new)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')
    elif smali.exists() and 'or-int/lit8 v7, v7, 0x4' not in data:
        raise ValueError('OppoGallery2 ActionReceiver receiver flag patch point not found')


def blob_fixup_oppogallery_wallpaper_attach_intent(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes10/com/oplus/gallery/pictureeditorpage/PictureEditorDM.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    replacement = (
        '.method public final a(Landroid/app/Activity;Landroid/net/Uri;)V\n'
        '    .locals 3\n'
        '\n'
        '    const-string p0, "activity"\n'
        '\n'
        '    invoke-static {p1, p0}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullParameter(Ljava/lang/Object;Ljava/lang/String;)V\n'
        '\n'
        '    const-string p0, "pickedItem"\n'
        '\n'
        '    invoke-static {p2, p0}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullParameter(Ljava/lang/Object;Ljava/lang/String;)V\n'
        '\n'
        '    new-instance v0, Landroid/content/Intent;\n'
        '\n'
        '    const-string v1, "android.intent.action.ATTACH_DATA"\n'
        '\n'
        '    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V\n'
        '\n'
        '    const-string v1, "image/*"\n'
        '\n'
        '    invoke-virtual {v0, p2, v1}, Landroid/content/Intent;->setDataAndType(Landroid/net/Uri;Ljava/lang/String;)Landroid/content/Intent;\n'
        '\n'
        '    const/4 v2, 0x1\n'
        '\n'
        '    invoke-virtual {v0, v2}, Landroid/content/Intent;->setFlags(I)Landroid/content/Intent;\n'
        '\n'
        '    const-string v2, "mimeType"\n'
        '\n'
        '    invoke-virtual {v0, v2, v1}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;\n'
        '\n'
        '    invoke-virtual {p1, v0}, Landroid/app/Activity;->startActivity(Landroid/content/Intent;)V\n'
        '\n'
        '    return-void\n'
        '.end method\n'
    )
    fixed, count = re.subn(
        r'\.method public final a\(Landroid/app/Activity;Landroid/net/Uri;\)V\n.*?\.end method',
        replacement,
        data,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise ValueError('OppoGallery2 wallpaper attach intent patch point not found')
    smali.write_text(fixed, encoding='utf-8')


def blob_fixup_oppogallery_safe_box_custom_flag(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = next(
        (
            path
            for path in Path(tmp_dir).glob('smali*/com/oplus/aiunit/vision/mn4.smali')
            if '.method public static final f(Ljava/lang/String;ZZ)Z' in path.read_text(encoding='utf-8')
        ),
        None,
    )
    if smali is None:
        pattern = re.compile(
            r'(    const-string (?P<key>[vp]\d+), "feature_is_support_user_custom_safe_box"\n'
            r'(?:\n|    \.line \d+\n)*'
            r'    const/4 (?P<flags>[vp]\d+), 0x6\n'
            r'(?:\n|    \.line \d+\n)*)'
            r'    invoke-static \{(?P=key), (?P<result>[vp]\d+), (?P=flags)\}, Lcom/oplus/aiunit/vision/c25;->d\(Ljava/lang/String;ZI\)Z\n'
            r'(?:\n|    \.line \d+\n)*'
            r'    move-result (?P=result)\n'
        )
        for smali in Path(tmp_dir).glob('smali*/com/oplus/aiunit/vision/*.smali'):
            data = smali.read_text(encoding='utf-8')
            if 'feature_is_support_user_custom_safe_box' not in data:
                continue
            fixed = pattern.sub(r'\1    const/4 \g<result>, 0x1\n', data, count=1)
            if fixed != data:
                smali.write_text(fixed, encoding='utf-8')
                return
            if 'feature_is_support_user_custom_safe_box' in data and '    const/4 p1, 0x1\n\n    if-nez p1,' in data:
                return
        raise ValueError('OppoGallery2 SafeBox config patch point not found')
    data = smali.read_text(encoding='utf-8')
    pattern = re.compile(
        r'(\.method public static final f\(Ljava/lang/String;ZZ\)Z\n'
        r'    \.locals 3\n'
        r'.*?'
        r'    invoke-static \{p0, v0\}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullParameter\(Ljava/lang/Object;Ljava/lang/String;\)V\n'
        r'\n)'
        r'(    \.line 4\n'
        r'    \.line 5\n'
        r'    \.line 6\n'
        r'    sget-object v0, Lcom/oplus/aiunit/vision/fr4;->a:Landroid/content/Context;\n)',
        re.DOTALL,
    )
    insert = (
        r'\1'
        '    const-string v0, "feature_is_support_user_custom_safe_box"\n'
        '\n'
        '    invoke-static {p0, v0}, Lkotlin/jvm/internal/Intrinsics;->areEqual(Ljava/lang/Object;Ljava/lang/Object;)Z\n'
        '\n'
        '    move-result v0\n'
        '\n'
        '    if-eqz v0, :oplus_safe_box_config_default_f\n'
        '\n'
        '    const/4 p0, 0x1\n'
        '\n'
        '    return p0\n'
        '\n'
        '    :oplus_safe_box_config_default_f\n'
        '\n'
        '    const-string v0, "configId"\n'
        '\n'
        r'\2'
    )
    fixed, count = pattern.subn(insert, data, count=1)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')
    elif ':oplus_safe_box_config_default_f' not in data:
        raise ValueError('OppoGallery2 SafeBox config patch point not found')


def blob_fixup_oppogallery_google_photos_consent_on_verify_failure(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes8/com/oplus/aiunit/vision/bi8$a.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    old = (
        '    if-eqz p1, :cond_0\n'
        '\n'
        '    .line 14\n'
        '    .line 15\n'
        '    sget-object v3, Lcom/oplus/aiunit/vision/we1;->a:Lcom/oplus/aiunit/vision/we1;\n'
    )
    new = (
        '    nop\n'
        '\n'
        '    .line 14\n'
        '    .line 15\n'
        '    sget-object v3, Lcom/oplus/aiunit/vision/we1;->a:Lcom/oplus/aiunit/vision/we1;\n'
    )
    fixed = data.replace(old, new, 1)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')
    elif '    nop\n\n    .line 14\n    .line 15\n    sget-object v3, Lcom/oplus/aiunit/vision/we1;->a:Lcom/oplus/aiunit/vision/we1;\n' not in data:
        return


def blob_fixup_oppogallery_google_photos_launch_consent_after_verify_failure(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes8/com/oplus/gallery/framework/abilities/gcloudsync/GCloudSyncStatusManager$c.smali'
    if not smali.exists():
        return

    data = smali.read_text(encoding='utf-8')
    marker = re.compile(
        r'(    invoke-static \{v0, v1, p0\}, Lcom/oplus/aiunit/vision/ro8;->q\(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;\)V\n'
        r'(?:\n|    \.line \d+\n)*)'
        r'(    :cond_[0-9a-f]+\n)'
    )
    insert = (
        r'\1'
        '    sget-object v2, Lcom/oplus/aiunit/vision/we1;->a:Lcom/oplus/aiunit/vision/we1;\n'
        '\n'
        '    invoke-static {}, Lkotlinx/coroutines/Dispatchers;->getIO()Lkotlinx/coroutines/CoroutineDispatcher;\n'
        '\n'
        '    move-result-object v3\n'
        '\n'
        '    const/4 v4, 0x0\n'
        '\n'
        '    new-instance v5, Lcom/oplus/aiunit/vision/ej8;\n'
        '\n'
        '    sget-object v1, Lcom/oplus/gallery/business_lib/cloudsync/EntryPoint;->SETTINGS:Lcom/oplus/gallery/business_lib/cloudsync/EntryPoint;\n'
        '\n'
        '    invoke-direct {v5, v1, v4}, Lcom/oplus/aiunit/vision/ej8;-><init>(Lcom/oplus/gallery/business_lib/cloudsync/EntryPoint;Lkotlin/coroutines/Continuation;)V\n'
        '\n'
        '    const/4 v6, 0x2\n'
        '\n'
        '    const/4 v7, 0x0\n'
        '\n'
        '    invoke-static/range {v2 .. v7}, Lkotlinx/coroutines/BuildersKt;->launch$default(Lkotlinx/coroutines/CoroutineScope;Lkotlin/coroutines/CoroutineContext;Lkotlinx/coroutines/CoroutineStart;Lkotlin/jvm/functions/Function2;ILjava/lang/Object;)Lkotlinx/coroutines/Job;\n'
        '\n'
        r'\2'
    )
    fixed, count = marker.subn(insert, data, count=1)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')
    elif 'Lcom/oplus/gallery/business_lib/cloudsync/EntryPoint;->SETTINGS:Lcom/oplus/gallery/business_lib/cloudsync/EntryPoint;' not in data:
        return


def blob_fixup_oppogallery_hide_google_photos_backup_settings(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    # Hide the photo-page overflow entry on newer Gallery builds. The older
    # settings-only patch below does not catch this 16.0.8 menu path.
    smali = Path(tmp_dir) / 'smali_classes10/com/oplus/aiunit/vision/g0i.smali'
    if smali.exists():
        data = smali.read_text(encoding='utf-8')
        marker = (
            '    sget v1, Lcom/oplus/gallery/photo_page/R$id;->action_backup_to_cloud:I\n'
            '\n'
            '    .line 532\n'
            '    .line 533\n'
            '    const-wide/high16 v3, 0x4000000000000000L    # 2.0\n'
            '\n'
            '    .line 534\n'
            '    .line 535\n'
            '    const-string v2, "action_backup_to_cloud"\n'
            '\n'
            '    .line 536\n'
            '    .line 537\n'
            '    invoke-static/range {v0 .. v6}, Lcom/oplus/aiunit/vision/g0i;->a(Ljava/util/LinkedHashMap;ILjava/lang/String;JZZ)V\n'
        )
        replacement = (
            marker +
            '\n'
            '    sget v1, Lcom/oplus/gallery/photo_page/R$id;->action_backup_to_cloud:I\n'
            '\n'
            '    invoke-static {v1}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;\n'
            '\n'
            '    move-result-object v1\n'
            '\n'
            '    invoke-virtual {v0, v1}, Ljava/util/LinkedHashMap;->remove(Ljava/lang/Object;)Ljava/lang/Object;\n'
        )
        if marker in data and 'LinkedHashMap;->remove(Ljava/lang/Object;)Ljava/lang/Object;' not in data:
            smali.write_text(data.replace(marker, replacement, 1), encoding='utf-8')

    smali = Path(tmp_dir) / 'smali_classes10/com/oplus/aiunit/vision/urh.smali'
    if smali.exists():
        data = smali.read_text(encoding='utf-8')
        if '.method public m()Z' not in data:
            insert = (
                '\n'
                '.method public m()Z\n'
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n'
                '.end method\n'
            )
            data = data.replace('\n.method public n(Lcom/oplus/gallery/foundation/uikit/responsiveui/AppUiResponder$a;)V', insert + '\n.method public n(Lcom/oplus/gallery/foundation/uikit/responsiveui/AppUiResponder$a;)V', 1)
            smali.write_text(data, encoding='utf-8')

    for smali in glob.glob(str(Path(tmp_dir) / 'smali*/com/oplus/gallery/settingpage/SettingsActivity$SettingFragment.smali')):
        data = Path(smali).read_text(encoding='utf-8')
        if ':oplus_hide_google_photos_backup_settings_done' in data:
            return
        marker = re.search(
            r'(?ms)^(    :cond_1\n'
            r'    :goto_0\n'
            r'    iget-object v0, v1, Lcom/oplus/gallery/settingpage/SettingsActivity\$SettingFragment;->[a-zA-Z0-9]+:Landroidx/preference/PreferenceScreen;\n'
            r'\n'
            r'    \.line \d+\n'
            r'    \.line \d+\n'
            r'    const-string v3, "pref_category_key_sending"\n)',
            data,
        )
        if not marker:
            continue
        screen_load = re.search(
            r'    iget-object v0, v1, Lcom/oplus/gallery/settingpage/SettingsActivity\$SettingFragment;->[a-zA-Z0-9]+:Landroidx/preference/PreferenceScreen;\n',
            marker.group(1),
        ).group(0)
        insert = (
            marker.group(1).replace('    const-string v3, "pref_category_key_sending"\n', '')
            + '    if-eqz v0, :oplus_hide_google_photos_backup_settings_done\n'
            + '\n'
            + '    const-string v3, "pref_category_key_cloud_sync"\n'
            + '\n'
            + '    invoke-virtual {v0, v3}, Landroidx/preference/PreferenceGroup;->removePreferenceRecursively(Ljava/lang/CharSequence;)Z\n'
            + '\n'
            + '    const-string v3, "pref_category_cloud_sync_key"\n'
            + '\n'
            + '    invoke-virtual {v0, v3}, Landroidx/preference/PreferenceGroup;->removePreferenceRecursively(Ljava/lang/CharSequence;)Z\n'
            + '\n'
            + '    const-string v3, "pref_key_auto_sync_2"\n'
            + '\n'
            + '    invoke-virtual {v0, v3}, Landroidx/preference/PreferenceGroup;->removePreferenceRecursively(Ljava/lang/CharSequence;)Z\n'
            + '\n'
            + '    const-string v3, "pref_category_key_cloud_storage_space"\n'
            + '\n'
            + '    invoke-virtual {v0, v3}, Landroidx/preference/PreferenceGroup;->removePreferenceRecursively(Ljava/lang/CharSequence;)Z\n'
            + '\n'
            + '    :oplus_hide_google_photos_backup_settings_done\n'
            + screen_load
            + '\n'
            + '    const-string v3, "pref_category_key_sending"\n'
        )
        fixed = data[:marker.start()] + insert + data[marker.end():]
        Path(smali).write_text(fixed, encoding='utf-8')
        return


def blob_fixup_stdid_receiver_flags(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali/com/oplus/stdid/AppApplication.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    old = (
        '.method public final onCreate()V\n'
        '    .locals 5\n'
    )
    new = (
        '.method public final onCreate()V\n'
        '    .locals 10\n'
    )
    fixed = data.replace(old, new, 1)
    old = (
        '    invoke-virtual {p0, v4, v0}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;)Landroid/content/Intent;\n'
    )
    new = (
        '    move-object v5, v4\n'
        '\n'
        '    move-object v4, p0\n'
        '\n'
        '    move-object v6, v0\n'
        '\n'
        '    move-object v7, v1\n'
        '\n'
        '    move-object v8, v1\n'
        '\n'
        '    const/4 v9, 0x4\n'
        '\n'
        '    invoke-virtual/range {v4 .. v9}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;I)Landroid/content/Intent;\n'
    )
    fixed = fixed.replace(old, new, 1)
    old = (
        '    invoke-virtual {p0, v4, v0, v2, v1}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;)Landroid/content/Intent;\n'
    )
    new = (
        '    move-object v5, v4\n'
        '\n'
        '    move-object v4, p0\n'
        '\n'
        '    move-object v6, v0\n'
        '\n'
        '    move-object v7, v2\n'
        '\n'
        '    move-object v8, v1\n'
        '\n'
        '    const/4 v9, 0x4\n'
        '\n'
        '    invoke-virtual/range {v4 .. v9}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;I)Landroid/content/Intent;\n'
    )
    fixed = fixed.replace(old, new, 1)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_oppogallery_system_share_helper(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # Use Gallery's existing system-share branch instead of the OnePlus custom
    # share page. This preserves Gallery's own media path -> content URI/MIME
    # conversion before Android's platform chooser is opened.
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes8' / 'com' / 'oplus' / 'aiunit' / 'vision' / 'x7m.smali'
    if not smali.exists():
        raise ValueError('OppoGallery2 ShareHelper smali not found')

    data = smali.read_text(encoding='utf-8', errors='ignore')
    old = (
        '    sget-object v2, Lcom/oplus/aiunit/vision/ci8;->m0:Lkotlin/Lazy;\n'
        '\n'
        '    .line 40\n'
        '    .line 41\n'
        '    invoke-interface {v2}, Lkotlin/Lazy;->getValue()Ljava/lang/Object;\n'
        '\n'
        '    .line 42\n'
        '    .line 43\n'
        '    .line 44\n'
        '    move-result-object v2\n'
        '\n'
        '    .line 45\n'
        '    check-cast v2, Ljava/lang/Boolean;\n'
        '\n'
        '    .line 46\n'
        '    .line 47\n'
        '    invoke-virtual {v2}, Ljava/lang/Boolean;->booleanValue()Z\n'
        '\n'
        '    .line 48\n'
        '    .line 49\n'
        '    .line 50\n'
        '    move-result v2\n'
        '\n'
        '    .line 51\n'
        '    const/4 v3, 0x0\n'
        '\n'
        '    .line 52\n'
        '    if-nez v2, :cond_2\n'
    )
    new = (
        '    const/4 v3, 0x0\n'
        '\n'
        '    goto :cond_2\n'
    )
    fixed = data.replace(old, new, 1)
    if fixed == data:
        raise ValueError('OppoGallery2 ShareHelper system-share patch point not found')

    uri_body = (
        '    .locals 5\n'
        '\n'
        '    const-string v0, "<this>"\n'
        '\n'
        '    invoke-static {p0, v0}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullParameter(Ljava/lang/Object;Ljava/lang/String;)V\n'
        '\n'
        '    invoke-virtual {p0}, Lcom/oplus/aiunit/vision/rfg;->f()Lcom/oplus/gallery/business_lib/model/data/base/MediaObject;\n'
        '\n'
        '    move-result-object v0\n'
        '\n'
        '    instance-of v1, v0, Lcom/oplus/aiunit/vision/ymd;\n'
        '\n'
        '    if-eqz v1, :cond_fallback\n'
        '\n'
        '    check-cast v0, Lcom/oplus/aiunit/vision/ymd;\n'
        '\n'
        '    invoke-virtual {v0}, Lcom/oplus/aiunit/vision/ymd;->x()Ljava/lang/String;\n'
        '\n'
        '    move-result-object v0\n'
        '\n'
        '    if-eqz v0, :cond_fallback\n'
        '\n'
        '    invoke-virtual {v0}, Ljava/lang/String;->length()I\n'
        '\n'
        '    move-result v1\n'
        '\n'
        '    if-lez v1, :cond_fallback\n'
        '\n'
        '    sget-object v1, Lcom/oplus/aiunit/vision/s55;->a:Landroid/content/Context;\n'
        '\n'
        '    if-eqz v1, :cond_fallback\n'
        '\n'
        '    new-instance v2, Lcom/oplus/aiunit/vision/mj8;\n'
        '\n'
        '    invoke-direct {v2, v0}, Lcom/oplus/aiunit/vision/mj8;-><init>(Ljava/lang/String;)V\n'
        '\n'
        '    const/4 v0, 0x0\n'
        '\n'
        '    new-array v0, v0, [Ljava/lang/String;\n'
        '\n'
        '    invoke-static {v1, v2, v0}, Lcom/oplus/gallery/foundation/fileaccess/GalleryFileProvider$a;->e(Landroid/content/Context;Lcom/oplus/aiunit/vision/mj8;[Ljava/lang/String;)Landroid/net/Uri;\n'
        '\n'
        '    move-result-object v0\n'
        '\n'
        '    return-object v0\n'
        '\n'
        '    :cond_fallback\n'
        '    invoke-static {p0}, Lcom/oplus/aiunit/vision/rkp;->i(Lcom/oplus/aiunit/vision/rfg;)Z\n'
        '\n'
        '    move-result v0\n'
        '\n'
        '    const-string v1, "external_primary"\n'
        '\n'
        '    if-eqz v0, :cond_0\n'
        '\n'
        '    iget-object p0, p0, Lcom/oplus/aiunit/vision/rfg;->b:Ljava/lang/String;\n'
        '\n'
        '    const/4 v0, 0x1\n'
        '\n'
        '    invoke-static {v0, p0, v1}, Lcom/oplus/aiunit/vision/ipd;->i(ILjava/lang/String;Ljava/lang/String;)Landroid/net/Uri;\n'
        '\n'
        '    move-result-object p0\n'
        '\n'
        '    goto :goto_0\n'
        '\n'
        '    :cond_0\n'
        '    invoke-static {p0}, Lcom/oplus/aiunit/vision/rkp;->j(Lcom/oplus/aiunit/vision/rfg;)Z\n'
        '\n'
        '    move-result v0\n'
        '\n'
        '    if-eqz v0, :cond_1\n'
        '\n'
        '    iget-object p0, p0, Lcom/oplus/aiunit/vision/rfg;->b:Ljava/lang/String;\n'
        '\n'
        '    const/4 v0, 0x3\n'
        '\n'
        '    invoke-static {v0, p0, v1}, Lcom/oplus/aiunit/vision/ipd;->i(ILjava/lang/String;Ljava/lang/String;)Landroid/net/Uri;\n'
        '\n'
        '    move-result-object p0\n'
        '\n'
        '    goto :goto_0\n'
        '\n'
        '    :cond_1\n'
        '    const/4 p0, 0x0\n'
        '\n'
        '    :goto_0\n'
        '    return-object p0\n'
    )
    before_uri = fixed
    fixed = _replace_smali_method(
        fixed,
        'public static b(Lcom/oplus/aiunit/vision/rfg;)Landroid/net/Uri;',
        uri_body,
    )
    if fixed == before_uri:
        raise ValueError('OppoGallery2 ShareHelper URI patch point not found')
    smali.write_text(fixed, encoding='utf-8')


def blob_fixup_oppogallery_op15_native_libs(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    data = manifest.read_text(encoding='utf-8') if manifest.exists() else ''
    old = [
        '        <uses-native-library android:name="/odm/lib64/aiboost/libaiboost.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/aiboost/libaiboost_qnn_external_delegate.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/aiboost/libQnnHtp.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/aiboost/libQnnHtpPrepare.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/aiboost/libQnnHtpV75Stub.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/aiboost/libQnnSystem.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/aiboost/libtransformer_lite.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/Skel_signed/aiboost/libQnnHtpV75Skel.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/aiboost/Skel_unsigned/libQnnHtpV75Skel.so" android:required="false"/>\n',
    ]
    new = [
        '        <uses-native-library android:name="/odm/lib64/libQnnHtp.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/libQnnHtpPrepare.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/libQnnHtpV81Stub.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/libQnnHtpV81CalculatorStub.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/libQnnSaver.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/libQnnSystem.so" android:required="false"/>\n',
    ]

    fixed = data
    anchor = ''.join(line for line in old if line in fixed)
    if anchor:
        fixed = fixed.replace(anchor, ''.join(new))
    elif new[-1] not in fixed:
        insert_after = '        <uses-native-library android:name="libOpenCL.so" android:required="true"/>\n'
        fixed = fixed.replace(insert_after, insert_after + ''.join(new))

    if fixed != data:
        manifest.write_text(fixed, encoding='utf-8')

    lib_dir = Path(tmp_dir) / 'lib/arm64-v8a'
    lib_dir.mkdir(parents=True, exist_ok=True)
    source_dir = Path(__file__).resolve().parent / 'configs/lib64'
    for lib in (
        'libQnnHtp.so',
        'libQnnHtpPrepare.so',
        'libQnnHtpV81Stub.so',
        'libQnnHtpV81CalculatorStub.so',
        'libQnnSaver.so',
        'libQnnSystem.so',
    ):
        shutil.copy2(source_dir / lib, lib_dir / lib)


def blob_fixup_oppogallery_popup_enter(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes5/com/coui/appcompat/poplist/COUIPopupMenuRootView.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    old = (
        '    iget-object p0, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mController:Lcom/coui/appcompat/poplist/BasePopupMenuAnimationController;\n'
        '\n'
        '    .line 22\n'
        '    .line 23\n'
        '    invoke-virtual {p0}, Lcom/coui/appcompat/poplist/BasePopupMenuAnimationController;->startMainMenuEnter()V\n'
    )
    new = (
        '    iget-object p0, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mController:Lcom/coui/appcompat/poplist/BasePopupMenuAnimationController;\n'
        '\n'
        '    .line 22\n'
        '    .line 23\n'
        '    const/4 v1, 0x0\n'
        '\n'
        '    invoke-virtual {p0, v1}, Lcom/coui/appcompat/poplist/BasePopupMenuAnimationController;->startMainMenuEnter(Z)V\n'
    )
    fixed = data.replace(old, new, 1)
    old = (
        '    .line 6\n'
        '    :cond_0\n'
        '    invoke-virtual {v0}, Lcom/coui/appcompat/poplist/BasePopupMenuAnimationController;->startMainMenuEnter()V\n'
    )
    new = (
        '    .line 6\n'
        '    :cond_0\n'
        '    const/4 p0, 0x0\n'
        '\n'
        '    invoke-virtual {v0, p0}, Lcom/coui/appcompat/poplist/BasePopupMenuAnimationController;->startMainMenuEnter(Z)V\n'
    )
    fixed = fixed.replace(old, new, 1)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_oppogallery_popup_width(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes5/com/coui/appcompat/poplist/COUIPopupListWindow.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    old = (
        '    invoke-static {v1, v0}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;)I\n'
        '\n'
        '    .line 47\n'
        '    .line 48\n'
        '    .line 49\n'
        '    iget-object v0, p0, Lcom/coui/appcompat/poplist/COUIPopupListWindow;->mMainMenuAdapter:Lcom/coui/appcompat/poplist/DefaultAdapter;\n'
    )
    new = (
        '    invoke-static {v1, v0}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;)I\n'
        '\n'
        '    move p0, v2\n'
        '\n'
        '    return p0\n'
        '\n'
        '    .line 47\n'
        '    .line 48\n'
        '    .line 49\n'
        '    iget-object v0, p0, Lcom/coui/appcompat/poplist/COUIPopupListWindow;->mMainMenuAdapter:Lcom/coui/appcompat/poplist/DefaultAdapter;\n'
    )
    fixed = data.replace(old, new)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_oppogallery_popup_visibility(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes5/com/coui/appcompat/poplist/COUIPopupListWindow.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    fixed = data.replace(
        '    iget-object p2, p0, Lcom/coui/appcompat/poplist/COUIPopupListWindow;->mContentView:Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;\n'
        '\n'
        '    invoke-virtual {p2}, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->showMainMenu()V\n'
        '\n'
        '    goto :goto_4\n',
        '    iget-object p2, p0, Lcom/coui/appcompat/poplist/COUIPopupListWindow;->mContentView:Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;\n'
        '\n'
        '    invoke-virtual {p2}, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->showMainMenu()V\n'
        '\n'
        '    invoke-virtual {p0, v2}, Landroid/widget/PopupWindow;->setTouchable(Z)V\n'
        '\n'
        '    invoke-virtual {p0, v2}, Landroid/widget/PopupWindow;->setFocusable(Z)V\n'
        '\n'
        '    invoke-virtual {p0}, Landroid/widget/PopupWindow;->update()V\n'
        '\n'
        '    goto :goto_4\n',
    )
    fixed = fixed.replace(
        '    invoke-super {p0, p2, v3, v3, v3}, Landroid/widget/PopupWindow;->showAtLocation(Landroid/view/View;III)V\n',
        '    invoke-super {p0, p2, v3, v3, v3}, Landroid/widget/PopupWindow;->showAtLocation(Landroid/view/View;III)V\n'
        '\n'
        '    invoke-virtual {p0, v2}, Landroid/widget/PopupWindow;->setTouchable(Z)V\n'
        '\n'
        '    invoke-virtual {p0, v2}, Landroid/widget/PopupWindow;->setFocusable(Z)V\n'
        '\n'
        '    invoke-virtual {p0}, Landroid/widget/PopupWindow;->update()V\n',
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_oppogallery_theme_fallbacks(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes7/com/oplus/aiunit/vision/ho4.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    fixed = _replace_smali_method(
        data,
        'public static final a(Landroid/content/res/Configuration;)I',
        '    .locals 1\n'
        '\n'
        '    const/4 v0, -0x1\n'
        '\n'
        '    return v0\n',
    )
    fixed = _replace_smali_method(
        fixed,
        'public static final b(Landroid/content/res/Configuration;)I',
        '    .locals 1\n'
        '\n'
        '    const/4 v0, -0x1\n'
        '\n'
        '    return v0\n',
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')

    smali = Path(tmp_dir) / 'smali_classes5/com/coui/appcompat/view/ViewNative.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    fixed = _replace_smali_method(
        data,
        'public static setScrollX(Landroid/view/View;I)V',
        '    .locals 0\n'
        '\n'
        '    invoke-virtual {p0, p1}, Landroid/view/View;->setScrollX(I)V\n'
        '\n'
        '    return-void\n',
    )
    fixed = _replace_smali_method(
        fixed,
        'public static setScrollY(Landroid/view/View;I)V',
        '    .locals 0\n'
        '\n'
        '    invoke-virtual {p0, p1}, Landroid/view/View;->setScrollY(I)V\n'
        '\n'
        '    return-void\n',
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')

    smali = Path(tmp_dir) / 'smali_classes5/com/coui/appcompat/theme/COUIThemeOverlay.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    fixed = _replace_smali_method(
        data,
        'private canReachBaseConfiguration()Z',
        '    .locals 1\n'
        '\n'
        '    const/4 v0, 0x0\n'
        '\n'
        '    return v0\n',
    )
    fixed = _replace_smali_method(
        fixed,
        'private getExtraConfig(Landroid/content/res/Configuration;)Loplus/content/res/OplusExtraConfiguration;',
        '    .locals 1\n'
        '\n'
        '    const/4 v0, 0x0\n'
        '\n'
        '    return-object v0\n',
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_oppogallery_popup_text_colors(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes5/com/coui/appcompat/preference/COUIPreferenceUtils.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    fixed = _replace_smali_method(
        data,
        'public static bindAssignmentView(Landroidx/preference/PreferenceViewHolder;Ljava/lang/CharSequence;I)V',
        '    .locals 2\n'
        '\n'
        '    sget v0, Lcom/support/preference/R$id;->assignment:I\n'
        '\n'
        '    invoke-virtual {p0, v0}, Landroidx/preference/PreferenceViewHolder;->findViewById(I)Landroid/view/View;\n'
        '\n'
        '    move-result-object p0\n'
        '\n'
        '    check-cast p0, Landroid/widget/TextView;\n'
        '\n'
        '    if-eqz p0, :cond_2\n'
        '\n'
        '    invoke-static {p1}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z\n'
        '\n'
        '    move-result v0\n'
        '\n'
        '    if-nez v0, :cond_1\n'
        '\n'
        '    invoke-virtual {p0, p1}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V\n'
        '\n'
        '    const/4 p1, 0x0\n'
        '\n'
        '    invoke-virtual {p0, p1}, Landroid/view/View;->setVisibility(I)V\n'
        '\n'
        '    const v1, -0x99999a\n'
        '\n'
        '    invoke-virtual {p0, v1}, Landroid/widget/TextView;->setTextColor(I)V\n'
        '\n'
        '    goto :goto_0\n'
        '\n'
        '    :cond_1\n'
        '    const/16 p1, 0x8\n'
        '\n'
        '    invoke-virtual {p0, p1}, Landroid/view/View;->setVisibility(I)V\n'
        '\n'
        '    :cond_2\n'
        '    :goto_0\n'
        '    return-void\n',
    )
    fixed = _replace_smali_method(
        fixed,
        'public static setSummaryViewColor(Landroidx/preference/PreferenceViewHolder;Landroid/content/res/ColorStateList;)V',
        '    .locals 2\n'
        '\n'
        '    const v0, 0x1020010\n'
        '\n'
        '    invoke-virtual {p0, v0}, Landroidx/preference/PreferenceViewHolder;->findViewById(I)Landroid/view/View;\n'
        '\n'
        '    move-result-object p0\n'
        '\n'
        '    check-cast p0, Landroid/widget/TextView;\n'
        '\n'
        '    if-eqz p0, :cond_1\n'
        '\n'
        '    const v1, -0x99999a\n'
        '\n'
        '    invoke-virtual {p0, v1}, Landroid/widget/TextView;->setTextColor(I)V\n'
        '\n'
        '    :cond_1\n'
        '    :goto_0\n'
        '    return-void\n',
    )
    fixed = _replace_smali_method(
        fixed,
        'public static setTitleViewColor(Landroid/content/Context;Landroidx/preference/PreferenceViewHolder;Landroid/content/res/ColorStateList;)V',
        '    .locals 2\n'
        '\n'
        '    const p0, 0x1020016\n'
        '\n'
        '    invoke-virtual {p1, p0}, Landroidx/preference/PreferenceViewHolder;->findViewById(I)Landroid/view/View;\n'
        '\n'
        '    move-result-object p0\n'
        '\n'
        '    if-eqz p0, :cond_1\n'
        '\n'
        '    check-cast p0, Landroid/widget/TextView;\n'
        '\n'
        '    const/high16 v0, -0x1000000\n'
        '\n'
        '    invoke-virtual {p0, v0}, Landroid/widget/TextView;->setTextColor(I)V\n'
        '\n'
        '    :cond_1\n'
        '    :goto_0\n'
        '    return-void\n',
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')

    smali = Path(tmp_dir) / 'smali_classes5/com/coui/appcompat/textview/COUITextView.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    if data and 'protected onDraw(Landroid/graphics/Canvas;)V' not in data:
        fixed = data.replace(
            '# virtual methods\n',
            '# virtual methods\n'
            '.method protected onDraw(Landroid/graphics/Canvas;)V\n'
            '    .locals 2\n'
            '\n'
            '    const/high16 v0, -0x1000000\n'
            '\n'
            '    invoke-virtual {p0}, Landroid/widget/TextView;->getCurrentTextColor()I\n'
            '\n'
            '    move-result v1\n'
            '\n'
            '    if-eq v1, v0, :cond_0\n'
            '\n'
            '    invoke-virtual {p0, v0}, Landroid/widget/TextView;->setTextColor(I)V\n'
            '\n'
            '    :cond_0\n'
            '    invoke-super {p0, p1}, Landroidx/appcompat/widget/AppCompatTextView;->onDraw(Landroid/graphics/Canvas;)V\n'
            '\n'
            '    return-void\n'
            '.end method\n'
            '\n',
            1,
        )
        smali.write_text(fixed, encoding='utf-8')

    smali = Path(tmp_dir) / 'smali_classes5/com/oplus/gallery/basebiz/widget/EditorMenuItemView.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    fixed = _replace_smali_method(
        data,
        'public final setIconDrawableTintColor(I)V',
        '    .locals 1\n'
        '\n'
        '    const/high16 p1, -0x1000000\n'
        '\n'
        '    iget-object v0, p0, Lcom/oplus/gallery/basebiz/widget/EditorMenuItemView;->a:Landroid/graphics/drawable/Drawable;\n'
        '\n'
        '    if-eqz v0, :cond_0\n'
        '\n'
        '    invoke-virtual {v0, p1}, Landroid/graphics/drawable/Drawable;->setTint(I)V\n'
        '\n'
        '    :cond_0\n'
        '    invoke-virtual {p0}, Landroid/view/View;->postInvalidate()V\n'
        '\n'
        '    return-void\n',
    )
    fixed = _replace_smali_method(
        fixed,
        'public final setPaintColorFilter(I)V',
        '    .locals 2\n'
        '\n'
        '    const/high16 p1, -0x1000000\n'
        '\n'
        '    new-instance v0, Landroid/graphics/PorterDuffColorFilter;\n'
        '\n'
        '    sget-object v1, Landroid/graphics/PorterDuff$Mode;->SRC_ATOP:Landroid/graphics/PorterDuff$Mode;\n'
        '\n'
        '    invoke-direct {v0, p1, v1}, Landroid/graphics/PorterDuffColorFilter;-><init>(ILandroid/graphics/PorterDuff$Mode;)V\n'
        '\n'
        '    iget-object p1, p0, Lcom/oplus/gallery/basebiz/widget/EditorMenuItemView;->b:Landroid/graphics/Paint;\n'
        '\n'
        '    invoke-virtual {p1, v0}, Landroid/graphics/Paint;->setColorFilter(Landroid/graphics/ColorFilter;)Landroid/graphics/ColorFilter;\n'
        '\n'
        '    invoke-virtual {p0}, Landroid/view/View;->postInvalidate()V\n'
        '\n'
        '    return-void\n',
    )
    fixed = _replace_smali_method(
        fixed,
        'public final setTextColor(I)V',
        '    .locals 1\n'
        '\n'
        '    const/high16 p1, -0x1000000\n'
        '\n'
        '    iget-object v0, p0, Lcom/oplus/gallery/basebiz/widget/EditorMenuItemView;->e:Landroid/graphics/Paint;\n'
        '\n'
        '    invoke-virtual {v0, p1}, Landroid/graphics/Paint;->setColor(I)V\n'
        '\n'
        '    invoke-virtual {p0}, Landroid/view/View;->postInvalidate()V\n'
        '\n'
        '    return-void\n',
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')

    smali = Path(tmp_dir) / 'smali_classes5/com/coui/appcompat/poplist/DefaultAdapter.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    fixed = data.replace(
        '    invoke-direct {p0, p2, p3}, Lcom/coui/appcompat/poplist/DefaultAdapter;->getTintColorByState(Landroid/content/res/ColorStateList;Lcom/coui/appcompat/poplist/PopupListItem;)I\n'
        '\n'
        '    .line 5\n'
        '    .line 6\n'
        '    .line 7\n'
        '    move-result p0\n'
        '\n'
        '    .line 8\n'
        '    invoke-virtual {p1, p0}, Landroid/widget/TextView;->setTextColor(I)V\n',
        '    const/high16 p0, -0x1000000\n'
        '\n'
        '    .line 8\n'
        '    invoke-virtual {p1, p0}, Landroid/widget/TextView;->setTextColor(I)V\n',
    )
    fixed = fixed.replace(
        '    :cond_6\n'
        '    :goto_3\n'
        '    invoke-virtual {p2}, Lcom/coui/appcompat/poplist/PopupListItem;->isChecked()Z\n',
        '    :cond_6\n'
        '    :goto_3\n'
        '    const/high16 p0, -0x1000000\n'
        '\n'
        '    invoke-virtual {p1, p0}, Landroid/widget/TextView;->setTextColor(I)V\n'
        '\n'
        '    invoke-virtual {p2}, Lcom/coui/appcompat/poplist/PopupListItem;->isChecked()Z\n',
    )
    fixed = fixed.replace(
        '    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V\n'
        '\n',
        '    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V\n'
        '\n'
        '    const/high16 v1, -0x1000000\n'
        '\n'
        '    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setTextColor(I)V\n',
        1,
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')

    smali = Path(tmp_dir) / 'smali_classes5/com/coui/appcompat/poplist/COUIPopupListWindow.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    fixed = data.replace(
        '    :cond_1\n'
        '    invoke-virtual {v1}, Landroid/content/res/TypedArray;->recycle()V\n',
        '    :cond_1\n'
        '    iget-object v2, p0, Lcom/coui/appcompat/poplist/COUIPopupListWindow;->mMainMenuWrapper:Lcom/coui/appcompat/poplist/RoundFrameLayout;\n'
        '\n'
        '    const/4 v3, -0x1\n'
        '\n'
        '    invoke-virtual {v2, v3}, Landroid/view/View;->setBackgroundColor(I)V\n'
        '\n'
        '    iget-object v2, p0, Lcom/coui/appcompat/poplist/COUIPopupListWindow;->mSubMenuWrapper:Lcom/coui/appcompat/poplist/RoundFrameLayout;\n'
        '\n'
        '    invoke-virtual {v2, v3}, Landroid/view/View;->setBackgroundColor(I)V\n'
        '\n'
        '    iget-object v2, p0, Lcom/coui/appcompat/poplist/COUIPopupListWindow;->mMainListView:Landroid/widget/ListView;\n'
        '\n'
        '    invoke-virtual {v2, v3}, Landroid/view/View;->setBackgroundColor(I)V\n'
        '\n'
        '    iget-object v2, p0, Lcom/coui/appcompat/poplist/COUIPopupListWindow;->mSubListView:Landroid/widget/ListView;\n'
        '\n'
        '    invoke-virtual {v2, v3}, Landroid/view/View;->setBackgroundColor(I)V\n'
        '\n'
        '    invoke-virtual {v1}, Landroid/content/res/TypedArray;->recycle()V\n',
        1,
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')

    smali = Path(tmp_dir) / 'smali_classes5/com/coui/appcompat/poplist/RoundFrameLayout.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    fixed = _replace_smali_method(
        data,
        'public initUseBackgroundBlur(ZLcom/coui/appcompat/uiutil/AnimLevel;)V',
        '    .locals 2\n'
        '\n'
        '    iget-object v0, p0, Lcom/coui/appcompat/poplist/RoundFrameLayout;->mBackgroundBlurBuilder:Lcom/coui/appcompat/uiutil/COUIBackgroundBlurBuilder;\n'
        '\n'
        '    const/4 v1, 0x0\n'
        '\n'
        '    invoke-virtual {v0, v1, p2}, Lcom/coui/appcompat/uiutil/COUIBackgroundBlurBuilder;->setUseBackgroundBlur(ZLcom/coui/appcompat/uiutil/AnimLevel;)Lcom/coui/appcompat/uiutil/COUIBackgroundBlurBuilder;\n'
        '\n'
        '    return-void\n',
    )
    fixed = _replace_smali_method(
        fixed,
        'public getUseBackgroundBlur()Z',
        '    .locals 1\n'
        '\n'
        '    const/4 v0, 0x0\n'
        '\n'
        '    return v0\n',
    )
    fixed = _replace_smali_method(
        fixed,
        'public dispatchDraw(Landroid/graphics/Canvas;)V',
        '    .locals 0\n'
        '\n'
        '    invoke-super {p0, p1}, Landroid/widget/FrameLayout;->dispatchDraw(Landroid/graphics/Canvas;)V\n'
        '\n'
        '    return-void\n',
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')

    smali = Path(tmp_dir) / 'smali_classes5/com/coui/appcompat/poplist/COUIPopupMenuRootView.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    fixed = data.replace(
        '    .line 18\n'
        '    sget-boolean p3, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->DEBUG_DRAW:Z\n'
        '\n'
        '    if-eqz p3, :cond_0\n'
        '\n'
        '    .line 19\n'
        '    invoke-virtual {p0, p1}, Landroid/view/View;->setWillNotDraw(Z)V\n'
        '\n'
        '    .line 20\n'
        '    :cond_0\n',
        '    .line 18\n'
        '    invoke-virtual {p0, p1}, Landroid/view/View;->setWillNotDraw(Z)V\n'
        '\n'
        '    .line 20\n',
        1,
    )
    fixed = _replace_smali_method(
        fixed,
        'public onDraw(Landroid/graphics/Canvas;)V',
        '    .locals 0\n'
        '\n'
        '    invoke-super {p0, p1}, Landroid/view/View;->onDraw(Landroid/graphics/Canvas;)V\n'
        '\n'
        '    return-void\n',
    )
    if 'dispatchDraw(Landroid/graphics/Canvas;)V' not in fixed:
        fixed = fixed.replace(
            '\n.method public onLayout(ZIIII)V',
            '\n.method protected dispatchDraw(Landroid/graphics/Canvas;)V\n'
            '    .locals 0\n'
            '\n'
            '    return-void\n'
            '.end method\n'
            '\n'
            '.method public onLayout(ZIIII)V',
            1,
        )
    fixed = _replace_smali_method(
        fixed,
        'public onLayout(ZIIII)V',
        '    .locals 6\n'
        '\n'
        '    iget-object v0, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mMainMenuRootView:Landroid/view/ViewGroup;\n'
        '\n'
        '    if-eqz v0, :cond_1\n'
        '\n'
        '    iget-object v1, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mDomain:Lcom/coui/appcompat/poplist/PopupMenuDomain;\n'
        '\n'
        '    if-eqz v1, :cond_0\n'
        '\n'
        '    iget-object v1, v1, Lcom/coui/appcompat/poplist/PopupMenuDomain;->mMainMenu:Landroid/graphics/Rect;\n'
        '\n'
        '    if-eqz v1, :cond_0\n'
        '\n'
        '    iget v2, v1, Landroid/graphics/Rect;->left:I\n'
        '\n'
        '    iget v3, v1, Landroid/graphics/Rect;->top:I\n'
        '\n'
        '    iget v4, v1, Landroid/graphics/Rect;->right:I\n'
        '\n'
        '    iget v5, v1, Landroid/graphics/Rect;->bottom:I\n'
        '\n'
        '    invoke-virtual {v0, v2, v3, v4, v5}, Landroid/view/View;->layout(IIII)V\n'
        '\n'
        '    goto :cond_1\n'
        '\n'
        '    :cond_0\n'
        '    const/4 v2, 0x0\n'
        '\n'
        '    const/4 v3, 0x0\n'
        '\n'
        '    iget v4, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mMainMenuWidth:I\n'
        '\n'
        '    iget v5, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mMainMenuHeight:I\n'
        '\n'
        '    invoke-virtual {v0, v2, v3, v4, v5}, Landroid/view/View;->layout(IIII)V\n'
        '\n'
        '    :cond_1\n'
        '    iget-object v0, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mSubMenuRootView:Landroid/view/ViewGroup;\n'
        '\n'
        '    if-eqz v0, :cond_3\n'
        '\n'
        '    iget-object v1, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mDomain:Lcom/coui/appcompat/poplist/PopupMenuDomain;\n'
        '\n'
        '    if-eqz v1, :cond_2\n'
        '\n'
        '    iget-object v1, v1, Lcom/coui/appcompat/poplist/PopupMenuDomain;->mSubMenu:Landroid/graphics/Rect;\n'
        '\n'
        '    if-eqz v1, :cond_2\n'
        '\n'
        '    iget v2, v1, Landroid/graphics/Rect;->left:I\n'
        '\n'
        '    iget v3, v1, Landroid/graphics/Rect;->top:I\n'
        '\n'
        '    iget v4, v1, Landroid/graphics/Rect;->right:I\n'
        '\n'
        '    iget v5, v1, Landroid/graphics/Rect;->bottom:I\n'
        '\n'
        '    invoke-virtual {v0, v2, v3, v4, v5}, Landroid/view/View;->layout(IIII)V\n'
        '\n'
        '    goto :cond_3\n'
        '\n'
        '    :cond_2\n'
        '    const/4 v2, 0x0\n'
        '\n'
        '    const/4 v3, 0x0\n'
        '\n'
        '    iget v4, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mSubMenuWidth:I\n'
        '\n'
        '    iget v5, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mSubMenuHeight:I\n'
        '\n'
        '    invoke-virtual {v0, v2, v3, v4, v5}, Landroid/view/View;->layout(IIII)V\n'
        '\n'
        '    :cond_3\n'
        '    return-void\n',
    )
    fixed = _replace_smali_method(
        fixed,
        'public onMeasure(II)V',
        '    .locals 6\n'
        '\n'
        '    const/high16 v0, 0x40000000\n'
        '\n'
        '    iget-object v1, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mMainMenuRootView:Landroid/view/ViewGroup;\n'
        '\n'
        '    if-eqz v1, :cond_2\n'
        '\n'
        '    iget v2, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mMainMenuWidth:I\n'
        '\n'
        '    iget v3, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mMainMenuHeight:I\n'
        '\n'
        '    iget-object v4, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mDomain:Lcom/coui/appcompat/poplist/PopupMenuDomain;\n'
        '\n'
        '    if-eqz v4, :cond_0\n'
        '\n'
        '    iget-object v4, v4, Lcom/coui/appcompat/poplist/PopupMenuDomain;->mMainMenu:Landroid/graphics/Rect;\n'
        '\n'
        '    if-eqz v4, :cond_0\n'
        '\n'
        '    invoke-virtual {v4}, Landroid/graphics/Rect;->width()I\n'
        '\n'
        '    move-result v5\n'
        '\n'
        '    if-lez v5, :cond_0\n'
        '\n'
        '    move v2, v5\n'
        '\n'
        '    invoke-virtual {v4}, Landroid/graphics/Rect;->height()I\n'
        '\n'
        '    move-result v5\n'
        '\n'
        '    if-lez v5, :cond_0\n'
        '\n'
        '    move v3, v5\n'
        '\n'
        '    :cond_0\n'
        '    if-lez v2, :cond_2\n'
        '\n'
        '    if-lez v3, :cond_2\n'
        '\n'
        '    invoke-static {v2, v0}, Landroid/view/View$MeasureSpec;->makeMeasureSpec(II)I\n'
        '\n'
        '    move-result v2\n'
        '\n'
        '    invoke-static {v3, v0}, Landroid/view/View$MeasureSpec;->makeMeasureSpec(II)I\n'
        '\n'
        '    move-result v3\n'
        '\n'
        '    invoke-virtual {v1, v2, v3}, Landroid/view/View;->measure(II)V\n'
        '\n'
        '    :cond_2\n'
        '    iget-object v1, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mSubMenuRootView:Landroid/view/ViewGroup;\n'
        '\n'
        '    if-eqz v1, :cond_5\n'
        '\n'
        '    iget v2, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mSubMenuWidth:I\n'
        '\n'
        '    iget v3, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mSubMenuHeight:I\n'
        '\n'
        '    iget-object v4, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mDomain:Lcom/coui/appcompat/poplist/PopupMenuDomain;\n'
        '\n'
        '    if-eqz v4, :cond_3\n'
        '\n'
        '    iget-object v4, v4, Lcom/coui/appcompat/poplist/PopupMenuDomain;->mSubMenu:Landroid/graphics/Rect;\n'
        '\n'
        '    if-eqz v4, :cond_3\n'
        '\n'
        '    invoke-virtual {v4}, Landroid/graphics/Rect;->width()I\n'
        '\n'
        '    move-result v5\n'
        '\n'
        '    if-lez v5, :cond_3\n'
        '\n'
        '    move v2, v5\n'
        '\n'
        '    invoke-virtual {v4}, Landroid/graphics/Rect;->height()I\n'
        '\n'
        '    move-result v5\n'
        '\n'
        '    if-lez v5, :cond_3\n'
        '\n'
        '    move v3, v5\n'
        '\n'
        '    :cond_3\n'
        '    if-lez v2, :cond_5\n'
        '\n'
        '    if-lez v3, :cond_5\n'
        '\n'
        '    invoke-static {v2, v0}, Landroid/view/View$MeasureSpec;->makeMeasureSpec(II)I\n'
        '\n'
        '    move-result v2\n'
        '\n'
        '    invoke-static {v3, v0}, Landroid/view/View$MeasureSpec;->makeMeasureSpec(II)I\n'
        '\n'
        '    move-result v3\n'
        '\n'
        '    invoke-virtual {v1, v2, v3}, Landroid/view/View;->measure(II)V\n'
        '\n'
        '    :cond_5\n'
        '    invoke-static {p1}, Landroid/view/View$MeasureSpec;->getSize(I)I\n'
        '\n'
        '    move-result p1\n'
        '\n'
        '    invoke-static {p2}, Landroid/view/View$MeasureSpec;->getSize(I)I\n'
        '\n'
        '    move-result p2\n'
        '\n'
        '    invoke-virtual {p0, p1, p2}, Landroid/view/View;->setMeasuredDimension(II)V\n'
        '\n'
        '    return-void\n',
    )
    fixed = _replace_smali_method(
        fixed,
        'protected dispatchDraw(Landroid/graphics/Canvas;)V',
        '    .locals 6\n'
        '\n'
        '    iget-object v0, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mMainMenuRootView:Landroid/view/ViewGroup;\n'
        '\n'
        '    if-eqz v0, :cond_2\n'
        '\n'
        '    iget-object v1, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mDomain:Lcom/coui/appcompat/poplist/PopupMenuDomain;\n'
        '\n'
        '    if-eqz v1, :cond_1\n'
        '\n'
        '    iget-object v1, v1, Lcom/coui/appcompat/poplist/PopupMenuDomain;->mMainMenu:Landroid/graphics/Rect;\n'
        '\n'
        '    if-eqz v1, :cond_1\n'
        '\n'
        '    invoke-virtual {p1}, Landroid/graphics/Canvas;->save()I\n'
        '\n'
        '    move-result v2\n'
        '\n'
        '    iget v3, v1, Landroid/graphics/Rect;->left:I\n'
        '\n'
        '    int-to-float v3, v3\n'
        '\n'
        '    iget v4, v1, Landroid/graphics/Rect;->top:I\n'
        '\n'
        '    int-to-float v4, v4\n'
        '\n'
        '    invoke-virtual {p1, v3, v4}, Landroid/graphics/Canvas;->translate(FF)V\n'
        '\n'
        '    invoke-virtual {v0, p1}, Landroid/view/View;->draw(Landroid/graphics/Canvas;)V\n'
        '\n'
        '    invoke-virtual {p1, v2}, Landroid/graphics/Canvas;->restoreToCount(I)V\n'
        '\n'
        '    goto :cond_2\n'
        '\n'
        '    :cond_1\n'
        '    invoke-virtual {v0, p1}, Landroid/view/View;->draw(Landroid/graphics/Canvas;)V\n'
        '\n'
        '    :cond_2\n'
        '    iget-object v0, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mSubMenuRootView:Landroid/view/ViewGroup;\n'
        '\n'
        '    if-eqz v0, :cond_4\n'
        '\n'
        '    iget-object v1, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mDomain:Lcom/coui/appcompat/poplist/PopupMenuDomain;\n'
        '\n'
        '    if-eqz v1, :cond_3\n'
        '\n'
        '    iget-object v1, v1, Lcom/coui/appcompat/poplist/PopupMenuDomain;->mSubMenu:Landroid/graphics/Rect;\n'
        '\n'
        '    if-eqz v1, :cond_3\n'
        '\n'
        '    invoke-virtual {p1}, Landroid/graphics/Canvas;->save()I\n'
        '\n'
        '    move-result v2\n'
        '\n'
        '    iget v3, v1, Landroid/graphics/Rect;->left:I\n'
        '\n'
        '    int-to-float v3, v3\n'
        '\n'
        '    iget v4, v1, Landroid/graphics/Rect;->top:I\n'
        '\n'
        '    int-to-float v4, v4\n'
        '\n'
        '    invoke-virtual {p1, v3, v4}, Landroid/graphics/Canvas;->translate(FF)V\n'
        '\n'
        '    invoke-virtual {v0, p1}, Landroid/view/View;->draw(Landroid/graphics/Canvas;)V\n'
        '\n'
        '    invoke-virtual {p1, v2}, Landroid/graphics/Canvas;->restoreToCount(I)V\n'
        '\n'
        '    goto :cond_4\n'
        '\n'
        '    :cond_3\n'
        '    invoke-virtual {v0, p1}, Landroid/view/View;->draw(Landroid/graphics/Canvas;)V\n'
        '\n'
        '    :cond_4\n'
        '    return-void\n',
    )
    fixed = _replace_smali_method(
        fixed,
        'public showMainMenu()V',
        '    .locals 2\n'
        '\n'
        '    iget-object v0, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mMainMenuRootView:Landroid/view/ViewGroup;\n'
        '\n'
        '    if-nez v0, :cond_0\n'
        '\n'
        '    return-void\n'
        '\n'
        '    :cond_0\n'
        '    const/4 v1, 0x0\n'
        '\n'
        '    invoke-virtual {p0, v1}, Landroid/view/View;->setWillNotDraw(Z)V\n'
        '\n'
        '    invoke-virtual {v0, v1}, Landroid/view/View;->setVisibility(I)V\n'
        '\n'
        '    const/high16 v1, 0x3f800000\n'
        '\n'
        '    invoke-virtual {p0, v1}, Landroid/view/View;->setAlpha(F)V\n'
        '\n'
        '    invoke-virtual {p0, v1}, Landroid/view/View;->setScaleX(F)V\n'
        '\n'
        '    invoke-virtual {p0, v1}, Landroid/view/View;->setScaleY(F)V\n'
        '\n'
        '    invoke-virtual {v0, v1}, Landroid/view/View;->setAlpha(F)V\n'
        '\n'
        '    invoke-virtual {v0, v1}, Landroid/view/View;->setScaleX(F)V\n'
        '\n'
        '    invoke-virtual {v0, v1}, Landroid/view/View;->setScaleY(F)V\n'
        '\n'
        '    iget-object v0, p0, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->mSubMenuRootView:Landroid/view/ViewGroup;\n'
        '\n'
        '    if-eqz v0, :cond_1\n'
        '\n'
        '    const/4 v1, 0x1\n'
        '\n'
        '    invoke-virtual {p0, v1}, Lcom/coui/appcompat/poplist/COUIPopupMenuRootView;->hideSubMenu(Z)V\n'
        '\n'
        '    :cond_1\n'
        '    return-void\n',
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_oplus_camera_system_properties(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    for smali in Path(tmp_dir).glob('smali*/**/*.smali'):
        data = smali.read_text(encoding='utf-8')
        fixed = data
        for old, new in {
            'Lcom/oplus/wrapper/os/SystemProperties;': 'Landroid/os/SystemProperties;',
            'Lcom/oplus/wrapper/os/UserHandle;': 'Landroid/os/UserHandle;',
            'Lcom/oplus/wrapper/os/Trace;': 'Landroid/os/Trace;',
            'Lcom/oplus/wrapper/os/Debug;': 'Landroid/os/Debug;',
        }.items():
            fixed = fixed.replace(old, new)
        if fixed != data:
            smali.write_text(fixed, encoding='utf-8')


def blob_fixup_melody_repackaging_detector(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    # In Melody (com.oplus.melody), the built-in raw earphone whitelist (R.raw.melody_app_whitelist)
    # is encrypted with AES-256-GCM using the SHA-256 hash of the OEM signing certificate.
    # When the APK is re-signed with ROM platform/test keys, RepackagingDetector returns the
    # hash of the new key, causing decryption to fail and resulting in an empty device feature list.
    # We patch RepackagingDetector.b() / c() to always return the original stock certificate hash,
    # and d() (LSPatch check) to return false.
    key_body = (
        '    .locals 1\n'
        '\n'
        '    const/16 v0, 0x20\n'
        '\n'
        '    new-array v0, v0, [B\n'
        '\n'
        '    fill-array-data v0, :array_0\n'
        '\n'
        '    return-object v0\n'
        '\n'
        '    :array_0\n'
        '    .array-data 1\n'
        '        -0x50t\n'
        '        -0x57t\n'
        '        -0x45t\n'
        '        -0x4t\n'
        '        0x5t\n'
        '        -0x12t\n'
        '        -0x1bt\n'
        '        -0x19t\n'
        '        -0x30t\n'
        '        -0x5et\n'
        '        -0x37t\n'
        '        0x7ct\n'
        '        0x3t\n'
        '        0x5t\n'
        '        -0x7at\n'
        '        -0x1ft\n'
        '        0x5bt\n'
        '        -0x4dt\n'
        '        0x30t\n'
        '        0x11t\n'
        '        0x52t\n'
        '        0x7t\n'
        '        -0x71t\n'
        '        0x54t\n'
        '        0x47t\n'
        '        0x3bt\n'
        '        -0x48t\n'
        '        0x2dt\n'
        '        -0xat\n'
        '        -0x28t\n'
        '        -0x38t\n'
        '        0x18t\n'
        '    .end array-data\n'
    )
    lspatch_body = (
        '    .locals 1\n'
        '\n'
        '    const/4 v0, 0x0\n'
        '\n'
        '    return v0\n'
    )

    for smali in Path(tmp_dir).glob('smali*/**/L.smali'):
        data = smali.read_text(encoding='utf-8')
        if 'RepackagingDetector' not in data:
            continue
        data = _replace_smali_method(data, 'public static b(Lcom/oplus/melody/MelodyApplication;)[B', key_body)
        data = _replace_smali_method(data, 'public static c(Lcom/oplus/melody/MelodyApplication;)[B', key_body)
        data = _replace_smali_method(data, 'public static d(Lcom/oplus/melody/MelodyApplication;)Z', lspatch_body)
        smali.write_text(data, encoding='utf-8')


def blob_fixup_oplus_camera_framework_shims(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    for smali in Path(tmp_dir).glob('smali*/**/*.smali'):
        data = smali.read_text(encoding='utf-8')
        fixed = data
        for old_tag, new_tag in {
            'com.oplus.capture.flash.need': 'com.oplus.flashtrigger.state',
            'com.oplus.flash.status': 'com.oplus.flashtrigger.state',
            'com.oplus.outflash.flashtype': 'com.oplus.flashtrigger.state',
            'com.oplus.preview.outflash.connected': 'com.oplus.flashtrigger.state',
            'com.oplus.flash.IntensityControl': 'com.oplus.flashtrigger.state',
            'com.oplus.facebeauty.custom': 'com.oplus.facebeauty.level',
            'com.oplus.aec.customAE.enable': 'com.oplus.macro.closeup.enable',
            'com.oplus.DolIsStaggerState': 'com.oplus.capture.request.idx',
            'com.oplus.iris.aperture.switching': 'com.oplus.capture.request.idx',
            'com.oplus.isRawMax': 'com.oplus.capture.request.idx',
            'com.oplus.is.master.mode': 'com.oplus.capture.request.idx',
            'com.oplus.control.face.dr': 'com.oplus.capture.request.idx',
            'com.oplus.fallback.stable': 'com.oplus.capture.request.idx',
            'com.oplus.capture.job.type': 'com.oplus.capture.request.idx',
            'com.oplus.capture.request.need.preview.stream': 'com.oplus.capture.request.idx',
            'com.oplus.filter.mode': 'com.oplus.capture.request.idx',
            'com.oplus.app.filter.type': 'com.oplus.capture.request.idx',
            'com.oplus.aicolor.rear.enable': 'com.oplus.capture.request.idx',
            'com.oplus.camera.3d.api.state': 'com.oplus.capture.request.idx',
            'com.oplus.camera.configure.thermal.level': 'com.oplus.capture.request.idx',
            'com.oplus.camera.pi.enable': 'com.oplus.capture.request.idx',
            'com.oplus.camera.pi.enable_list': 'com.oplus.capture.request.idx',
            'com.oplus.asd.hdr.scope': 'com.oplus.capture.request.idx',
            'com.oplus.night.se.enable': 'com.oplus.capture.request.idx',
            'com.oplus.preview.ai.preset.asd.enable': 'com.oplus.capture.request.idx',
            'com.oplus.lsd.enable': 'com.oplus.capture.request.idx',
            'com.oplus.only.zoom.change': 'com.oplus.capture.request.idx',
            'com.oplus.config.aeExposureCompensation': 'com.oplus.capture.request.idx',
            'com.oplus.naturetone.state': 'com.oplus.capture.request.idx',
            'com.oplus.hal.fluency': 'com.oplus.capture.request.idx',
            'com.oplus.double.ois.wirecutoff.detection.sn': 'com.oplus.capture.request.idx',
            'com.oplus.process.pid': 'com.oplus.capture.request.idx',
            'com.oplus.TR.processing.state': 'com.oplus.capture.request.idx',
            'com.oplus.capture.request.idx_list': 'com.oplus.capture.request.idx',
            'com.oplus.capture.request.picture.size.scale': 'com.oplus.capture.request.idx',
            'com.oplus.picture.offset.time': 'com.oplus.capture.request.idx',
            'com.oplus.izoom.ability.support': 'com.oplus.aps.zoom.feature',
            'com.oplus.mipiraw.online.bpc': 'com.oplus.capture.mipiraw.online.bpc',
            'com.oplus.full.bining.qbc.enable': 'com.oplus.camera.is.from.main.menu',
            'com.oplus.rear.remosaic.enable': 'com.oplus.camera.is.from.main.menu',
            'com.oplus.burst.capture.single': 'com.oplus.camera.is.from.main.menu',
            'com.oplus.defer.force.start': 'com.oplus.camera.is.from.main.menu',
            'com.oplus.flash.snapshot.use.nonzsl': 'com.oplus.camera.is.from.main.menu',
            'com.oplus.algo.visualization.enable': 'com.oplus.multiobj.info.visualization',
            'com.oplus.camera.algo.visualization.enable': 'com.oplus.multiobj.info.visualization',
            'com.oplus.sod.enable': 'com.oplus.sod.touch.region',
            'com.oplus.caller.package.name': 'com.oplus.packageName',
            'com.oplus.device.orientation': 'com.oplus.preview.orientation',
        }.items():
            fixed = fixed.replace(old_tag, new_tag)
        fixed = re.sub(
            r'(?m)^\.implements Ljava/lang/Object;\n',
            '',
            fixed,
        )
        fixed = re.sub(
            r'(?m)^(\s*)invoke-virtual \{([vp]\d+)\}, Ljava/lang/Enum;->name\(\)Ljava/lang/String;',
            r'\1invoke-static {\2}, Ljava/lang/String;->valueOf(Ljava/lang/Object;)Ljava/lang/String;',
            fixed,
        )
        if smali.match('*/com/oplus/camera/CameraManager$a.smali'):
            fixed = fixed.replace(
                '    invoke-virtual {p0}, Landroid/os/AsyncTask;->isCancelled()Z\n'
                '\n'
                '    .line 29\n'
                '    .line 30\n'
                '    .line 31\n'
                '    move-result p1\n'
                '\n'
                '    .line 32\n'
                '    if-nez p1, :cond_4\n'
                '\n'
                '    .line 33\n'
                '    .line 34\n'
                '    sget p1, Lqk/p;->p:I\n',
                '    invoke-virtual {p0}, Landroid/os/AsyncTask;->isCancelled()Z\n'
                '\n'
                '    .line 29\n'
                '    .line 30\n'
                '    .line 31\n'
                '    move-result p1\n'
                '\n'
                '    .line 32\n'
                '    if-nez p1, :cond_4\n'
                '\n'
                '    .line 33\n'
                '    .line 34\n'
                '    const/4 p1, 0x0\n',
                1,
            )

        if smali.match('*/in/x0.smali'):
            fixed = _noop_smali_method(fixed, 'public final S6()V')

        if smali.name == 'Performance.smali':
            fixed = _noop_smali_method(fixed, 'public static setIOPriority(I)V')
            fixed = _noop_smali_method(fixed, 'private static synthetic lambda$registerOsenseEventCallback$44()V')
            fixed = _noop_smali_method(fixed, 'private static registerOsenseEventCallback()V')
            fixed = _noop_smali_method(fixed, 'private static unregisterOsenseEventCallback()V')
            fixed = _noop_smali_method(fixed, 'public static requestLongTimeTaskMode()V')
            fixed = _noop_smali_method(fixed, 'public static cancelLongTimeTaskMode()V')

        if False and smali.match('*/com/oplus/ocs/camera/CameraUnitImpl$4.smali'):
            fixed = _noop_smali_method(fixed, 'public run()V')

        if False and smali.match('*/com/oplus/ocs/camera/CameraUnitImpl.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public isAuthedClient(Landroid/content/Context;)Z',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x1\n'
                '\n'
                '    return v0\n',
            )

        if smali.match('*/com/oplus/aiunit/configuration/OSRepository.smali'):
            empty_map_body = _empty_map_smali_body()
            for signature in (
                'private final listFilesFromOS(Ljava/lang/String;Ljava/lang/String;)Ljava/util/Map;',
                'public static synthetic listFilesFromOS$default(Lcom/oplus/aiunit/configuration/OSRepository;Ljava/lang/String;Ljava/lang/String;ILjava/lang/Object;)Ljava/util/Map;',
                'private final listFilesFromOsV2(Ljava/lang/String;)Ljava/util/Map;',
                'public final listPreinstalledOap2(Landroid/content/Context;)Ljava/util/Map;',
                'public final listPreinstalledOapOaa2(Landroid/content/Context;)Ljava/util/Map;',
                'private final readFilesFromOS(Ljava/lang/String;)Ljava/util/Map;',
                'private final readFilesFromOsV2(Ljava/lang/String;)Ljava/util/Map;',
                'public final readPreInstalledOrangeResConfig()Ljava/util/Map;',
                'public final readPreInstalledUnitConfig()Ljava/util/Map;',
                'public final readPreInstalledUnitConfigV2()Ljava/util/Map;',
            ):
                fixed = _replace_smali_method(fixed, signature, empty_map_body)

        if smali.match('*/com/oplus/ocs/camera/producer/info/CameraCharacteristicsHelper.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public static getCameraIdType(Ljava/lang/String;)Lcom/oplus/ocs/camera/producer/info/CameraIdType;',
                '    .locals 4\n'
                '\n'
                '    sget-object v0, Lcom/oplus/ocs/camera/producer/info/CameraCharacteristicsHelper;->sCameraIdTypeMap:Ljava/util/Map;\n'
                '\n'
                '    invoke-interface {v0, p0}, Ljava/util/Map;->get(Ljava/lang/Object;)Ljava/lang/Object;\n'
                '\n'
                '    move-result-object v1\n'
                '\n'
                '    check-cast v1, Lcom/oplus/ocs/camera/producer/info/CameraIdType;\n'
                '\n'
                '    if-eqz v1, :cond_0\n'
                '\n'
                '    return-object v1\n'
                '\n'
                '    :cond_0\n'
                '    const/4 v2, -0x1\n'
                '\n'
                '    const-string v3, "rear_main"\n'
                '\n'
                '    invoke-virtual {v3, p0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n'
                '\n'
                '    move-result v3\n'
                '\n'
                '    if-eqz v3, :cond_1\n'
                '\n'
                '    const/4 v2, 0x0\n'
                '\n'
                '    goto :goto_0\n'
                '\n'
                '    :cond_1\n'
                '    const-string v3, "front_main"\n'
                '\n'
                '    invoke-virtual {v3, p0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n'
                '\n'
                '    move-result v3\n'
                '\n'
                '    if-eqz v3, :cond_2\n'
                '\n'
                '    const/4 v2, 0x1\n'
                '\n'
                '    goto :goto_0\n'
                '\n'
                '    :cond_2\n'
                '    const-string v3, "rear_wide"\n'
                '\n'
                '    invoke-virtual {v3, p0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n'
                '\n'
                '    move-result v3\n'
                '\n'
                '    if-eqz v3, :cond_3\n'
                '\n'
                '    const/4 v2, 0x2\n'
                '\n'
                '    goto :goto_0\n'
                '\n'
                '    :cond_3\n'
                '    const-string v3, "rear_tele"\n'
                '\n'
                '    invoke-virtual {v3, p0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n'
                '\n'
                '    move-result v3\n'
                '\n'
                '    if-eqz v3, :cond_4\n'
                '\n'
                '    const/4 v2, 0x3\n'
                '\n'
                '    goto :goto_0\n'
                '\n'
                '    :cond_4\n'
                '    const-string v3, "rear_ultra_tele"\n'
                '\n'
                '    invoke-virtual {v3, p0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n'
                '\n'
                '    move-result v3\n'
                '\n'
                '    if-eqz v3, :cond_5\n'
                '\n'
                '    const/4 v2, 0x4\n'
                '\n'
                '    goto :goto_0\n'
                '\n'
                '    :cond_5\n'
                '    const-string v3, "rear_main_front_main"\n'
                '\n'
                '    invoke-virtual {v3, p0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n'
                '\n'
                '    move-result v3\n'
                '\n'
                '    if-eqz v3, :cond_6\n'
                '\n'
                '    const/16 v2, 0x64\n'
                '\n'
                '    :cond_6\n'
                '    :goto_0\n'
                '    if-ltz v2, :cond_7\n'
                '\n'
                '    new-instance v1, Lcom/oplus/ocs/camera/producer/info/CameraIdType;\n'
                '\n'
                '    invoke-direct {v1, p0, v2}, Lcom/oplus/ocs/camera/producer/info/CameraIdType;-><init>(Ljava/lang/String;I)V\n'
                '\n'
                '    invoke-interface {v0, p0, v1}, Ljava/util/Map;->put(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;\n'
                '\n'
                '    sget-object p0, Lcom/oplus/ocs/camera/producer/info/CameraCharacteristicsHelper;->sCameraIdArray:Landroid/util/SparseArray;\n'
                '\n'
                '    invoke-virtual {p0, v2, v1}, Landroid/util/SparseArray;->put(ILjava/lang/Object;)V\n'
                '\n'
                '    return-object v1\n'
                '\n'
                '    :cond_7\n'
                '    const/4 p0, 0x0\n'
                '\n'
                '    return-object p0\n',
            )
            fixed = fixed.replace(
                '    .line 123\n'
                '    :goto_3\n'
                '    sget-object v12, Lcom/oplus/ocs/camera/producer/info/CameraCharacteristicsWrapper;->KEY_AVAILABLE_STREAM_FPS_RANGES:Landroid/hardware/camera2/CameraCharacteristics$Key;\n',
                '    .line 123\n'
                '    :goto_3\n'
                '    const-string v13, "0"\n'
                '\n'
                '    invoke-virtual {v13, v7}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n'
                '\n'
                '    move-result v13\n'
                '\n'
                '    if-eqz v13, :cond_op15_camera_type_1\n'
                '\n'
                '    const/4 v10, 0x0\n'
                '\n'
                '    goto :cond_op15_camera_type_done\n'
                '\n'
                '    :cond_op15_camera_type_1\n'
                '    const-string v13, "1"\n'
                '\n'
                '    invoke-virtual {v13, v7}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n'
                '\n'
                '    move-result v13\n'
                '\n'
                '    if-eqz v13, :cond_op15_camera_type_2\n'
                '\n'
                '    const/4 v10, 0x1\n'
                '\n'
                '    goto :cond_op15_camera_type_done\n'
                '\n'
                '    :cond_op15_camera_type_2\n'
                '    const-string v13, "2"\n'
                '\n'
                '    invoke-virtual {v13, v7}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n'
                '\n'
                '    move-result v13\n'
                '\n'
                '    if-eqz v13, :cond_op15_camera_type_3\n'
                '\n'
                '    const/4 v10, 0x2\n'
                '\n'
                '    goto :cond_op15_camera_type_done\n'
                '\n'
                '    :cond_op15_camera_type_3\n'
                '    const-string v13, "3"\n'
                '\n'
                '    invoke-virtual {v13, v7}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n'
                '\n'
                '    move-result v13\n'
                '\n'
                '    if-eqz v13, :cond_op15_camera_type_4\n'
                '\n'
                '    const/4 v10, 0x6\n'
                '\n'
                '    goto :cond_op15_camera_type_done\n'
                '\n'
                '    :cond_op15_camera_type_4\n'
                '    const-string v13, "4"\n'
                '\n'
                '    invoke-virtual {v13, v7}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z\n'
                '\n'
                '    move-result v13\n'
                '\n'
                '    if-eqz v13, :cond_op15_camera_type_done\n'
                '\n'
                '    const/16 v10, 0x1a\n'
                '\n'
                '    :cond_op15_camera_type_done\n'
                '    sget-object v12, Lcom/oplus/ocs/camera/producer/info/CameraCharacteristicsWrapper;->KEY_AVAILABLE_STREAM_FPS_RANGES:Landroid/hardware/camera2/CameraCharacteristics$Key;\n',
            )

        if False and smali.match('*/com/oplus/ocs/camera/producer/device/Camera2Impl.smali'):
            fixed = fixed.replace(
                '.method public openCameraDevice(ILandroid/os/Handler;)V\n'
                '    .locals 6\n',
                '.method public openCameraDevice(ILandroid/os/Handler;)V\n'
                '    .locals 8\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-virtual {v1, p1, v3, p2}, Landroid/hardware/camera2/CameraManager;->openCamera(Ljava/lang/String;Landroid/hardware/camera2/CameraDevice$StateCallback;Landroid/os/Handler;)V\n'
                '\n'
                '    .line 2919\n',
                '    const-string v6, "OP15Unit"\n'
                '\n'
                '    new-instance v7, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v4, "Camera2Impl openCameraDevice requested id="\n'
                '\n'
                '    invoke-direct {v7, v4}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v7, p1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v7}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v7\n'
                '\n'
                '    invoke-static {v6, v7}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v6\n'
                '\n'
                '    invoke-virtual {v1, p1, v3, p2}, Landroid/hardware/camera2/CameraManager;->openCamera(Ljava/lang/String;Landroid/hardware/camera2/CameraDevice$StateCallback;Landroid/os/Handler;)V\n'
                '\n'
                '    .line 2919\n',
                1,
            )
            fixed = fixed.replace(
                '    iget-object p0, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->mDeviceVariable:Landroid/os/ConditionVariable;\n'
                '\n'
                '    invoke-virtual {p0}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    return-void\n',
                '    iget-object p0, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->mDeviceVariable:Landroid/os/ConditionVariable;\n'
                '\n'
                '    invoke-virtual {p0}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    const-string p0, "OP15Unit"\n'
                '\n'
                '    const-string p1, "Camera2Impl openCameraDevice block returned"\n'
                '\n'
                '    invoke-static {p0, p1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p0\n'
                '\n'
                '    return-void\n',
                1,
            )

        if False and smali.match('*/com/oplus/ocs/camera/producer/device/Camera2Impl$2.smali'):
            fixed = fixed.replace(
                '.method public onOpened(Landroid/hardware/camera2/CameraDevice;)V\n'
                '    .locals 2\n',
                '.method public onOpened(Landroid/hardware/camera2/CameraDevice;)V\n'
                '    .locals 3\n'
                '\n'
                '    const-string v0, "OP15Unit"\n'
                '\n'
                '    new-instance v1, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v2, "Camera2Impl.StateCallback onOpened device="\n'
                '\n'
                '    invoke-direct {v1, v2}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v1, p1}, Ljava/lang/StringBuilder;->append(Ljava/lang/Object;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v1\n'
                '\n'
                '    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n',
                1,
            )

        if False and smali.match('*/com/oplus/ocs/camera/producer/device/Camera2StateMachineImpl$1.smali'):
            fixed = fixed.replace(
                '.method public onOpened(Landroid/hardware/camera2/CameraDevice;)V\n'
                '    .locals 1\n',
                '.method public onOpened(Landroid/hardware/camera2/CameraDevice;)V\n'
                '    .locals 2\n'
                '\n'
                '    const-string v0, "OP15Unit"\n'
                '\n'
                '    const-string v1, "StateMachine inner onOpened entry"\n'
                '\n'
                '    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n',
                1,
            )

        if False and smali.match('*/com/oplus/ocs/camera/producer/device/Camera2StateMachineImpl$StateMachineHandler.smali'):
            fixed = fixed.replace(
                '    invoke-interface {p1, v0, v1}, Lcom/oplus/ocs/camera/producer/device/Camera2Interface;->openCameraDevice(ILandroid/os/Handler;)V\n'
                '\n'
                '    .line 375\n',
                '    invoke-interface {p1, v0, v1}, Lcom/oplus/ocs/camera/producer/device/Camera2Interface;->openCameraDevice(ILandroid/os/Handler;)V\n'
                '\n'
                '    const-string p1, "OP15Unit"\n'
                '\n'
                '    const-string v0, "StateMachine MSG_OPEN_CAMERA_DEVICE returned from openCameraDevice"\n'
                '\n'
                '    invoke-static {p1, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p1\n'
                '\n'
                '    .line 375\n',
                1,
            )

        if smali.match('*/vj/k.smali'):
            fixed = fixed.replace(
                '    iget-object p0, p0, Lvj/k;->K:Landroid/os/ConditionVariable;\n'
                '\n'
                '    .line 648\n'
                '    .line 649\n'
                '    invoke-virtual {p0}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    .line 650\n',
                '    iget-object p0, p0, Lvj/k;->K:Landroid/os/ConditionVariable;\n'
                '\n'
                '    const-string v9, "OP15Preview"\n'
                '\n'
                '    new-instance v10, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v0, "J waiting K="\n'
                '\n'
                '    invoke-direct {v10, v0}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-static {p0}, Ljava/lang/System;->identityHashCode(Ljava/lang/Object;)I\n'
                '\n'
                '    move-result v0\n'
                '\n'
                '    invoke-virtual {v10, v0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v10}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v10\n'
                '\n'
                '    invoke-static {v9, v10}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v9\n'
                '\n'
                '    .line 648\n'
                '    .line 649\n'
                '    invoke-virtual {p0}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    const-string v9, "OP15Preview"\n'
                '\n'
                '    const-string v10, "J released K"\n'
                '\n'
                '    invoke-static {v9, v10}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v9\n'
                '\n'
                '    .line 650\n',
                1,
            )

        if smali.match('*/com/oplus/camera/Camera$h.smali'):
            fixed = fixed.replace(
                '.method public final onServiceConnected(Landroid/content/ComponentName;Landroid/os/IBinder;)V\n'
                '    .locals 3\n',
                '.method public final onServiceConnected(Landroid/content/ComponentName;Landroid/os/IBinder;)V\n'
                '    .locals 3\n'
                '\n'
                '    const-string v0, "OP15ApsBind"\n'
                '\n'
                '    const-string v1, "Camera$h onServiceConnected entry"\n'
                '\n'
                '    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n',
                1,
            )
            fixed = fixed.replace(
                '    iget-object p1, p0, Lcom/oplus/camera/CameraManager;->J:Landroid/os/ConditionVariable;\n'
                '\n'
                '    .line 106\n'
                '    .line 107\n'
                '    invoke-virtual {p1}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    .line 108\n',
                '    iget-object p1, p0, Lcom/oplus/camera/CameraManager;->J:Landroid/os/ConditionVariable;\n'
                '\n'
                '    const-string p2, "OP15ApsBind"\n'
                '\n'
                '    const-string v0, "Camera$h waiting CameraManager.J"\n'
                '\n'
                '    invoke-static {p2, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p2\n'
                '\n'
                '    .line 106\n'
                '    .line 107\n'
                '    invoke-virtual {p1}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    const-string p1, "OP15ApsBind"\n'
                '\n'
                '    const-string p2, "Camera$h CameraManager.J released"\n'
                '\n'
                '    invoke-static {p1, p2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p1\n'
                '\n'
                '    .line 108\n',
                1,
            )
            fixed = fixed.replace(
                '    iget-object p1, p1, Lvj/k;->K:Landroid/os/ConditionVariable;\n'
                '\n'
                '    .line 120\n'
                '    .line 121\n'
                '    invoke-virtual {p1}, Landroid/os/ConditionVariable;->open()V\n'
                '\n'
                '    .line 122\n',
                '    iget-object p1, p1, Lvj/k;->K:Landroid/os/ConditionVariable;\n'
                '\n'
                '    const-string v0, "OP15Preview"\n'
                '\n'
                '    new-instance p2, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v1, "Camera$h opening K="\n'
                '\n'
                '    invoke-direct {p2, v1}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-static {p1}, Ljava/lang/System;->identityHashCode(Ljava/lang/Object;)I\n'
                '\n'
                '    move-result v1\n'
                '\n'
                '    invoke-virtual {p2, v1}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {p2}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object p2\n'
                '\n'
                '    invoke-static {v0, p2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n'
                '\n'
                '    .line 120\n'
                '    .line 121\n'
                '    invoke-virtual {p1}, Landroid/os/ConditionVariable;->open()V\n'
                '\n'
                '    .line 122\n',
                1,
            )

        if smali.match('*/com/oplus/camera/Camera$i.smali'):
            fixed = fixed.replace(
                '.method public final run()V\n'
                '    .locals 4\n',
                '.method public final run()V\n'
                '    .locals 4\n'
                '\n'
                '    const-string v0, "OP15ApsBind"\n'
                '\n'
                '    const-string v1, "Camera$i bind runnable entry"\n'
                '\n'
                '    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n',
                1,
            )
            fixed = fixed.replace(
                '    sget-object v2, Lcom/oplus/camera/MyApplication;->d:Landroid/os/ConditionVariable;\n'
                '\n'
                '    .line 51\n'
                '    .line 52\n'
                '    invoke-virtual {v2}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    .line 53\n',
                '    const-string v2, "OP15ApsBind"\n'
                '\n'
                '    const-string v3, "Camera$i skip MyApplication.d wait before APS bind"\n'
                '\n'
                '    invoke-static {v2, v3}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v2\n'
                '\n'
                '    .line 53\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-virtual {p0, v0, v1, v2, v3}, Landroid/content/Context;->bindService(Landroid/content/Intent;ILjava/util/concurrent/Executor;Landroid/content/ServiceConnection;)Z\n'
                '\n'
                '    .line 75\n',
                '    invoke-virtual {p0, v0, v1, v2, v3}, Landroid/content/Context;->bindService(Landroid/content/Intent;ILjava/util/concurrent/Executor;Landroid/content/ServiceConnection;)Z\n'
                '\n'
                '    move-result v0\n'
                '\n'
                '    const-string v1, "OP15ApsBind"\n'
                '\n'
                '    new-instance v2, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v3, "Camera$i bindService result="\n'
                '\n'
                '    invoke-direct {v2, v3}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v2, v0}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v2}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v0\n'
                '\n'
                '    invoke-static {v1, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n'
                '\n'
                '    .line 75\n',
                1,
            )

        if False and smali.match('*/mj/r3.smali'):
            fixed = fixed.replace(
                '    invoke-virtual {p0}, Lmj/r3;->x()V\n'
                '\n'
                '    .line 24\n'
                '    .line 25\n'
                '    .line 26\n'
                '    return-void\n',
                '    invoke-virtual {p0}, Lmj/r3;->x()V\n'
                '\n'
                '    iget-object v0, p0, Lmj/r3;->L:Lvj/k;\n'
                '\n'
                '    if-eqz v0, :cond_op15_c0_k_done\n'
                '\n'
                '    iget-object v0, v0, Lvj/k;->K:Landroid/os/ConditionVariable;\n'
                '\n'
                '    if-eqz v0, :cond_op15_c0_k_done\n'
                '\n'
                '    const-string v1, "OP15Preview"\n'
                '\n'
                '    new-instance v2, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string p1, "r3.c0 opening K="\n'
                '\n'
                '    invoke-direct {v2, p1}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-static {v0}, Ljava/lang/System;->identityHashCode(Ljava/lang/Object;)I\n'
                '\n'
                '    move-result p1\n'
                '\n'
                '    invoke-virtual {v2, p1}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v2}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object p1\n'
                '\n'
                '    invoke-static {v1, p1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p1\n'
                '\n'
                '    invoke-virtual {v0}, Landroid/os/ConditionVariable;->open()V\n'
                '\n'
                '    :cond_op15_c0_k_done\n'
                '    .line 24\n'
                '    .line 25\n'
                '    .line 26\n'
                '    return-void\n',
                1,
            )

        if False and smali.match('*/com/oplus/ocs/camera/producer/device/Camera2Impl.smali'):
            fixed = fixed.replace(
                '    .line 2976\n'
                '    iget-object p0, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->mDeviceVariable:Landroid/os/ConditionVariable;\n'
                '\n'
                '    invoke-virtual {p0}, Landroid/os/ConditionVariable;->block()V\n',
                '    .line 2976\n'
                '    invoke-direct {p0}, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->closeAllImageReader()V\n'
                '\n'
                '    iget-object v1, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->mCameraStateCallback:Landroid/hardware/camera2/CameraDevice$StateCallback;\n'
                '\n'
                '    if-eqz v1, :cond_op15_direct_closed_callback\n'
                '\n'
                '    iget-object v2, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->mCameraDevice:Landroid/hardware/camera2/CameraDevice;\n'
                '\n'
                '    invoke-virtual {v1, v2}, Landroid/hardware/camera2/CameraDevice$StateCallback;->onClosed(Landroid/hardware/camera2/CameraDevice;)V\n'
                '\n'
                '    :cond_op15_direct_closed_callback\n'
                '    iget-object v1, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->mDeviceVariable:Landroid/os/ConditionVariable;\n'
                '\n'
                '    invoke-virtual {v1}, Landroid/os/ConditionVariable;->open()V\n'
                '\n'
                '    const/4 v1, 0x0\n'
                '\n'
                '    iput-object v1, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->mCameraDevice:Landroid/hardware/camera2/CameraDevice;\n',
            )
            fixed = fixed.replace(
                '    if-nez v1, :cond_0\n'
                '\n'
                '    return-void\n'
                '\n'
                '    .line 2905\n'
                '    :cond_0\n'
                '    invoke-virtual {p0, v1}, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->updateOplusParams(Landroid/hardware/camera2/CameraManager;)V\n',
                '    if-nez v1, :cond_0\n'
                '\n'
                '    return-void\n'
                '\n'
                '    .line 2905\n'
                '    :cond_0\n'
                '    const/16 v2, 0x64\n'
                '\n'
                '    if-ne p1, v2, :cond_0_op15_real_id\n'
                '\n'
                '    const/4 p1, 0x0\n'
                '\n'
                '    :cond_0_op15_real_id\n'
                '    invoke-virtual {p0, v1}, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->updateOplusParams(Landroid/hardware/camera2/CameraManager;)V\n',
            )
        if smali.match('*/com/oplus/ocs/camera/producer/device/Camera2Impl$2.smali'):
            fixed = fixed.replace(
                '.method public onClosed(Landroid/hardware/camera2/CameraDevice;)V\n'
                '    .locals 2\n',
                '.method public onClosed(Landroid/hardware/camera2/CameraDevice;)V\n'
                '    .locals 3\n',
            )
            fixed = fixed.replace(
                '    const-string v1, "StateCallback"\n'
                '\n'
                '    invoke-static {v1, v0}, Lcom/oplus/ocs/camera/common/util/CameraUnitLog;->w(Ljava/lang/String;Ljava/lang/String;)V\n'
                '\n'
                '    .line 350\n'
                '    iget-object v0, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl$2;->this$0:Lcom/oplus/ocs/camera/producer/device/Camera2Impl;\n',
                '    const-string v1, "StateCallback"\n'
                '\n'
                '    invoke-static {v1, v0}, Lcom/oplus/ocs/camera/common/util/CameraUnitLog;->w(Ljava/lang/String;Ljava/lang/String;)V\n'
                '\n'
                '    iget-object v2, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl$2;->this$0:Lcom/oplus/ocs/camera/producer/device/Camera2Impl;\n'
                '\n'
                '    invoke-static {v2}, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->-$$Nest$fgetmCameraStateCallback(Lcom/oplus/ocs/camera/producer/device/Camera2Impl;)Landroid/hardware/camera2/CameraDevice$StateCallback;\n'
                '\n'
                '    move-result-object v2\n'
                '\n'
                '    if-eqz v2, :cond_op15_on_closed_forwarded\n'
                '\n'
                '    invoke-virtual {v2, p1}, Landroid/hardware/camera2/CameraDevice$StateCallback;->onClosed(Landroid/hardware/camera2/CameraDevice;)V\n'
                '\n'
                '    :cond_op15_on_closed_forwarded\n'
                '    .line 350\n'
                '    iget-object v0, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl$2;->this$0:Lcom/oplus/ocs/camera/producer/device/Camera2Impl;\n',
            )
        if False and smali.match('*/com/oplus/ocs/camera/producer/device/Camera2Impl$12.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public execute(Ljava/lang/Runnable;)V',
                '    .locals 0\n'
                '\n'
                '    invoke-interface {p1}, Ljava/lang/Runnable;->run()V\n'
                '\n'
                '    return-void\n',
            )

        if False and smali.match('*/com/oplus/ocs/camera/producer/device/Camera2Impl$7.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public onConfigured(Landroid/hardware/camera2/CameraCaptureSession;)V',
                '    .locals 3\n'
                '\n'
                '    .line 838\n'
                '    new-instance v0, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v1, "onConfigured,"\n'
                '\n'
                '    invoke-direct {v0, v1}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v0, p1}, Ljava/lang/StringBuilder;->append(Ljava/lang/Object;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v0\n'
                '\n'
                '    const-string v1, "StateCallback"\n'
                '\n'
                '    invoke-static {v1, v0}, Lcom/oplus/ocs/camera/common/util/CameraUnitLog;->w(Ljava/lang/String;Ljava/lang/String;)V\n'
                '\n'
                '    const-string v0, "CameraUnit.CameraStartupPerformance.onCameraCaptureSessionConfigured"\n'
                '\n'
                '    .line 840\n'
                '    invoke-static {v0}, Lcom/oplus/ocs/camera/common/util/CameraUnitLog;->traceBeginSection(Ljava/lang/String;)V\n'
                '\n'
                '    .line 842\n'
                '    iget-object v1, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl$7;->this$0:Lcom/oplus/ocs/camera/producer/device/Camera2Impl;\n'
                '\n'
                '    invoke-static {v1, p1}, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->-$$Nest$fputmCaptureSession(Lcom/oplus/ocs/camera/producer/device/Camera2Impl;Landroid/hardware/camera2/CameraCaptureSession;)V\n'
                '\n'
                '    move-object v2, p1\n'
                '\n'
                '    .line 843\n'
                '    iget-object p1, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl$7;->this$0:Lcom/oplus/ocs/camera/producer/device/Camera2Impl;\n'
                '\n'
                '    invoke-static {p1}, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->-$$Nest$fgetmSessionVariable(Lcom/oplus/ocs/camera/producer/device/Camera2Impl;)Landroid/os/ConditionVariable;\n'
                '\n'
                '    move-result-object p1\n'
                '\n'
                '    invoke-virtual {p1}, Landroid/os/ConditionVariable;->open()V\n'
                '\n'
                '    iget-object p1, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl$7;->this$0:Lcom/oplus/ocs/camera/producer/device/Camera2Impl;\n'
                '\n'
                '    invoke-static {p1}, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->-$$Nest$fgetmCameraSessionCallback(Lcom/oplus/ocs/camera/producer/device/Camera2Impl;)Landroid/hardware/camera2/CameraCaptureSession$StateCallback;\n'
                '\n'
                '    move-result-object p1\n'
                '\n'
                '    if-eqz p1, :cond_0_op15_config_forwarded\n'
                '\n'
                '    invoke-virtual {p1, v2}, Landroid/hardware/camera2/CameraCaptureSession$StateCallback;->onConfigured(Landroid/hardware/camera2/CameraCaptureSession;)V\n'
                '\n'
                '    :cond_0_op15_config_forwarded\n'
                '    .line 844\n'
                '    iget-object p0, p0, Lcom/oplus/ocs/camera/producer/device/Camera2Impl$7;->this$0:Lcom/oplus/ocs/camera/producer/device/Camera2Impl;\n'
                '\n'
                '    const/4 p1, 0x0\n'
                '\n'
                '    invoke-static {p0, p1}, Lcom/oplus/ocs/camera/producer/device/Camera2Impl;->-$$Nest$fputmbNotAllowedTakePicture(Lcom/oplus/ocs/camera/producer/device/Camera2Impl;Z)V\n'
                '\n'
                '    .line 846\n'
                '    invoke-static {v0}, Lcom/oplus/ocs/camera/common/util/CameraUnitLog;->traceEndSection(Ljava/lang/String;)V\n'
                '\n'
                '    return-void\n',
            )

        if False and smali.match('*/com/oplus/ocs/camera/producer/device/CameraSessionEntity.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public getOperationMode()I',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n',
            )
            fixed = _replace_smali_method(
                fixed,
                'public setOperationMode(Ljava/lang/String;)V',
                '    .locals 1\n'
                '\n'
                '    const-string v0, "0"\n'
                '\n'
                '    iput-object v0, p0, Lcom/oplus/ocs/camera/producer/device/CameraSessionEntity;->mOperationMode:Ljava/lang/String;\n'
                '\n'
                '    return-void\n',
            )

        if False and smali.match('*/com/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter.smali'):
            fixed = fixed.replace(
                '    .line 1508\n'
                '    :goto_1\n'
                '    invoke-static {}, Lcom/oplus/ocs/camera/platform/PlatformUtil;->getPlatformFlag()Ljava/lang/String;\n',
                '    .line 1508\n'
                '    :goto_1\n'
                '    const-string p1, "OP15Retry"\n'
                '\n'
                '    const-string v0, "onCameraOpened retryPendingPreview"\n'
                '\n'
                '    invoke-static {p1, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p1\n'
                '\n'
                '    iget-object p1, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter;->this$0:Lcom/oplus/ocs/camera/producer/ProducerImpl;\n'
                '\n'
                '    iget-object v0, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter;->mHandler:Landroid/os/Handler;\n'
                '\n'
                '    invoke-virtual {p1, v0}, Lcom/oplus/ocs/camera/producer/ProducerImpl;->retryPendingPreview(Landroid/os/Handler;)V\n'
                '\n'
                '    invoke-static {}, Lcom/oplus/ocs/camera/platform/PlatformUtil;->getPlatformFlag()Ljava/lang/String;\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-virtual {p1}, Landroid/os/ConditionVariable;->open()V\n'
                '\n'
                '    .line 1661\n'
                '    iget-object p1, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter;->mHandler:Landroid/os/Handler;\n',
                '    invoke-virtual {p1}, Landroid/os/ConditionVariable;->open()V\n'
                '\n'
                '    iget-object p1, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter;->this$0:Lcom/oplus/ocs/camera/producer/ProducerImpl;\n'
                '\n'
                '    iget-object v0, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter;->mHandler:Landroid/os/Handler;\n'
                '\n'
                '    invoke-virtual {p1, v0}, Lcom/oplus/ocs/camera/producer/ProducerImpl;->retryPendingPreview(Landroid/os/Handler;)V\n'
                '\n'
                '    .line 1661\n'
                '    iget-object p1, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter;->mHandler:Landroid/os/Handler;\n',
            )

        if False and smali.match('*/com/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter.smali'):
            fixed = fixed.replace(
                '    .line 1497\n'
                '    :try_start_3\n'
                '    iget-object p1, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter;->mHandler:Landroid/os/Handler;\n'
                '\n'
                '    if-eqz p1, :cond_6\n'
                '\n'
                '    .line 1498\n'
                '    new-instance v0, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter$1;\n'
                '\n'
                '    invoke-direct {v0, p0}, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter$1;-><init>(Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter;)V\n'
                '\n'
                '    invoke-virtual {p1, v0}, Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z\n'
                '\n'
                '    goto :goto_1\n'
                '\n'
                '    .line 1505\n'
                '    :cond_6\n'
                '    iget-object p1, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter;->mCameraStateCallbackAdapter:Lcom/oplus/ocs/camera/appinterface/CameraStateCallbackAdapter;\n'
                '\n'
                '    iget-object v0, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter;->this$0:Lcom/oplus/ocs/camera/producer/ProducerImpl;\n'
                '\n'
                '    invoke-virtual {p1, v0}, Lcom/oplus/ocs/camera/appinterface/CameraStateCallbackAdapter;->onCameraOpened(Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;)V\n'
                '\n'
                '    .line 1508\n'
                '    :goto_1\n',
                '    .line 1497\n'
                '    :try_start_3\n'
                '    const-string p1, "OP15Unit"\n'
                '\n'
                '    const-string v0, "DefaultAdapter direct onCameraOpened callback"\n'
                '\n'
                '    invoke-static {p1, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p1\n'
                '\n'
                '    iget-object p1, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter;->mCameraStateCallbackAdapter:Lcom/oplus/ocs/camera/appinterface/CameraStateCallbackAdapter;\n'
                '\n'
                '    iget-object v0, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl$DefaultCameraStateCallbackAdapter;->this$0:Lcom/oplus/ocs/camera/producer/ProducerImpl;\n'
                '\n'
                '    invoke-virtual {p1, v0}, Lcom/oplus/ocs/camera/appinterface/CameraStateCallbackAdapter;->onCameraOpened(Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;)V\n'
                '\n'
                '    .line 1508\n'
                '    :goto_1\n',
                1,
            )

        if smali.match('*/com/oplus/ocs/camera/producer/ProducerImpl.smali'):
            fixed = fixed.replace(
                '    .line 139\n'
                '    iput-boolean p1, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl;->mbManageMultiDevice:Z\n',
                '    .line 139\n'
                '    const/4 p1, 0x0\n'
                '\n'
                '    iput-boolean p1, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl;->mbManageMultiDevice:Z\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-virtual {v0}, Lcom/oplus/ocs/camera/producer/device/CameraSessionEntity;->getOperationMode()I\n'
                '\n'
                '    move-result p5\n',
                '    invoke-virtual {v0}, Lcom/oplus/ocs/camera/producer/device/CameraSessionEntity;->getOperationMode()I\n'
                '\n'
                '    move-result p5\n'
                '\n'
                '    const/4 p5, 0x0\n',
                1,
            )
            fixed = _replace_smali_method(
                fixed,
                'public setParameter(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)V',
                '    .locals 1\n'
                '\n'
                '    iget-object v0, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl;->mAllStageParameterBuilder:Lcom/oplus/ocs/camera/metadata/parameter/PreviewParameter$Builder;\n'
                '\n'
                '    if-nez v0, :cond_0\n'
                '\n'
                '    new-instance v0, Lcom/oplus/ocs/camera/metadata/parameter/PreviewParameter$Builder;\n'
                '\n'
                '    invoke-direct {v0}, Lcom/oplus/ocs/camera/metadata/parameter/PreviewParameter$Builder;-><init>()V\n'
                '\n'
                '    iput-object v0, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl;->mAllStageParameterBuilder:Lcom/oplus/ocs/camera/metadata/parameter/PreviewParameter$Builder;\n'
                '\n'
                '    :cond_0\n'
                '    invoke-virtual {v0, p1, p2}, Lcom/oplus/ocs/camera/metadata/parameter/PreviewParameter$Builder;->set(Landroid/hardware/camera2/CaptureRequest$Key;Ljava/lang/Object;)Lcom/oplus/ocs/camera/metadata/parameter/Parameter$BaseBuilder;\n'
                '\n'
                '    return-void\n',
            )
            fixed = _replace_smali_method(
                fixed,
                'public setParameter(Ljava/lang/String;Ljava/lang/Object;)V',
                '    .locals 1\n'
                '\n'
                '    iget-object v0, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl;->mAllStageParameterBuilder:Lcom/oplus/ocs/camera/metadata/parameter/PreviewParameter$Builder;\n'
                '\n'
                '    if-nez v0, :cond_0\n'
                '\n'
                '    new-instance v0, Lcom/oplus/ocs/camera/metadata/parameter/PreviewParameter$Builder;\n'
                '\n'
                '    invoke-direct {v0}, Lcom/oplus/ocs/camera/metadata/parameter/PreviewParameter$Builder;-><init>()V\n'
                '\n'
                '    iput-object v0, p0, Lcom/oplus/ocs/camera/producer/ProducerImpl;->mAllStageParameterBuilder:Lcom/oplus/ocs/camera/metadata/parameter/PreviewParameter$Builder;\n'
                '\n'
                '    :cond_0\n'
                '    invoke-virtual {v0, p1, p2}, Lcom/oplus/ocs/camera/metadata/parameter/PreviewParameter$Builder;->set(Ljava/lang/String;Ljava/lang/Object;)Lcom/oplus/ocs/camera/metadata/parameter/Parameter$BaseBuilder;\n'
                '\n'
                '    return-void\n',
            )
            # Keep original null-current-mode behavior instead of silently creating
            # a rear photo mode during switch/startPreview.

        if smali.match('*/wl/h.smali'):
            fixed = _noop_smali_method(fixed, 'public final run()V')

        if smali.match('*/nj/d.smali'):
            fixed = fixed.replace(
                '.method public final g7(II)V\n'
                '    .locals 6\n',
                '.method public final g7(II)V\n'
                '    .locals 6\n'
                '\n'
                '    const-string v0, "OP15Switch"\n'
                '\n'
                '    new-instance v1, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v2, "g7 target="\n'
                '\n'
                '    invoke-direct {v1, v2}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v1, p1}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v2, " openType="\n'
                '\n'
                '    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v1, p2}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v2, " paused="\n'
                '\n'
                '    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    iget-boolean v2, p0, Lnj/d;->d:Z\n'
                '\n'
                '    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v2, " switching="\n'
                '\n'
                '    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    iget-boolean v2, p0, Lnj/d;->e:Z\n'
                '\n'
                '    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v1\n'
                '\n'
                '    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n',
                1,
            )

        if smali.match('*/uj/g.smali'):
            fixed = fixed.replace(
                '.method public final n(IZ)Z\n'
                '    .locals 6\n',
                '.method public final n(IZ)Z\n'
                '    .locals 8\n'
                '\n'
                '    const-string v0, "OP15Switch"\n'
                '\n'
                '    new-instance v1, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v2, "DeviceProcessor.n entry arg="\n'
                '\n'
                '    invoke-direct {v1, v2}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v1, p1}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v2, " flag="\n'
                '\n'
                '    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v1, p2}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v1\n'
                '\n'
                '    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-interface {v2}, Lcom/oplus/camera/b;->a()Z\n'
                '\n'
                '    .line 70\n'
                '    .line 71\n'
                '    .line 72\n'
                '    move-result v0\n'
                '\n'
                '    .line 73\n',
                '    invoke-interface {v2}, Lcom/oplus/camera/b;->a()Z\n'
                '\n'
                '    .line 70\n'
                '    .line 71\n'
                '    .line 72\n'
                '    move-result v0\n'
                '\n'
                '    const-string v6, "OP15Switch"\n'
                '\n'
                '    new-instance v7, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v3, "DeviceProcessor.n active="\n'
                '\n'
                '    invoke-direct {v7, v3}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v7, v0}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v3, " openType="\n'
                '\n'
                '    invoke-virtual {v7, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v7, p1}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v7}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v7\n'
                '\n'
                '    invoke-static {v6, v7}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v6\n'
                '\n'
                '    const-string v3, "DeviceProcessor"\n'
                '\n'
                '    .line 73\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-interface {p1}, Ls7/x$h;->Y()J\n'
                '\n'
                '    .line 82\n'
                '    .line 83\n'
                '    .line 84\n'
                '    move-result-wide v4\n'
                '\n'
                '    .line 85\n',
                '    invoke-interface {p1}, Ls7/x$h;->Y()J\n'
                '\n'
                '    .line 82\n'
                '    .line 83\n'
                '    .line 84\n'
                '    move-result-wide v4\n'
                '\n'
                '    const-string v6, "OP15Switch"\n'
                '\n'
                '    new-instance v7, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string p1, "DeviceProcessor.n delay="\n'
                '\n'
                '    invoke-direct {v7, p1}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v7, v4, v5}, Ljava/lang/StringBuilder;->append(J)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v7}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v7\n'
                '\n'
                '    invoke-static {v6, v7}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v6\n'
                '\n'
                '    .line 85\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-interface {p1, v4, v5, p0}, Lf6/c;->s2(JLjava/lang/Runnable;)V\n'
                '\n'
                '    .line 106\n',
                '    invoke-interface {p1, v4, v5, p0}, Lf6/c;->s2(JLjava/lang/Runnable;)V\n'
                '\n'
                '    const-string p0, "OP15Switch"\n'
                '\n'
                '    const-string p1, "DeviceProcessor.n scheduled delayed"\n'
                '\n'
                '    invoke-static {p0, p1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p0\n'
                '\n'
                '    .line 106\n',
                1,
            )
            # Keep the stock app scheduler for immediate opens. Bypassing V5().R0()
            # can open the new camera device while leaving app-side mode/UI state on
            # the old camera, which is exactly what OP15 switch logs showed.
        if smali.match('*/uj/g$c.smali'):
            fixed = fixed.replace(
                '.method public final a()V\n'
                '    .locals 5\n'
                '\n'
                '    .line 1\n'
                '    const-string v0, "DeviceProcessor"\n',
                '.method public final a()V\n'
                '    .locals 5\n'
                '\n'
                '    const-string v0, "OP15Close"\n'
                '\n'
                '    const-string v1, "DeviceProcessor.closeComplete entry"\n'
                '\n'
                '    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n'
                '\n'
                '    .line 1\n'
                '    const-string v0, "DeviceProcessor"\n',
                1,
            )
            fixed = fixed.replace(
                '    :cond_2\n'
                '    return-void\n',
                '    :cond_2\n'
                '    const-string v0, "OP15Close"\n'
                '\n'
                '    const-string v1, "DeviceProcessor.closeComplete return"\n'
                '\n'
                '    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n'
                '\n'
                '    return-void\n',
                1,
            )
            fixed = fixed.replace(
                '.method public static g(Luj/g$c;ZIZ)V\n'
                '    .locals 12\n',
                '.method public static g(Luj/g$c;ZIZ)V\n'
                '    .locals 12\n'
                '\n'
                '    const-string v10, "OP15Switch"\n'
                '\n'
                '    new-instance v11, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v0, "responseCameraOpened entry first="\n'
                '\n'
                '    invoke-direct {v11, v0}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v11, p1}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v0, " cameraId="\n'
                '\n'
                '    invoke-virtual {v11, v0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v11, p2}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v0, " openedPaused="\n'
                '\n'
                '    invoke-virtual {v11, v0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v11, p3}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v11}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v11\n'
                '\n'
                '    invoke-static {v10, v11}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v10\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-virtual {p0}, Lpj/a;->d()I\n'
                '\n'
                '    .line 177\n'
                '    .line 178\n'
                '    .line 179\n'
                '    move-result p0\n'
                '\n'
                '    .line 180\n',
                '    invoke-virtual {p0}, Lpj/a;->d()I\n'
                '\n'
                '    .line 177\n'
                '    .line 178\n'
                '    .line 179\n'
                '    move-result p0\n'
                '\n'
                '    const-string v10, "OP15Switch"\n'
                '\n'
                '    new-instance v11, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v8, "responseCameraOpened taskCount="\n'
                '\n'
                '    invoke-direct {v11, v8}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v11, p0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v8, " cameraId="\n'
                '\n'
                '    invoke-virtual {v11, v8}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v11, p2}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v11}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v11\n'
                '\n'
                '    invoke-static {v10, v11}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v10\n'
                '\n'
                '    .line 180\n',
                1,
            )
            fixed = fixed.replace(
                '    if-eqz p0, :cond_6\n'
                '\n'
                '    .line 191\n',
                '    const-string v10, "OP15Switch"\n'
                '\n'
                '    new-instance v11, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v8, "responseCameraOpened taskInfoNull="\n'
                '\n'
                '    invoke-direct {v11, v8}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    if-nez p0, :cond_op15_task_not_null\n'
                '\n'
                '    const/4 v8, 0x1\n'
                '\n'
                '    goto :goto_op15_task_null_done\n'
                '\n'
                '    :cond_op15_task_not_null\n'
                '    const/4 v8, 0x0\n'
                '\n'
                '    :goto_op15_task_null_done\n'
                '    invoke-virtual {v11, v8}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v11}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v11\n'
                '\n'
                '    invoke-static {v10, v11}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v10\n'
                '\n'
                '    if-eqz p0, :cond_6\n'
                '\n'
                '    .line 191\n',
                1,
            )
            fixed = fixed.replace(
                '    iget-object p0, v7, Lmj/r3;->L:Lvj/k;\n'
                '\n'
                '    .line 324\n'
                '    .line 325\n'
                '    invoke-virtual {p0, p3}, Lvj/k;->q(Z)V\n',
                '    const-string v10, "OP15Switch"\n'
                '\n'
                '    const-string v11, "responseCameraOpened calling preview q"\n'
                '\n'
                '    invoke-static {v10, v11}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v10\n'
                '\n'
                '    iget-object p0, v7, Lmj/r3;->L:Lvj/k;\n'
                '\n'
                '    .line 324\n'
                '    .line 325\n'
                '    invoke-virtual {p0, p3}, Lvj/k;->q(Z)V\n',
                1,
            )
            fixed = fixed.replace(
                '    :cond_14\n'
                '    const-string p0, "responseCameraOpened, will create session in next task, so drop it!"\n',
                '    :cond_14\n'
                '    const-string v10, "OP15Switch"\n'
                '\n'
                '    const-string v11, "responseCameraOpened dropping for next task"\n'
                '\n'
                '    invoke-static {v10, v11}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v10\n'
                '\n'
                '    const-string p0, "responseCameraOpened, will create session in next task, so drop it!"\n',
                1,
            )
            fixed = fixed.replace(
                '.method public final f(Lcom/oplus/ocs/camera/CameraDevice;I)V\n'
                '    .locals 8\n',
                '.method public final f(Lcom/oplus/ocs/camera/CameraDevice;I)V\n'
                '    .locals 10\n',
                1,
            )
            fixed = fixed.replace(
                '    iget-boolean v0, p0, Luj/g;->w:Z\n'
                '\n'
                '    .line 35\n',
                '    iget-boolean v0, p0, Luj/g;->w:Z\n'
                '\n'
                '    const-string v8, "OP15Switch"\n'
                '\n'
                '    new-instance v9, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v3, "onCameraOpened entry cameraId="\n'
                '\n'
                '    invoke-direct {v9, v3}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v9, p2}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v3, " wasPausedOpen="\n'
                '\n'
                '    invoke-virtual {v9, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v9, v0}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v3, " openType="\n'
                '\n'
                '    invoke-virtual {v9, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    iget v3, p0, Luj/g;->m:I\n'
                '\n'
                '    invoke-virtual {v9, v3}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v9}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v9\n'
                '\n'
                '    invoke-static {v8, v9}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v8\n'
                '\n'
                '    .line 35\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-virtual {p0}, Lsj/a;->d()Z\n'
                '\n'
                '    .line 82\n'
                '    .line 83\n'
                '    .line 84\n'
                '    move-result v3\n'
                '\n'
                '    .line 85\n',
                '    invoke-virtual {p0}, Lsj/a;->d()Z\n'
                '\n'
                '    .line 82\n'
                '    .line 83\n'
                '    .line 84\n'
                '    move-result v3\n'
                '\n'
                '    new-instance v9, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v8, "onCameraOpened state isPaused="\n'
                '\n'
                '    invoke-direct {v9, v8}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v9, v3}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v8, " appBlocked="\n'
                '\n'
                '    invoke-virtual {v9, v8}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v9, p1}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v9}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v9\n'
                '\n'
                '    const-string v8, "OP15Switch"\n'
                '\n'
                '    invoke-static {v8, v9}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v8\n'
                '\n'
                '    .line 85\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-static {p0, v4, p2, v0}, Luj/g$c;->g(Luj/g$c;ZIZ)V\n'
                '\n'
                '    .line 564\n',
                '    const-string p1, "OP15Switch"\n'
                '\n'
                '    const-string v1, "onCameraOpened call response first=false"\n'
                '\n'
                '    invoke-static {p1, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p1\n'
                '\n'
                '    invoke-static {p0, v4, p2, v0}, Luj/g$c;->g(Luj/g$c;ZIZ)V\n'
                '\n'
                '    .line 564\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-static {p0, v2, p2, v0}, Luj/g$c;->g(Luj/g$c;ZIZ)V\n'
                '\n'
                '    .line 570\n',
                '    const-string p1, "OP15Switch"\n'
                '\n'
                '    const-string v1, "onCameraOpened call response first=true"\n'
                '\n'
                '    invoke-static {p1, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p1\n'
                '\n'
                '    invoke-static {p0, v2, p2, v0}, Luj/g$c;->g(Luj/g$c;ZIZ)V\n'
                '\n'
                '    .line 570\n',
                1,
            )

        if smali.match('*/s7/b1.smali'):
            fixed = fixed.replace(
                '.method public final A(Z)V\n'
                '    .locals 2\n',
                '.method public final A(Z)V\n'
                '    .locals 4\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-virtual {p0, v0}, Ls7/b1;->G(Ljava/lang/Runnable;)V\n'
                '\n'
                '    .line 36\n',
                '    const-string v2, "OP15Close"\n'
                '\n'
                '    const-string v3, "b1.A scheduling f0 close runnable"\n'
                '\n'
                '    invoke-static {v2, v3}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v2\n'
                '\n'
                '    invoke-virtual {p0, v0}, Ls7/b1;->G(Ljava/lang/Runnable;)V\n'
                '\n'
                '    const-string v2, "OP15Close"\n'
                '\n'
                '    const-string v3, "b1.A returned from G, waiting n"\n'
                '\n'
                '    invoke-static {v2, v3}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v2\n'
                '\n'
                '    .line 36\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-virtual {p0}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    .line 47\n'
                '    .line 48\n'
                '    .line 49\n'
                '    const-string p0, "closeCameraDevice X"\n',
                '    invoke-virtual {p0}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    const-string p0, "OP15Close"\n'
                '\n'
                '    const-string v0, "b1.A n released"\n'
                '\n'
                '    invoke-static {p0, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p0\n'
                '\n'
                '    .line 47\n'
                '    .line 48\n'
                '    .line 49\n'
                '    const-string p0, "closeCameraDevice X"\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-virtual {v0, v7}, Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z\n'
                '\n'
                '    .line 30\n'
                '    .line 31\n'
                '    .line 32\n'
                '    return-void\n'
                '.end method',
                '    invoke-virtual {v0, v7}, Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z\n'
                '\n'
                '    move-result v0\n'
                '\n'
                '    const-string v1, "OP15Preview"\n'
                '\n'
                '    new-instance v2, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v3, "b1.W post result="\n'
                '\n'
                '    invoke-direct {v2, v3}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v2, v0}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v3, " operation="\n'
                '\n'
                '    invoke-virtual {v2, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v2, p3}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v3, " mode="\n'
                '\n'
                '    invoke-virtual {v2, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v2, p4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v2}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v2\n'
                '\n'
                '    invoke-static {v1, v2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v1\n'
                '\n'
                '    .line 30\n'
                '    .line 31\n'
                '    .line 32\n'
                '    return-void\n'
                '.end method',
                1,
            )

        if smali.match('*/s7/f0.smali'):
            fixed = fixed.replace(
                '.method public final run()V\n'
                '    .locals 7\n',
                '.method public final run()V\n'
                '    .locals 7\n'
                '\n'
                '    const-string v3, "OP15Close"\n'
                '\n'
                '    const-string v4, "f0.run entry"\n'
                '\n'
                '    invoke-static {v3, v4}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v3\n',
                1,
            )
            fixed = fixed.replace(
                '    iget-object v1, v0, Ls7/b1;->q:Landroid/os/ConditionVariable;\n'
                '\n'
                '    .line 6\n'
                '    .line 7\n'
                '    invoke-virtual {v1}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    .line 8\n',
                '    iget-object v1, v0, Ls7/b1;->q:Landroid/os/ConditionVariable;\n'
                '\n'
                '    const-string v3, "OP15Close"\n'
                '\n'
                '    const-string v4, "f0 waiting q"\n'
                '\n'
                '    invoke-static {v3, v4}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v3\n'
                '\n'
                '    .line 6\n'
                '    .line 7\n'
                '    invoke-virtual {v1}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    const-string v3, "OP15Close"\n'
                '\n'
                '    const-string v4, "f0 q released, closing device"\n'
                '\n'
                '    invoke-static {v3, v4}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v3\n'
                '\n'
                '    .line 8\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-virtual {v0, v3, p0}, Lcom/oplus/ocs/camera/CameraDevice;->close(ZZ)V\n'
                '\n'
                '    .line 52\n',
                '    invoke-virtual {v0, v3, p0}, Lcom/oplus/ocs/camera/CameraDevice;->close(ZZ)V\n'
                '\n'
                '    const-string p0, "OP15Close"\n'
                '\n'
                '    const-string v0, "f0 returned from CameraDevice.close"\n'
                '\n'
                '    invoke-static {p0, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p0\n'
                '\n'
                '    .line 52\n',
                1,
            )

        if smali.match('*/s7/g0.smali'):
            fixed = fixed.replace(
                '.method public final run()V\n'
                '    .locals 15\n',
                '.method public final run()V\n'
                '    .locals 15\n'
                '\n'
                '    const-string v13, "OP15Preview"\n'
                '\n'
                '    const-string v14, "g0 run entry"\n'
                '\n'
                '    invoke-static {v13, v14}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v13\n',
                1,
            )
            fixed = fixed.replace(
                '    iget-object v6, v0, Ls7/b1;->o:Landroid/os/ConditionVariable;\n'
                '\n'
                '    .line 387\n'
                '    .line 388\n'
                '    invoke-virtual {v6}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    .line 389\n',
                '    iget-object v6, v0, Ls7/b1;->o:Landroid/os/ConditionVariable;\n'
                '\n'
                '    const-string v13, "OP15Preview"\n'
                '\n'
                '    const-string v14, "g0 waiting session configured"\n'
                '\n'
                '    invoke-static {v13, v14}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v13\n'
                '\n'
                '    .line 387\n'
                '    .line 388\n'
                '    invoke-virtual {v6}, Landroid/os/ConditionVariable;->block()V\n'
                '\n'
                '    const-string v13, "OP15Preview"\n'
                '\n'
                '    const-string v14, "g0 session configured released"\n'
                '\n'
                '    invoke-static {v13, v14}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v13\n'
                '\n'
                '    .line 389\n',
                1,
            )

        if smali.match('*/uj/b.smali'):
            fixed = fixed.replace(
                '.method public final run()V\n'
                '    .locals 13\n',
                '.method public final run()V\n'
                '    .locals 13\n'
                '\n'
                '    const-string v9, "OP15Switch"\n'
                '\n'
                '    const-string v10, "OpenRunnable.run entry"\n'
                '\n'
                '    invoke-static {v9, v10}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v9\n',
                1,
            )
            fixed = fixed.replace(
                '    new-instance v9, Luj/e;\n'
                '\n'
                '    .line 166\n',
                '    const-string v9, "OP15Switch"\n'
                '\n'
                '    new-instance v10, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v11, "OpenRunnable resolved cameraId="\n'
                '\n'
                '    invoke-direct {v10, v11}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v10, v4}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v11, " openType="\n'
                '\n'
                '    invoke-virtual {v10, v11}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v10, v1}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v10}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v10\n'
                '\n'
                '    invoke-static {v9, v10}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v9\n'
                '\n'
                '    new-instance v9, Luj/e;\n'
                '\n'
                '    .line 166\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-interface {p0, v4, v3}, Ls7/x$c;->s(ILs7/x$d;)V\n'
                '\n'
                '    .line 346\n',
                '    invoke-interface {p0, v4, v3}, Ls7/x$c;->s(ILs7/x$d;)V\n'
                '\n'
                '    const-string p0, "OP15Switch"\n'
                '\n'
                '    const-string v3, "OpenRunnable requested camera open"\n'
                '\n'
                '    invoke-static {p0, v3}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p0\n'
                '\n'
                '    .line 346\n',
                1,
            )

        if smali.match('*/t5/x0.smali'):
            fixed = _noop_smali_method(fixed, 'public static varargs c([I)V')
            fixed = _noop_smali_method(fixed, 'public static varargs g(Lt5/x0$a;[I)V')

        if smali.match('*/a7/i3.smali'):
            fixed = _noop_smali_method(fixed, 'static constructor <clinit>()V')
            fixed = fixed.replace(
                'Lcom/oplus/shoulderpressure/OplusShoulderPressureManager;',
                'Ljava/lang/Object;',
            )

        if smali.match('*/a7/c3.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public static a(Landroid/content/Context;)I',
                '    .locals 1\n'
                '\n'
                '    const/16 v0, 0xff\n'
                '\n'
                '    return v0\n'
            )

        if smali.match('*/a7/e1.smali'):
            fixed = _noop_smali_method(fixed, 'public static e(I)V')

        if smali.match('*/s7/p.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public static c(I)Ljava/lang/String;',
                '    .locals 1\n'
                '\n'
                '    packed-switch p0, :pswitch_data_0\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return-object v0\n'
                '\n'
                '    :pswitch_0\n'
                '    const-string v0, "rear_main"\n'
                '\n'
                '    return-object v0\n'
                '\n'
                '    :pswitch_1\n'
                '    const-string v0, "front_main"\n'
                '\n'
                '    return-object v0\n'
                '\n'
                '    :pswitch_2\n'
                '    const-string v0, "rear_wide"\n'
                '\n'
                '    return-object v0\n'
                '\n'
                '    :pswitch_3\n'
                '    const-string v0, "rear_tele"\n'
                '\n'
                '    return-object v0\n'
                '\n'
                '    :pswitch_4\n'
                '    const-string v0, "rear_ultra_tele"\n'
                '\n'
                '    return-object v0\n'
                '\n'
                '    :pswitch_data_0\n'
                '    .packed-switch 0x0\n'
                '        :pswitch_0\n'
                '        :pswitch_1\n'
                '        :pswitch_2\n'
                '        :pswitch_3\n'
                '        :pswitch_4\n'
                '    .end packed-switch\n',
            )

        if smali.match('*/s7/j.smali'):
            fixed = re.sub(
                r'(?ms)^(\s*)invoke-interface \{v0\}, Ljava/util/List;->size\(\)I\n'
                r'\n'
                r'\s*\.line 1062\n'
                r'\s*\.line 1063\n'
                r'\s*\.line 1064\n'
                r'\s*move-result v0\n'
                r'\n'
                r'\s*\.line 1065\n',
                r'\1move v0, v1\n\n    .line 1065\n',
                fixed,
                count=1,
            )

        if smali.match('*/tk/g.smali'):
            fixed = fixed.replace(
                '    :cond_c\n'
                '    :goto_4\n'
                '    iget-boolean p1, p0, Ltk/g;->S0:Z\n'
                '\n'
                '    .line 213\n'
                '    .line 214\n'
                '    if-eqz p1, :cond_f\n'
                '\n'
                '    .line 215\n',
                '    :cond_c\n'
                '    :goto_4\n'
                '    const/4 p1, 0x1\n'
                '\n'
                '    .line 213\n'
                '    .line 214\n'
                '    if-eqz p1, :cond_f\n'
                '\n'
                '    .line 215\n',
                1,
            )

        if smali.match('*/mm/d2.smali') or smali.match('*/mm/h2.smali') or smali.match('*/ai/a.smali'):
            fixed = re.sub(
                r'(?m)^\.implements Landroid/os/OplusKeyEventManager\$OnKeyEventObserver;\n',
                '',
                fixed,
            )

        if smali.match('*/mm/g2.smali'):
            fixed = _noop_smali_method(fixed, 'public final b(Landroid/app/Activity;)V')
            fixed = _noop_smali_method(fixed, 'public final c(Landroid/app/Activity;)V')

        if smali.match('*/mm/i2.smali'):
            fixed = _noop_smali_method(fixed, 'public final b(Landroid/app/Activity;)V')
            fixed = _noop_smali_method(fixed, 'public final c(Landroid/app/Activity;)V')

        if smali.match('*/ai/b.smali'):
            fixed = re.sub(
                r'(?ms)^(\s*)invoke-static \{\}, Landroid/os/OplusKeyEventManager;->getInstance\(\)Landroid/os/OplusKeyEventManager;\n'
                r'.*?^\s*invoke-virtual \{[^}]+\}, Landroid/os/OplusKeyEventManager;->[^\n]+\n'
                r'\s*move-result ([vp]\d+)',
                r'\1const/4 \2, 0x0',
                fixed,
            )
            fixed = re.sub(
                r'(?ms)^(\s*)invoke-static \{\}, Landroid/os/OplusKeyEventManager;->getInstance\(\)Landroid/os/OplusKeyEventManager;\n'
                r'.*?^\s*move-result-object ([vp]\d+)\n'
                r'.*?^\s*invoke-virtual \{[^}]+\}, Landroid/os/OplusKeyEventManager;->[^\n]+\n'
                r'.*?^\s*move-result ([vp]\d+)',
                r'\1const/4 \3, 0x0',
                fixed,
            )

        if smali.match('*/k6/l.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public constructor <init>()V',
                '    .locals 2\n'
                '\n'
                '    invoke-direct {p0}, Ljava/lang/Object;-><init>()V\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    iput-boolean v0, p0, Lk6/l;->a:Z\n'
                '\n'
                '    iput-boolean v0, p0, Lk6/l;->e:Z\n'
                '\n'
                '    iput-boolean v0, p0, Lk6/l;->f:Z\n'
                '\n'
                '    iput v0, p0, Lk6/l;->i:I\n'
                '\n'
                '    iput-boolean v0, p0, Lk6/l;->j:Z\n'
                '\n'
                '    const-wide/16 v0, 0x0\n'
                '\n'
                '    iput-wide v0, p0, Lk6/l;->k:J\n'
                '\n'
                '    return-void\n'
            )
            fixed = _noop_smali_method(fixed, 'public final a(JZ)V')
            fixed = _noop_smali_method(fixed, 'public final b()V')
            fixed = _noop_smali_method(fixed, 'public final c()V')
            fixed = _noop_smali_method(fixed, 'public final d(I)V')
            fixed = _noop_smali_method(fixed, 'public final e()V')
            fixed = _noop_smali_method(fixed, 'public final f()V')
            fixed = _noop_smali_method(fixed, 'public final g(II)V')

        if smali.match('*/k6/l$a.smali'):
            fixed = _noop_smali_method(fixed, 'public final handleMessage(Landroid/os/Message;)V')

        if smali.match('*/p3/a.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public static a(Landroid/content/Context;)Ljava/lang/Object;',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return-object v0\n'
            )
            fixed = _replace_smali_method(
                fixed,
                'public static b(IIII)I',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n'
            )
            fixed = _replace_smali_method(
                fixed,
                'public static c()Z',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n'
            )
            fixed = _noop_smali_method(fixed, 'public static d(Landroid/content/Context;)V')
            fixed = _noop_smali_method(fixed, 'public static e(Ljava/lang/Object;IIIII)V')

        if smali.match('*/eo/j0.smali'):
            fixed = _noop_smali_method(fixed, 'public final b()V')

        if smali.match('*/eo/j0$a.smali') or smali.match('*/com/oplus/camera/feature/out/screen/capture/MultiDisplayManager$e.smali'):
            fixed = _noop_smali_method(fixed, 'public final onActivityEnter(Ljava/lang/Object;)V')
            fixed = _noop_smali_method(fixed, 'public final onActivityExit(Ljava/lang/Object;)V')
            fixed = _noop_smali_method(fixed, 'public final onAppEnter(Ljava/lang/Object;)V')
            fixed = _noop_smali_method(fixed, 'public final onAppExit(Ljava/lang/Object;)V')

        if smali.match('*/eo/s1.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public final a(Landroid/app/Activity;)Z',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n',
            )
            fixed = _noop_smali_method(fixed, 'public final c(Landroid/app/Activity;Lvj/d;)V')
            fixed = _noop_smali_method(fixed, 'public final d()V')
            fixed = _noop_smali_method(fixed, 'public final e()V')

        if smali.match('*/com/oplus/camera/feature/out/screen/capture/MultiDisplayManager.smali'):
            fixed = _noop_smali_method(fixed, 'public h(Landroid/content/Context;)V')

        if smali.match('*/com/oplus/camera/CameraManager.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public static V0()Z',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n',
            )
            fixed = _replace_smali_method(
                fixed,
                'public final m1(Z)V',
                '    .locals 1\n'
                '\n'
                '    iput-boolean p1, p0, Lcom/oplus/camera/CameraManager;->l0:Z\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    iput-boolean v0, p0, Lcom/oplus/camera/CameraManager;->m0:Z\n'
                '\n'
                '    return-void\n',
            )
            fixed = _noop_smali_method(fixed, 'public final F6()V')

        if False and smali.match('*/com/oplus/ocs/camera/CameraDeviceAdapterV2.smali'):
            fixed = fixed.replace(
                '.field private mCameraDeviceInterface:Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;\n',
                '.field private static sOp15LastPreviewAssistCallback:Lcom/oplus/ocs/camera/CameraPreviewAssistCallback;\n'
                '\n'
                '.field private static sOp15LastPreviewCallback:Lcom/oplus/ocs/camera/CameraPreviewCallback;\n'
                '\n'
                '.field private static sOp15LastPreviewHandler:Landroid/os/Handler;\n'
                '\n'
                '.field private static sOp15LastPreviewSurfaces:Ljava/util/Map;\n'
                '\n'
                '.field private static sOp15LastSdkConfig:Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;\n'
                '\n'
                '.field private mCameraDeviceInterface:Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;\n',
                1,
            )
            fixed = _replace_smali_method(
                fixed,
                'public constructor <init>(Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;)V',
                '    .locals 0\n'
                '\n'
                '    invoke-direct {p0}, Lcom/oplus/ocs/camera/CameraDeviceAdapter;-><init>()V\n'
                '\n'
                '    iput-object p1, p0, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->mCameraDeviceInterface:Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;\n'
                '\n'
                '    return-void\n',
            )
            fixed = _replace_smali_method(
                fixed,
                'public configure(Lcom/oplus/ocs/camera/CameraDeviceConfig;)V',
                '    .locals 4\n'
                '\n'
                '    iget-object v0, p0, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->mCameraDeviceInterface:Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;\n'
                '\n'
                '    if-eqz v0, :cond_0\n'
                '\n'
                '    invoke-virtual {p1}, Lcom/oplus/ocs/camera/CameraDeviceConfig;->getConfig()Ljava/lang/Object;\n'
                '\n'
                '    move-result-object v0\n'
                '\n'
                '    instance-of v0, v0, Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;\n'
                '\n'
                '    if-eqz v0, :cond_0\n'
                '\n'
                '    iget-object p0, p0, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->mCameraDeviceInterface:Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;\n'
                '\n'
                '    invoke-virtual {p1}, Lcom/oplus/ocs/camera/CameraDeviceConfig;->getConfig()Ljava/lang/Object;\n'
                '\n'
                '    move-result-object p1\n'
                '\n'
                '    check-cast p1, Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;\n'
                '\n'
                '    sput-object p1, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastSdkConfig:Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;\n'
                '\n'
                '    invoke-interface {p0, p1}, Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;->configure(Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;)V\n'
                '\n'
                '    sget-object p1, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewSurfaces:Ljava/util/Map;\n'
                '\n'
                '    if-eqz p1, :cond_0\n'
                '\n'
                '    sget-object v0, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewCallback:Lcom/oplus/ocs/camera/CameraPreviewCallback;\n'
                '\n'
                '    if-eqz v0, :cond_0\n'
                '\n'
                '    sget-object v1, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewHandler:Landroid/os/Handler;\n'
                '\n'
                '    if-eqz v1, :cond_0\n'
                '\n'
                '    const-string v2, "OP15Preview"\n'
                '\n'
                '    const-string v3, "configure replay cached startPreview"\n'
                '\n'
                '    invoke-static {v2, v3}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v2\n'
                '\n'
                '    new-instance v2, Lcom/oplus/ocs/camera/CameraPreviewCallbackAdapterV2;\n'
                '\n'
                '    invoke-direct {v2, v0}, Lcom/oplus/ocs/camera/CameraPreviewCallbackAdapterV2;-><init>(Lcom/oplus/ocs/camera/CameraPreviewCallback;)V\n'
                '\n'
                '    sget-object v0, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewAssistCallback:Lcom/oplus/ocs/camera/CameraPreviewAssistCallback;\n'
                '\n'
                '    new-instance v3, Lcom/oplus/ocs/camera/CameraPreviewAssistCallbackAdapterV2;\n'
                '\n'
                '    invoke-direct {v3, v0}, Lcom/oplus/ocs/camera/CameraPreviewAssistCallbackAdapterV2;-><init>(Lcom/oplus/ocs/camera/CameraPreviewAssistCallback;)V\n'
                '\n'
                '    invoke-interface {p0, p1, v2, v1, v3}, Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;->startPreview(Ljava/util/Map;Lcom/oplus/ocs/camera/appinterface/CameraPreviewCallbackAdapter;Landroid/os/Handler;Lcom/oplus/ocs/camera/appinterface/CameraPreviewAssistCallbackAdapter;)V\n'
                '\n'
                '    :cond_0\n'
                '    return-void\n',
            )
            fixed = _replace_smali_method(
                fixed,
                'public startPreview(Ljava/util/Map;Lcom/oplus/ocs/camera/CameraPreviewCallback;Landroid/os/Handler;Lcom/oplus/ocs/camera/CameraPreviewAssistCallback;)V',
                '    .locals 1\n'
                '    .annotation system Ldalvik/annotation/Signature;\n'
                '        value = {\n'
                '            "(",\n'
                '            "Ljava/util/Map<",\n'
                '            "Ljava/lang/String;",\n'
                '            "Landroid/view/Surface;",\n'
                '            ">;",\n'
                '            "Lcom/oplus/ocs/camera/CameraPreviewCallback;",\n'
                '            "Landroid/os/Handler;",\n'
                '            "Lcom/oplus/ocs/camera/CameraPreviewAssistCallback;",\n'
                '            ")V"\n'
                '        }\n'
                '    .end annotation\n'
                '\n'
                '    sput-object p1, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewSurfaces:Ljava/util/Map;\n'
                '\n'
                '    sput-object p2, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewCallback:Lcom/oplus/ocs/camera/CameraPreviewCallback;\n'
                '\n'
                '    sput-object p3, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewHandler:Landroid/os/Handler;\n'
                '\n'
                '    sput-object p4, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewAssistCallback:Lcom/oplus/ocs/camera/CameraPreviewAssistCallback;\n'
                '\n'
                '    const-string v0, "OP15Preview"\n'
                '\n'
                '    const-string p2, "cache startPreview args"\n'
                '\n'
                '    invoke-static {v0, p2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p2\n'
                '\n'
                '    iget-object p0, p0, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->mCameraDeviceInterface:Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;\n'
                '\n'
                '    if-eqz p0, :cond_0\n'
                '\n'
                '    new-instance v0, Lcom/oplus/ocs/camera/CameraPreviewCallbackAdapterV2;\n'
                '\n'
                '    sget-object p2, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewCallback:Lcom/oplus/ocs/camera/CameraPreviewCallback;\n'
                '\n'
                '    invoke-direct {v0, p2}, Lcom/oplus/ocs/camera/CameraPreviewCallbackAdapterV2;-><init>(Lcom/oplus/ocs/camera/CameraPreviewCallback;)V\n'
                '\n'
                '    new-instance p2, Lcom/oplus/ocs/camera/CameraPreviewAssistCallbackAdapterV2;\n'
                '\n'
                '    invoke-direct {p2, p4}, Lcom/oplus/ocs/camera/CameraPreviewAssistCallbackAdapterV2;-><init>(Lcom/oplus/ocs/camera/CameraPreviewAssistCallback;)V\n'
                '\n'
                '    invoke-interface {p0, p1, v0, p3, p2}, Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;->startPreview(Ljava/util/Map;Lcom/oplus/ocs/camera/appinterface/CameraPreviewCallbackAdapter;Landroid/os/Handler;Lcom/oplus/ocs/camera/appinterface/CameraPreviewAssistCallbackAdapter;)V\n'
                '\n'
                '    :cond_0\n'
                '    return-void\n',
            )
            fixed = fixed.replace(
                '\n.method public resumeRecording()V\n',
                '\n.method public op15ReplayCachedPreview()V\n'
                '    .locals 5\n'
                '\n'
                '    iget-object p0, p0, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->mCameraDeviceInterface:Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;\n'
                '\n'
                '    if-eqz p0, :cond_0\n'
                '\n'
                '    sget-object v0, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastSdkConfig:Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;\n'
                '\n'
                '    if-eqz v0, :cond_op15_no_config\n'
                '\n'
                '    const-string v3, "OP15Preview"\n'
                '\n'
                '    const-string v4, "onOpened replay cached configure"\n'
                '\n'
                '    invoke-static {v3, v4}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v3\n'
                '\n'
                '    invoke-interface {p0, v0}, Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;->configure(Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;)V\n'
                '\n'
                '    :cond_op15_no_config\n'
                '    sget-object v0, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewSurfaces:Ljava/util/Map;\n'
                '\n'
                '    if-eqz v0, :cond_0\n'
                '\n'
                '    sget-object v1, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewCallback:Lcom/oplus/ocs/camera/CameraPreviewCallback;\n'
                '\n'
                '    if-eqz v1, :cond_0\n'
                '\n'
                '    sget-object v2, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewHandler:Landroid/os/Handler;\n'
                '\n'
                '    if-eqz v2, :cond_0\n'
                '\n'
                '    const-string v3, "OP15Preview"\n'
                '\n'
                '    const-string v4, "onOpened replay cached startPreview"\n'
                '\n'
                '    invoke-static {v3, v4}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v3\n'
                '\n'
                '    new-instance v3, Lcom/oplus/ocs/camera/CameraPreviewCallbackAdapterV2;\n'
                '\n'
                '    invoke-direct {v3, v1}, Lcom/oplus/ocs/camera/CameraPreviewCallbackAdapterV2;-><init>(Lcom/oplus/ocs/camera/CameraPreviewCallback;)V\n'
                '\n'
                '    sget-object v1, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->sOp15LastPreviewAssistCallback:Lcom/oplus/ocs/camera/CameraPreviewAssistCallback;\n'
                '\n'
                '    new-instance v4, Lcom/oplus/ocs/camera/CameraPreviewAssistCallbackAdapterV2;\n'
                '\n'
                '    invoke-direct {v4, v1}, Lcom/oplus/ocs/camera/CameraPreviewAssistCallbackAdapterV2;-><init>(Lcom/oplus/ocs/camera/CameraPreviewAssistCallback;)V\n'
                '\n'
                '    invoke-interface {p0, v0, v3, v2, v4}, Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;->startPreview(Ljava/util/Map;Lcom/oplus/ocs/camera/appinterface/CameraPreviewCallbackAdapter;Landroid/os/Handler;Lcom/oplus/ocs/camera/appinterface/CameraPreviewAssistCallbackAdapter;)V\n'
                '\n'
                '    :cond_0\n'
                '    return-void\n'
                '.end method\n'
                '\n.method public resumeRecording()V\n',
                1,
            )

        if False and smali.match('*/com/oplus/ocs/camera/CameraStateCallbackAdapterV2.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public onCameraOpened(Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;)V',
                '    .locals 4\n'
                '\n'
                '    invoke-super {p0, p1}, Lcom/oplus/ocs/camera/appinterface/CameraStateCallbackAdapter;->onCameraOpened(Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;)V\n'
                '\n'
                '    const-string v0, "OP15Unit"\n'
                '\n'
                '    new-instance v1, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v2, "V2 onCameraOpened legacyCallback="\n'
                '\n'
                '    invoke-direct {v1, v2}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    iget-object v2, p0, Lcom/oplus/ocs/camera/CameraStateCallbackAdapterV2;->mCameraStateCallback:Lcom/oplus/ocs/camera/CameraStateCallback;\n'
                '\n'
                '    if-eqz v2, :cond_op15_null_callback\n'
                '\n'
                '    invoke-virtual {v2}, Ljava/lang/Object;->getClass()Ljava/lang/Class;\n'
                '\n'
                '    move-result-object v3\n'
                '\n'
                '    invoke-virtual {v3}, Ljava/lang/Class;->getName()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v3\n'
                '\n'
                '    goto :goto_op15_log_callback\n'
                '\n'
                '    :cond_op15_null_callback\n'
                '    const-string v3, "null"\n'
                '\n'
                '    :goto_op15_log_callback\n'
                '    invoke-virtual {v1, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v1\n'
                '\n'
                '    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n'
                '\n'
                '    iget-object p0, p0, Lcom/oplus/ocs/camera/CameraStateCallbackAdapterV2;->mCameraStateCallback:Lcom/oplus/ocs/camera/CameraStateCallback;\n'
                '\n'
                '    if-eqz p0, :cond_0\n'
                '\n'
                '    new-instance v0, Lcom/oplus/ocs/camera/CameraDevice;\n'
                '\n'
                '    new-instance v1, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;\n'
                '\n'
                '    invoke-direct {v1, p1}, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;-><init>(Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;)V\n'
                '\n'
                '    invoke-direct {v0, v1}, Lcom/oplus/ocs/camera/CameraDevice;-><init>(Lcom/oplus/ocs/camera/CameraDeviceAdapter;)V\n'
                '\n'
                '    invoke-virtual {p0, v0}, Lcom/oplus/ocs/camera/CameraStateCallback;->onCameraOpened(Lcom/oplus/ocs/camera/CameraDevice;)V\n'
                '\n'
                '    :cond_0\n'
                '    return-void\n',
            )

        if smali.match('*/androidx/window/layout/a.smali'):
            fixed = fixed.replace(
                '    :pswitch_c\n'
                '    iget-object v0, p0, Landroidx/window/layout/a;->b:Ljava/lang/Object;\n',
                '    :pswitch_c\n'
                '    const-string v13, "OP15Switch"\n'
                '\n'
                '    const-string v14, "layout/a camera-open runnable entry"\n'
                '\n'
                '    invoke-static {v13, v14}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v13\n'
                '\n'
                '    iget-object v0, p0, Landroidx/window/layout/a;->b:Ljava/lang/Object;\n',
                1,
            )
            fixed = fixed.replace(
                '    iget-object v1, v0, Ls7/c1;->b:Ls7/b1;\n'
                '\n'
                '    .line 1450\n'
                '    .line 1451\n'
                '    iget-object v1, v1, Ls7/b1;->b:Ls7/v;\n'
                '\n'
                '    .line 1452\n'
                '    .line 1453\n'
                '    if-eqz v1, :cond_19\n',
                '    iget-object v1, v0, Ls7/c1;->b:Ls7/b1;\n'
                '\n'
                '    .line 1450\n'
                '    .line 1451\n'
                '    iget-object v1, v1, Ls7/b1;->b:Ls7/v;\n'
                '\n'
                '    .line 1452\n'
                '    .line 1453\n'
                '    if-eqz v1, :cond_op15_layout_null_device\n'
                '\n'
                '    goto :goto_op15_layout_has_device\n'
                '\n'
                '    :cond_op15_layout_null_device\n'
                '    const-string v13, "OP15Switch"\n'
                '\n'
                '    const-string v14, "layout/a skip: b1 camera wrapper is null"\n'
                '\n'
                '    invoke-static {v13, v14}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v13\n'
                '\n'
                '    goto :cond_19\n'
                '\n'
                '    :goto_op15_layout_has_device\n',
                1,
            )
            fixed = fixed.replace(
                '    iget v0, v0, Ls7/b1;->t:I\n'
                '\n'
                '    .line 1460\n'
                '    .line 1461\n'
                '    invoke-interface {v1, p0, v0}, Ls7/x$d;->f(Lcom/oplus/ocs/camera/CameraDevice;I)V\n',
                '    iget v0, v0, Ls7/b1;->t:I\n'
                '\n'
                '    const-string v13, "OP15Switch"\n'
                '\n'
                '    new-instance v14, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v12, "layout/a dispatch app onCameraOpened cameraId="\n'
                '\n'
                '    invoke-direct {v14, v12}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v14, v0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v14}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v14\n'
                '\n'
                '    invoke-static {v13, v14}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v13\n'
                '\n'
                '    .line 1460\n'
                '    .line 1461\n'
                '    invoke-interface {v1, p0, v0}, Ls7/x$d;->f(Lcom/oplus/ocs/camera/CameraDevice;I)V\n',
                1,
            )

        if smali.match('*/s7/c1.smali'):
            fixed = fixed.replace(
                '.method public final onCameraOpened(Lcom/oplus/ocs/camera/CameraDevice;)V\n'
                '    .locals 4\n',
                '.method public final onCameraOpened(Lcom/oplus/ocs/camera/CameraDevice;)V\n'
                '    .locals 6\n',
                1,
            )
            fixed = fixed.replace(
                '.method public final onCameraClosed()V\n'
                '    .locals 5\n',
                '.method public final onCameraClosed()V\n'
                '    .locals 5\n'
                '\n'
                '    const-string v0, "OP15Close"\n'
                '\n'
                '    const-string v1, "c1.onCameraClosed entry"\n'
                '\n'
                '    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n',
                1,
            )
            fixed = fixed.replace(
                '    iget-object p0, v3, Ls7/b1;->p:Landroid/os/ConditionVariable;\n'
                '\n'
                '    .line 67\n'
                '    .line 68\n'
                '    invoke-virtual {p0}, Landroid/os/ConditionVariable;->open()V\n'
                '\n'
                '    .line 69\n',
                '    iget-object p0, v3, Ls7/b1;->p:Landroid/os/ConditionVariable;\n'
                '\n'
                '    .line 67\n'
                '    .line 68\n'
                '    invoke-virtual {p0}, Landroid/os/ConditionVariable;->open()V\n'
                '\n'
                '    const-string p0, "OP15Close"\n'
                '\n'
                '    const-string v1, "c1.onCameraClosed opened n/o/p"\n'
                '\n'
                '    invoke-static {p0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p0\n'
                '\n'
                '    .line 69\n',
                1,
            )
            fixed = fixed.replace(
                '.method public final onSessionConfigured()V\n'
                '    .locals 3\n',
                '.method public final onSessionConfigured()V\n'
                '    .locals 3\n'
                '\n'
                '    const-string v1, "OP15Preview"\n'
                '\n'
                '    const-string v2, "c1 onSessionConfigured opens b1.o"\n'
                '\n'
                '    invoke-static {v1, v2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v1\n',
                1,
            )
            fixed = fixed.replace(
                '    iput v1, v0, Ls7/b1;->t:I\n'
                '\n'
                '    .line 47\n'
                '    .line 48\n'
                '    new-instance v1, Landroidx/window/embedding/c;\n'
                '\n'
                '    .line 49\n'
                '    .line 50\n'
                '    invoke-direct {v1, v2, p0, p1}, Landroidx/window/embedding/c;-><init>(ILjava/lang/Object;Ljava/lang/Object;)V\n'
                '\n'
                '    .line 51\n'
                '    .line 52\n'
                '    .line 53\n'
                '    invoke-virtual {v0, v1}, Ls7/b1;->G(Ljava/lang/Runnable;)V\n'
                '\n'
                '    .line 54\n'
                '    .line 55\n'
                '    .line 56\n'
                '    iget-object v1, v0, Ls7/b1;->v:Ls7/b1$a;\n'
                '\n'
                '    .line 57\n'
                '    .line 58\n'
                '    invoke-virtual {v1}, Lx6/c;->d()Landroid/os/Handler;\n'
                '\n'
                '    .line 59\n'
                '    .line 60\n'
                '    .line 61\n'
                '    move-result-object v1\n'
                '\n'
                '    .line 62\n'
                '    new-instance v3, Landroidx/window/layout/a;\n'
                '\n'
                '    .line 63\n'
                '    .line 64\n'
                '    invoke-direct {v3, v2, p0, p1}, Landroidx/window/layout/a;-><init>(ILjava/lang/Object;Ljava/lang/Object;)V\n'
                '\n'
                '    .line 65\n'
                '    .line 66\n'
                '    .line 67\n'
                '    invoke-virtual {v1, v3}, Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z\n'
                '\n'
                '    .line 68\n',
                '    iput v1, v0, Ls7/b1;->t:I\n'
                '\n'
                '    .line 47\n'
                '    .line 48\n'
                '    new-instance v1, Landroidx/window/embedding/c;\n'
                '\n'
                '    invoke-direct {v1, v2, p0, p1}, Landroidx/window/embedding/c;-><init>(ILjava/lang/Object;Ljava/lang/Object;)V\n'
                '\n'
                '    invoke-virtual {v0, v1}, Ls7/b1;->G(Ljava/lang/Runnable;)V\n'
                '\n'
                '    const-string v1, "OP15Switch"\n'
                '\n'
                '    const-string v3, "c1 initialized b1.G before camera-open dispatch"\n'
                '\n'
                '    invoke-static {v1, v3}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v1\n'
                '\n'
                '    iget-object v1, v0, Ls7/b1;->v:Ls7/b1$a;\n'
                '\n'
                '    invoke-virtual {v1}, Lx6/c;->d()Landroid/os/Handler;\n'
                '\n'
                '    move-result-object v1\n'
                '\n'
                '    new-instance v3, Landroidx/window/layout/a;\n'
                '\n'
                '    invoke-direct {v3, v2, p0, p1}, Landroidx/window/layout/a;-><init>(ILjava/lang/Object;Ljava/lang/Object;)V\n'
                '\n'
                '    invoke-virtual {v1, v3}, Landroid/os/Handler;->post(Ljava/lang/Runnable;)Z\n'
                '\n'
                '    move-result v3\n'
                '\n'
                '    const-string v4, "OP15Switch"\n'
                '\n'
                '    new-instance v5, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string p0, "c1 posted layout/a result="\n'
                '\n'
                '    invoke-direct {v5, p0}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v5, v3}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string p0, " handler="\n'
                '\n'
                '    invoke-virtual {v5, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v5, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/Object;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string p0, " looper="\n'
                '\n'
                '    invoke-virtual {v5, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v1}, Landroid/os/Handler;->getLooper()Landroid/os/Looper;\n'
                '\n'
                '    move-result-object p0\n'
                '\n'
                '    invoke-virtual {v5, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/Object;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v5}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object p0\n'
                '\n'
                '    invoke-static {v4, p0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p0\n'
                '\n'
                '    .line 68\n',
                1,
            )

        if smali.match('*/s7/c1$a.smali'):
            fixed = fixed.replace(
                '.method public final run()V\n'
                '    .locals 0\n'
                '\n'
                '    .line 1\n'
                '    iget-object p0, p0, Ls7/c1$a;->a:Ls7/c1;\n'
                '\n'
                '    .line 2\n'
                '    .line 3\n'
                '    iget-object p0, p0, Ls7/c1;->b:Ls7/b1;\n'
                '\n'
                '    .line 4\n'
                '    .line 5\n'
                '    iget-object p0, p0, Ls7/b1;->z:Ls7/x$d;\n'
                '\n'
                '    .line 6\n'
                '    .line 7\n'
                '    invoke-interface {p0}, Ls7/x$d;->a()V\n'
                '\n'
                '    .line 8\n'
                '    .line 9\n'
                '    .line 10\n'
                '    return-void\n'
                '.end method',
                '.method public final run()V\n'
                '    .locals 2\n'
                '\n'
                '    const-string v0, "OP15Close"\n'
                '\n'
                '    const-string v1, "c1$a run entry"\n'
                '\n'
                '    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n'
                '\n'
                '    .line 1\n'
                '    iget-object p0, p0, Ls7/c1$a;->a:Ls7/c1;\n'
                '\n'
                '    .line 2\n'
                '    .line 3\n'
                '    iget-object p0, p0, Ls7/c1;->b:Ls7/b1;\n'
                '\n'
                '    .line 4\n'
                '    .line 5\n'
                '    iget-object p0, p0, Ls7/b1;->z:Ls7/x$d;\n'
                '\n'
                '    const-string v0, "OP15Close"\n'
                '\n'
                '    const-string v1, "c1$a before z.a"\n'
                '\n'
                '    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v0\n'
                '\n'
                '    .line 6\n'
                '    .line 7\n'
                '    invoke-interface {p0}, Ls7/x$d;->a()V\n'
                '\n'
                '    const-string p0, "OP15Close"\n'
                '\n'
                '    const-string v0, "c1$a after z.a"\n'
                '\n'
                '    invoke-static {p0, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p0\n'
                '\n'
                '    .line 8\n'
                '    .line 9\n'
                '    .line 10\n'
                '    return-void\n'
                '.end method',
                1,
            )

        if smali.match('*/x6/z.smali'):
            fixed = fixed.replace(
                '.method public final a(Ljava/lang/String;Ljava/lang/Runnable;)V\n'
                '    .locals 1\n',
                '.method public final a(Ljava/lang/String;Ljava/lang/Runnable;)V\n'
                '    .locals 4\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-static {p1}, Ljava/util/Objects;->requireNonNull(Ljava/lang/Object;)Ljava/lang/Object;\n',
                '    const-string v1, "OP15TaskBus"\n'
                '\n'
                '    new-instance v2, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v3, "schedule task="\n'
                '\n'
                '    invoke-direct {v2, v3}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v2, p1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v2}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v2\n'
                '\n'
                '    invoke-static {v1, v2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v1\n'
                '\n'
                '    invoke-static {p1}, Ljava/util/Objects;->requireNonNull(Ljava/lang/Object;)Ljava/lang/Object;\n',
                1,
            )
            fixed = fixed.replace(
                '    iget-object p0, p0, Lx6/z;->a:Lx6/z$a;\n'
                '\n'
                '    .line 10\n'
                '    .line 11\n'
                '    invoke-virtual {p0, v0}, Ljava/util/concurrent/ThreadPoolExecutor;->execute(Ljava/lang/Runnable;)V\n',
                '    iget-object p0, p0, Lx6/z;->a:Lx6/z$a;\n'
                '\n'
                '    .line 10\n'
                '    .line 11\n'
                '    invoke-virtual {p0, v0}, Ljava/util/concurrent/ThreadPoolExecutor;->execute(Ljava/lang/Runnable;)V\n'
                '\n'
                '    const-string p0, "OP15TaskBus"\n'
                '\n'
                '    const-string p1, "execute accepted"\n'
                '\n'
                '    invoke-static {p0, p1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p0\n',
                1,
            )

        if smali.match('*/x6/z$d.smali'):
            fixed = fixed.replace(
                '.method public final run()V\n'
                '    .locals 3\n',
                '.method public final run()V\n'
                '    .locals 5\n',
                1,
            )
            fixed = fixed.replace(
                '    iget-object v0, p0, Lx6/z$d;->b:Ljava/lang/String;\n',
                '    iget-object v0, p0, Lx6/z$d;->b:Ljava/lang/String;\n'
                '\n'
                '    const-string v3, "OP15TaskBus"\n'
                '\n'
                '    new-instance v4, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v1, "run start task="\n'
                '\n'
                '    invoke-direct {v4, v1}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v4, v0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v4}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v4\n'
                '\n'
                '    invoke-static {v3, v4}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v3\n',
                1,
            )
            fixed = fixed.replace(
                '    invoke-interface {v1}, Ljava/lang/Runnable;->run()V\n',
                '    invoke-interface {v1}, Ljava/lang/Runnable;->run()V\n'
                '\n'
                '    const-string v3, "OP15TaskBus"\n'
                '\n'
                '    new-instance v4, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v1, "run end task="\n'
                '\n'
                '    invoke-direct {v4, v1}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-virtual {v4, v0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v4}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v4\n'
                '\n'
                '    invoke-static {v3, v4}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v3\n',
                1,
            )

        if smali.match('*/vj/i.smali'):
            fixed = fixed.replace(
                '.method public final run()V\n'
                '    .locals 10\n',
                '.method public final run()V\n'
                '    .locals 13\n'
                '\n'
                '    const-string v10, "OP15Preview"\n'
                '\n'
                '    const-string v11, "vj/i run entry"\n'
                '\n'
                '    invoke-static {v10, v11}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v10\n',
                1,
            )
            fixed = fixed.replace(
                '    iget-object p0, v0, Lvj/k;->L:Landroid/os/ConditionVariable;\n'
                '\n'
                '    .line 370\n'
                '    .line 371\n'
                '    invoke-virtual {p0}, Landroid/os/ConditionVariable;->open()V\n',
                '    iget-object p0, v0, Lvj/k;->L:Landroid/os/ConditionVariable;\n'
                '\n'
                '    const-string v10, "OP15Preview"\n'
                '\n'
                '    new-instance v11, Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v12, "vj/i opening k="\n'
                '\n'
                '    invoke-direct {v11, v12}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V\n'
                '\n'
                '    invoke-static {v0}, Ljava/lang/System;->identityHashCode(Ljava/lang/Object;)I\n'
                '\n'
                '    move-result v12\n'
                '\n'
                '    invoke-virtual {v11, v12}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    const-string v12, " L="\n'
                '\n'
                '    invoke-virtual {v11, v12}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-static {p0}, Ljava/lang/System;->identityHashCode(Ljava/lang/Object;)I\n'
                '\n'
                '    move-result v12\n'
                '\n'
                '    invoke-virtual {v11, v12}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;\n'
                '\n'
                '    invoke-virtual {v11}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
                '\n'
                '    move-result-object v11\n'
                '\n'
                '    invoke-static {v10, v11}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result v10\n'
                '\n'
                '    .line 370\n'
                '    .line 371\n'
                '    invoke-virtual {p0}, Landroid/os/ConditionVariable;->open()V\n'
                '\n'
                '    const-string p0, "OP15Preview"\n'
                '\n'
                '    const-string v10, "vj/i opened L condition"\n'
                '\n'
                '    invoke-static {p0, v10}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p0\n',
                1,
            )

        if smali.match('*/com/oplus/ocs/camera/producer/mode/BaseMode.smali'):
            fixed = fixed.replace(
                '    check-cast p2, Lcom/oplus/ocs/camera/common/util/ApsRequestTag;\n'
                '\n'
                '    iput-object p2, v2, Lcom/oplus/ocs/camera/common/util/CameraRequestTag;->mApsRequestTag:Lcom/oplus/ocs/camera/common/util/ApsRequestTag;\n',
                '    check-cast p2, Lcom/oplus/ocs/camera/common/util/ApsRequestTag;\n'
                '\n'
                '    if-nez p2, :cond_op15_aps_tag_ready\n'
                '\n'
                '    new-instance p2, Lcom/oplus/ocs/camera/common/util/ApsRequestTag;\n'
                '\n'
                '    invoke-direct {p2}, Lcom/oplus/ocs/camera/common/util/ApsRequestTag;-><init>()V\n'
                '\n'
                '    iget-object v6, p0, Lcom/oplus/ocs/camera/producer/mode/BaseMode;->mTagMap:Ljava/util/Map;\n'
                '\n'
                '    invoke-interface {v6, p1, p2}, Ljava/util/Map;->put(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;\n'
                '\n'
                '    move-result-object v6\n'
                '\n'
                '    :cond_op15_aps_tag_ready\n'
                '    iput-object p2, v2, Lcom/oplus/ocs/camera/common/util/CameraRequestTag;->mApsRequestTag:Lcom/oplus/ocs/camera/common/util/ApsRequestTag;\n',
                1,
            )
            fixed = fixed.replace(
                '    check-cast p2, Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;\n'
                '\n'
                '    .line 1725\n'
                '    invoke-virtual {p2}, Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;->getPictureSurfaces()Ljava/util/List;\n',
                '    check-cast p2, Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;\n'
                '\n'
                '    if-eqz p2, :cond_60\n'
                '\n'
                '    .line 1725\n'
                '    invoke-virtual {p2}, Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;->getPictureSurfaces()Ljava/util/List;\n',
                1,
            )
            fixed = _replace_smali_method(
                fixed,
                'final getConfigureParameter(Ljava/lang/String;)Lcom/oplus/ocs/camera/metadata/parameter/Parameter;',
                '    .locals 2\n'
                '\n'
                '    iget-object p0, p0, Lcom/oplus/ocs/camera/producer/mode/BaseMode;->mConfigMap:Ljava/util/concurrent/ConcurrentHashMap;\n'
                '\n'
                '    invoke-virtual {p0, p1}, Ljava/util/concurrent/ConcurrentHashMap;->get(Ljava/lang/Object;)Ljava/lang/Object;\n'
                '\n'
                '    move-result-object p0\n'
                '\n'
                '    check-cast p0, Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;\n'
                '\n'
                '    if-eqz p0, :cond_0\n'
                '\n'
                '    invoke-virtual {p0}, Lcom/oplus/ocs/camera/common/parameter/SdkCameraDeviceConfig;->getConfigureParameter()Lcom/oplus/ocs/camera/metadata/parameter/Parameter;\n'
                '\n'
                '    move-result-object p0\n'
                '\n'
                '    return-object p0\n'
                '\n'
                '    :cond_0\n'
                '    const-string p0, "OP15Preview"\n'
                '\n'
                '    const-string p1, "missing config, using empty configure parameter"\n'
                '\n'
                '    invoke-static {p0, p1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I\n'
                '\n'
                '    move-result p0\n'
                '\n'
                '    new-instance p0, Lcom/oplus/ocs/camera/metadata/parameter/ConfigureParameter$Builder;\n'
                '\n'
                '    invoke-direct {p0}, Lcom/oplus/ocs/camera/metadata/parameter/ConfigureParameter$Builder;-><init>()V\n'
                '\n'
                '    invoke-virtual {p0}, Lcom/oplus/ocs/camera/metadata/parameter/ConfigureParameter$Builder;->build()Lcom/oplus/ocs/camera/metadata/parameter/Parameter;\n'
                '\n'
                '    move-result-object p0\n'
                '\n'
                '    return-object p0\n',
            )

        if smali.match('*/a7/l0.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public static m(Ljava/lang/String;)Z',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n',
            )

        if smali.match('*/a7/u3.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public static a(Landroid/content/Context;)Landroid/graphics/Typeface;',
                '    .locals 1\n'
                '\n'
                '    sget-object v0, Landroid/graphics/Typeface;->DEFAULT:Landroid/graphics/Typeface;\n'
                '\n'
                '    return-object v0\n',
            )

        if smali.match('*/j3/a.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public static c(Landroid/content/res/Configuration;)Loplus/content/res/OplusExtraConfiguration;',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return-object v0\n',
            )

        fixed = re.sub(
            r'(?m)^(\s*)invoke-static \{[^}]+\}, Landroid/os/OplusManager;->onStamp\(Ljava/lang/String;Ljava/util/Map;\)V',
            r'\1nop',
            fixed,
        )

        if smali.match('*/pm/l1.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public final b()Z',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n',
            )

        if smali.match('*/l9/a.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public static g(Landroid/bluetooth/BluetoothDevice;)Z',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n',
            )
            fixed = _replace_smali_method(
                fixed,
                'public static i(Landroid/bluetooth/BluetoothDevice;)Z',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n',
            )

        if smali.match('*/eo/a.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public static b(I)I',
                '    .locals 1\n'
                '\n'
                '    invoke-static {}, Landroid/content/res/Resources;->getSystem()Landroid/content/res/Resources;\n'
                '\n'
                '    move-result-object p0\n'
                '\n'
                '    invoke-virtual {p0}, Landroid/content/res/Resources;->getDisplayMetrics()Landroid/util/DisplayMetrics;\n'
                '\n'
                '    move-result-object p0\n'
                '\n'
                '    iget v0, p0, Landroid/util/DisplayMetrics;->densityDpi:I\n'
                '\n'
                '    return v0\n',
            )

        if smali.match('*/com/oplus/camera/util/LayoutUtil.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public static x(Landroid/content/Context;)Z',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n',
            )

        if smali.match('*/n3/h.smali'):
            fixed = _noop_smali_method(fixed, 'public static e(Landroid/view/View;IIIIII)V')

        if smali.match('*/com/coui/appcompat/dialog/widget/COUIAlertDialogMaxLinearLayout.smali'):
            fixed = _noop_smali_method(fixed, 'private setOutLineProviderInternal(Landroid/graphics/Outline;)V')

        if smali.match('*/com/coui/appcompat/button/COUIButton$a.smali'):
            fixed = _noop_smali_method(fixed, 'public final getOutline(Landroid/view/View;Landroid/graphics/Outline;)V')

        if smali.match('*/com/coui/appcompat/tooltips/COUIToolTips$g.smali'):
            fixed = _noop_smali_method(fixed, 'public final getOutline(Landroid/view/View;Landroid/graphics/Outline;)V')

        if smali.match('*/v7/d.smali'):
            fixed = _noop_smali_method(fixed, 'public final d(Lcom/oplus/camera/MyApplication;)V')
            fixed = _noop_smali_method(fixed, 'public final g()V')

        if smali.match('*/hk/d.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public constructor <init>()V',
                '    .locals 3\n'
                '\n'
                '    invoke-direct {p0}, Ljava/lang/Object;-><init>()V\n'
                '\n'
                '    const/4 v0, 0x1\n'
                '\n'
                '    invoke-static {v0}, Ljava/util/concurrent/Executors;->newScheduledThreadPool(I)Ljava/util/concurrent/ScheduledExecutorService;\n'
                '\n'
                '    move-result-object v1\n'
                '\n'
                '    iput-object v1, p0, Lhk/d;->a:Ljava/util/concurrent/ScheduledExecutorService;\n'
                '\n'
                '    const/4 v1, 0x0\n'
                '\n'
                '    iput-object v1, p0, Lhk/d;->b:Ljava/lang/Object;\n'
                '\n'
                '    new-instance v1, Ljava/util/concurrent/atomic/AtomicInteger;\n'
                '\n'
                '    const/4 v2, 0x0\n'
                '\n'
                '    invoke-direct {v1, v2}, Ljava/util/concurrent/atomic/AtomicInteger;-><init>(I)V\n'
                '\n'
                '    iput-object v1, p0, Lhk/d;->d:Ljava/util/concurrent/atomic/AtomicInteger;\n'
                '\n'
                '    iput-boolean v0, p0, Lhk/d;->e:Z\n'
                '\n'
                '    iput-boolean v2, p0, Lhk/d;->f:Z\n'
                '\n'
                '    new-instance v0, Ljava/lang/Object;\n'
                '\n'
                '    invoke-direct {v0}, Ljava/lang/Object;-><init>()V\n'
                '\n'
                '    iput-object v0, p0, Lhk/d;->h:Ljava/lang/Object;\n'
                '\n'
                '    const/4 v0, -0x1\n'
                '\n'
                '    iput v0, p0, Lhk/d;->i:I\n'
                '\n'
                '    return-void\n',
            )
            fixed = re.sub(
                r'(?m)^(\s*)invoke-virtual \{[^}]+\}, Lcom/oplus/osense/OsenseResEventClient;->requestSceneAction\(Landroid/os/Bundle;\)V',
                r'\1nop',
                fixed,
            )
            fixed = fixed.replace(
                'Lcom/oplus/osense/OsenseResEventClient;',
                'Ljava/lang/Object;',
            )

        if fixed != data:
            smali.write_text(fixed, encoding='utf-8')


def blob_fixup_opluscamera_defer_job_count(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = next(Path(tmp_dir).glob('smali*/ac/o0.smali'), None)
    if smali is None:
        return

    data = smali.read_text(encoding='utf-8')
    fixed = _replace_smali_method(
        data,
        'public final P()I',
        '    .locals 1\n'
        '\n'
        '    const/4 v0, 0x0\n'
        '\n'
        '    return v0\n',
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_camera_unit_op15_camera_type(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = next(
        Path(tmp_dir).glob('smali*/com/oplus/ocs/camera/producer/info/CameraCharacteristicsWrapper.smali'),
        None,
    )
    if smali is None:
        return

    data = smali.read_text(encoding='utf-8')
    fixed = data.replace(
        '    const-class v2, [I\n'
        '\n'
        '    invoke-direct {v0, v1, v2}, Landroid/hardware/camera2/CameraCharacteristics$Key;-><init>(Ljava/lang/String;Ljava/lang/Class;)V\n'
        '\n'
        '    sput-object v0, Lcom/oplus/ocs/camera/producer/info/CameraCharacteristicsWrapper;->KEY_CUSTOM_CAMERA_TYPE:Landroid/hardware/camera2/CameraCharacteristics$Key;\n',
        '    const-class v2, [I\n'
        '\n'
        '    const-class v3, [B\n'
        '\n'
        '    invoke-direct {v0, v1, v3}, Landroid/hardware/camera2/CameraCharacteristics$Key;-><init>(Ljava/lang/String;Ljava/lang/Class;)V\n'
        '\n'
        '    sput-object v0, Lcom/oplus/ocs/camera/producer/info/CameraCharacteristicsWrapper;->KEY_CUSTOM_CAMERA_TYPE:Landroid/hardware/camera2/CameraCharacteristics$Key;\n',
        1,
    )
    fixed = fixed.replace(
        '    invoke-virtual {v1, p1}, Landroid/hardware/camera2/CameraCharacteristics;->get(Landroid/hardware/camera2/CameraCharacteristics$Key;)Ljava/lang/Object;\n'
        '\n'
        '    move-result-object v0\n'
        '    :try_end_0\n',
        '    invoke-virtual {v1, p1}, Landroid/hardware/camera2/CameraCharacteristics;->get(Landroid/hardware/camera2/CameraCharacteristics$Key;)Ljava/lang/Object;\n'
        '\n'
        '    move-result-object v0\n'
        '\n'
        '    sget-object v1, Lcom/oplus/ocs/camera/producer/info/CameraCharacteristicsWrapper;->KEY_CUSTOM_CAMERA_TYPE:Landroid/hardware/camera2/CameraCharacteristics$Key;\n'
        '\n'
        '    if-ne p1, v1, :cond_op15_camera_type_done\n'
        '\n'
        '    instance-of v1, v0, [B\n'
        '\n'
        '    if-eqz v1, :cond_op15_camera_type_done\n'
        '\n'
        '    check-cast v0, [B\n'
        '\n'
        '    array-length v1, v0\n'
        '\n'
        '    new-array v1, v1, [I\n'
        '\n'
        '    const/4 v2, 0x0\n'
        '\n'
        '    :goto_op15_camera_type_loop\n'
        '    array-length v3, v0\n'
        '\n'
        '    if-ge v2, v3, :cond_op15_camera_type_converted\n'
        '\n'
        '    aget-byte v3, v0, v2\n'
        '\n'
        '    and-int/lit16 v3, v3, 0xff\n'
        '\n'
        '    aput v3, v1, v2\n'
        '\n'
        '    add-int/lit8 v2, v2, 0x1\n'
        '\n'
        '    goto :goto_op15_camera_type_loop\n'
        '\n'
        '    :cond_op15_camera_type_converted\n'
        '    move-object v0, v1\n'
        '\n'
        '    :cond_op15_camera_type_done\n'
        '    :try_end_0\n',
        1,
    )
    fixed = fixed.replace(
        '    move-result-object p0\n'
        '\n'
        '    check-cast p0, [I\n'
        '\n'
        '    if-eqz p0, :cond_0\n',
        '    move-result-object p0\n'
        '\n'
        '    if-eqz p0, :cond_0\n',
        1,
    )
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_camera_unit_sdk_runtime(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    replacements = {
        'com/google/oplus/protobuf/ExtensionRegistryLite.smali': (
            ('.field private static volatile eagerlyParseMessageSets:Z = false',
             '.field private static volatile eagerlyParseMessageSets:Z'),
        ),
        'com/oplus/camera/hdrtransform/HdrTransformPlatform.smali': (
            ('.field private static sAlgoExists:Z = false',
             '.field private static sAlgoExists:Z'),
            ('.field private static sLibraryLoaded:Z = false',
             '.field private static sLibraryLoaded:Z'),
        ),
        'com/oplus/ocs/camera/UxThreadPool.smali': (
            ('.field private static sThreadUxMap:Landroid/util/SparseArray; = null',
             '.field private static sThreadUxMap:Landroid/util/SparseArray;'),
            ('.field private static sbHasSetUx:Z = false',
             '.field private static sbHasSetUx:Z'),
        ),
        'com/oplus/ocs/camera/common/parameter/apsadapter/ApsHelper.smali': (
            ('.field private static bInit:Z = false',
             '.field private static bInit:Z'),
        ),
        'com/oplus/ocs/camera/common/util/OsenseKeyThreadHelper.smali': (
            ('.field private static sOsenseInit:Z = false',
             '.field private static sOsenseInit:Z'),
        ),
        'com/oplus/ocs/camera/consumer/ApsDataConvert.smali': (
            ('.field private static sbUnderWaterVideoStatus:Z = false',
             '.field private static sbUnderWaterVideoStatus:Z'),
        ),
        'com/oplus/ocs/camera/consumer/apsAdapter/ALog.smali': (
            ('.field private static volatile sEnable:Z = false',
             '.field private static volatile sEnable:Z'),
            ('.field private static volatile sJNILoadFailed:Z = false',
             '.field private static volatile sJNILoadFailed:Z'),
            ('.field private static volatile sLogEncryptEnable:Z = false',
             '.field private static volatile sLogEncryptEnable:Z'),
        ),
        'com/oplus/statistics/util/LogUtil.smali': (
            ('.field private static isDebug:Z = false',
             '.field private static isDebug:Z'),
        ),
    }

    for relative, pairs in replacements.items():
        smali = next(Path(tmp_dir).glob(f'smali*/{relative}'), None)
        if smali is None:
            continue
        data = smali.read_text(encoding='utf-8')
        fixed = data
        for old, new in pairs:
            fixed = fixed.replace(old, new, 1)
        if fixed != data:
            smali.write_text(fixed, encoding='utf-8')

    smali = next(Path(tmp_dir).glob('smali*/com/oplus/ocs/camera/producer/mode/BaseMode.smali'), None)
    if smali is None:
        return

    data = smali.read_text(encoding='utf-8')
    fixed = _replace_smali_method(
        data,
        'public isSensorModeNeedWait(II)Z',
        '    .locals 1\n'
        '\n'
        '    const/4 v0, 0x0\n'
        '\n'
        '    return v0\n',
    )
    sat_identity_pattern = re.compile(
        r'(    invoke-static \{\}, Lcom/oplus/ocs/camera/common/util/Util;->isSystemCamera\(\)Z\n'
        r'\n'
        r'    move-result p2\n'
        r'\n)'
        r'    if-nez p2, (:cond_[0-9a-f]+)\n'
        r'\n'
        r'(    invoke-virtual \{p0, p3\}, Lcom/oplus/ocs/camera/producer/mode/BaseMode;->useOplusCameraCase\(Ljava/lang/String;\)Z\n'
        r'\n'
        r'    move-result p2\n'
        r'\n'
        r'    if-eqz p2, \2\n'
        r'\n'
        r'(?:    \.line \d+\n)?'
        r'    sget-object p2, Lcom/oplus/ocs/camera/metadata/UConfigureKeys;->IS_OPLUS_PACKAGE:Lcom/oplus/ocs/camera/metadata/RequestKey;\n)'
    )
    fixed, sat_count = sat_identity_pattern.subn(r'\1    nop\n\n\3', fixed, count=1)
    if sat_count != 1 and 'UConfigureKeys;->IS_OPLUS_PACKAGE' in fixed and 'useOplusCameraCase(Ljava/lang/String;)Z' in fixed:
        raise ValueError('com.oplus.camera.unit.sdk.jar BaseMode SAT identity guard pattern not found exactly once')
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_camera_unit_facebeauty_probe_path(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # Re-point the guarded ProductJni probe from /product/lib64 to /system_ext/lib64.
    if tmp_dir is None:
        return

    old = '/product/lib64/libApsFaceBeautyPreviewProductJni.so'
    new = '/system_ext/lib64/libApsFaceBeautyPreviewProductJni.so'
    for smali in Path(tmp_dir).glob('smali*/**/*.smali'):
        data = smali.read_text(encoding='utf-8', errors='ignore')
        if old not in data:
            continue
        smali.write_text(data.replace(old, new), encoding='utf-8')
        return


def blob_fixup_apsclient_force_java_heif(ctx, file, file_path, *args, **kwargs):
    # OPlus supports two HEIF handoffs: optional native helpers when dlopen can
    # resolve them, otherwise its Java-reflection fallback. Stock keeps this APS
    # client in /product and the helpers in /system_ext, so product namespace
    # isolation selects reflection. Our system_ext remap co-located them and
    # unintentionally enabled the native route that stock CPH2747 does not use.
    path = Path(file_path)
    blob = path.read_bytes()
    actual_sha256 = sha256(blob).hexdigest()
    if actual_sha256 != APSCLIENT_STOCK_SHA256:
        raise ValueError(
            'APS client SHA-256 mismatch: '
            f'expected {APSCLIENT_STOCK_SHA256}, found {actual_sha256}'
        )

    patched = bytearray(blob)
    for offset, expected, replacement in APSCLIENT_HEIF_DLOPEN_TARGETS:
        end = offset + len(expected)
        if blob[offset:end] != expected:
            raise ValueError(
                f'APS client dlopen target mismatch at {offset:#x}: '
                f'expected {expected!r}, found {blob[offset:end]!r}'
            )
        patched[offset:end] = replacement

    result = bytes(patched)
    patched_sha256 = sha256(result).hexdigest()
    if patched_sha256 != APSCLIENT_PATCHED_SHA256:
        raise ValueError(
            'patched APS client SHA-256 mismatch: '
            f'expected {APSCLIENT_PATCHED_SHA256}, found {patched_sha256}'
        )
    path.write_bytes(result)


lib_fixups: lib_fixups_user_type = {
    # **lib_fixups already includes the clang RT ubsan and proto 3.9.1
    # fixups that were previously handled by the bash helper functions
    # lib_to_package_fixup_clang_rt_ubsan_standalone and
    # lib_to_package_fixup_proto_3_9_1 — no need to add them explicitly.
    **lib_fixups,
    (
        'libSuperTextWrapper',
        'libXDocProcessSDK',
        'libYTCommon',
        'libmpbase',
        'libextendfile',
    ): lib_fixup_system_ext_suffix,
}

def blob_fixup_filemanager_cut_skip_k0_when_same_disk(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return
    smali = Path(tmp_dir) / 'smali' / 'com' / 'filemanager' / 'fileoperate' / 'cut' / 'FileActionCut.smali'
    data = smali.read_text(encoding='utf-8')
    # K0() checks whether a cross-device move dialog is needed, but on LineageOS
    # it crashes silently (swallowed by the thread pool) before logging anything.
    # V:Z is already set true in V() when source and dest are on the same volume,
    # so skipping K0() for same-disk moves is correct — no cross-device dialog needed.
    if 'iget-boolean v2, p0, Lcom/filemanager/fileoperate/cut/FileActionCut;->V:Z' in data:
        return
    pattern = (
        r'(?m)^(?P<label>    :cond_\w+\n)'
        r'(?P<call>    invoke-virtual \{p0\}, Lcom/filemanager/fileoperate/cut/FileActionCut;->K0\(\)Z\n'
        r'\n'
        r'    move-result v2\n'
        r'\n'
        r'    if-eqz v2, :(?P<after>cond_\w+)\n)'
    )

    def skip_same_disk(match: re.Match) -> str:
        return (
            match.group('label')
            + '    iget-boolean v2, p0, Lcom/filemanager/fileoperate/cut/FileActionCut;->V:Z\n'
            + f'    if-nez v2, :{match.group("after")}\n'
            + match.group('call')
        )

    data, count = re.subn(pattern, skip_same_disk, data, count=1)
    if count != 1:
        raise ValueError('FileManager FileActionCut K0() block not found exactly once')
    smali.write_text(data, encoding='utf-8')


def blob_fixup_filemanager_select_dir_current_path_fallback(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return
    smali = Path(tmp_dir) / 'smali_classes3' / 'com' / 'oplus' / 'selectdir' / 'SelectDirPathPanelFragment.smali'
    data = smali.read_text(encoding='utf-8')
    log_anchor = '    const-string v4, "selectButton click -> select path:"\n'
    button_anchor = '    iget-object p1, p0, Lcom/oplus/selectdir/SelectDirPathPanelFragment;->mSelectButton:Lcom/coui/appcompat/button/COUIButton;\n'
    # B0().getValue() returns null because G0() never populates it in this flow.
    # mPathBar.getCurrentPath() is updated on every navigation and is reliable.
    new = (
        '    iget-object v0, p0, Lcom/oplus/selectdir/SelectDirPathPanelFragment;->mPathBar:Lcom/filemanager/common/view/BrowserPathBar;\n'
        '    if-eqz v0, :cond_pathbar_skip\n'
        '    invoke-virtual {v0}, Lcom/filemanager/common/view/BrowserPathBar;->getCurrentPath()Ljava/lang/String;\n'
        '    move-result-object v0\n'
        '    if-eqz v0, :cond_pathbar_skip\n'
        '    iget-object p1, v1, Lkotlin/jvm/internal/Ref$ObjectRef;->element:Ljava/lang/Object;\n'
        '    check-cast p1, Ljava/util/List;\n'
        '    if-eqz p1, :cond_pathbar_set\n'
        '    invoke-interface {p1}, Ljava/util/List;->isEmpty()Z\n'
        '    move-result p1\n'
        '    if-eqz p1, :cond_pathbar_skip\n'
        '    :cond_pathbar_set\n'
        '    invoke-static {v0}, Lkotlin/collections/p;->e(Ljava/lang/Object;)Ljava/util/List;\n'
        '    move-result-object v0\n'
        '    iput-object v0, v1, Lkotlin/jvm/internal/Ref$ObjectRef;->element:Ljava/lang/Object;\n'
        '    :cond_pathbar_skip\n'
    )
    log_idx = data.find(log_anchor)
    button_idx = data.find(button_anchor, log_idx)
    if log_idx == -1 or button_idx == -1:
        return

    select_path_block = data[log_idx:button_idx]
    if ':cond_pathbar_skip' not in select_path_block:
        data = data[:button_idx] + new + data[button_idx:]
    smali.write_text(data, encoding='utf-8')


def blob_fixup_filemanager_copycut_skip_osense_scene(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return
    smali = Path(tmp_dir) / 'smali' / 'com' / 'filemanager' / 'fileoperate' / 'copy' / 'FileActionBaseCopyCut.smali'
    data = smali.read_text(encoding='utf-8')
    signature = 'public final c0()V'
    body = (
        '    .locals 0\n'
        '\n'
        '    return-void\n'
    )
    fixed = _replace_smali_method(data, signature, body)
    if fixed == data:
        raise ValueError('FileManager FileActionBaseCopyCut.c0() method not found')
    smali.write_text(fixed, encoding='utf-8')


def blob_fixup_filemanager_superapp_zip_preview(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return
    smali = Path(tmp_dir) / 'smali' / 'com' / 'filemanager' / 'superapp' / 'ui' / 'superapp' / 'SuperListFragment$n.smali'
    data = smali.read_text(encoding='utf-8')
    if 'SuperApp archive preview direct' in data:
        return
    anchor = (
        '    :cond_2\n'
        '    invoke-static {p1}, Lkotlin/a;->b(Ljava/lang/Object;)V\n'
        '\n'
    )
    insert = (
        anchor +
        '    iget-object p1, p0, Lcom/filemanager/superapp/ui/superapp/SuperListFragment$n;->i:Lcom/filemanager/common/base/c;\n'
        '\n'
        '    invoke-virtual {p1}, Lcom/filemanager/common/base/c;->t()I\n'
        '\n'
        '    move-result p1\n'
        '\n'
        '    const/16 v1, 0x80\n'
        '\n'
        '    if-ne p1, v1, :cond_superapp_archive_skip\n'
        '\n'
        '    const-string p1, "SuperListFragment"\n'
        '\n'
        '    const-string v1, "SuperApp archive preview direct"\n'
        '\n'
        '    invoke-static {p1, v1}, Lcom/filemanager/common/utils/g2;->b(Ljava/lang/String;Ljava/lang/String;)V\n'
        '\n'
        '    sget-object p1, Le8/a;->a:Le8/a;\n'
        '\n'
        '    iget-object v1, p0, Lcom/filemanager/superapp/ui/superapp/SuperListFragment$n;->l:Landroidx/fragment/app/FragmentActivity;\n'
        '\n'
        '    iget-object v2, p0, Lcom/filemanager/superapp/ui/superapp/SuperListFragment$n;->i:Lcom/filemanager/common/base/c;\n'
        '\n'
        '    const/high16 v3, 0x18000000\n'
        '\n'
        '    invoke-virtual {p1, v1, v2, v3}, Le8/a;->h(Landroid/app/Activity;Lcom/filemanager/common/base/c;I)V\n'
        '\n'
        '    sget-object p0, Lht/m;->a:Lht/m;\n'
        '\n'
        '    return-object p0\n'
        '\n'
        '    :cond_superapp_archive_skip\n'
        '\n'
    )
    if anchor not in data:
        raise ValueError('FileManager SuperListFragment archive click anchor not found')
    data = data.replace(anchor, insert, 1)
    smali.write_text(data, encoding='utf-8')


def blob_fixup_filemanager_skip_osense_scene_actions(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return
    smali = Path(tmp_dir) / 'smali' / 'u6' / 'b.smali'
    data = smali.read_text(encoding='utf-8')
    signature = 'public static final f(Ljava/lang/String;I)V'
    body = (
        '    .locals 2\n'
        '\n'
        '    const-string p1, "action"\n'
        '\n'
        '    invoke-static {p0, p1}, Lkotlin/jvm/internal/j;->g(Ljava/lang/Object;Ljava/lang/String;)V\n'
        '\n'
        '    const-string p0, "PerformanceManager"\n'
        '\n'
        '    const-string p1, "setSceneAction return, patched"\n'
        '\n'
        '    invoke-static {p0, p1}, Lcom/filemanager/common/utils/g2;->b(Ljava/lang/String;Ljava/lang/String;)V\n'
        '\n'
        '    return-void\n'
    )
    fixed = _replace_smali_method(data, signature, body)
    if fixed == data:
        raise ValueError('FileManager PerformanceManager.f() method not found')
    smali.write_text(fixed, encoding='utf-8')


def blob_fixup_filemanager_safecheck_direct(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return
    smali = Path(tmp_dir) / 'smali' / 'com' / 'filemanager' / 'common' / 'fileutils' / 'e.smali'
    data = smali.read_text(encoding='utf-8')
    signature = 'public final x(Lvt/a;Ljava/lang/Object;)Ljava/lang/Object;'
    body = (
        '    .locals 3\n'
        '\n'
        '    const-string p0, "method"\n'
        '\n'
        '    invoke-static {p1, p0}, Lkotlin/jvm/internal/j;->g(Ljava/lang/Object;Ljava/lang/String;)V\n'
        '\n'
        '    const-string p0, "safeCheck direct"\n'
        '\n'
        '    const-string v0, "JavaFileHelper"\n'
        '\n'
        '    invoke-static {v0, p0}, Lcom/filemanager/common/utils/g2;->b(Ljava/lang/String;Ljava/lang/String;)V\n'
        '\n'
        '    :try_start_0\n'
        '    invoke-interface {p1}, Lvt/a;->invoke()Ljava/lang/Object;\n'
        '\n'
        '    move-result-object p0\n'
        '    :try_end_0\n'
        '    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0\n'
        '\n'
        '    return-object p0\n'
        '\n'
        '    :catch_0\n'
        '    move-exception p0\n'
        '\n'
        '    invoke-virtual {p0}, Ljava/lang/Throwable;->getMessage()Ljava/lang/String;\n'
        '\n'
        '    move-result-object p0\n'
        '\n'
        '    new-instance p1, Ljava/lang/StringBuilder;\n'
        '\n'
        '    invoke-direct {p1}, Ljava/lang/StringBuilder;-><init>()V\n'
        '\n'
        '    const-string v1, "safeCheck failed: default="\n'
        '\n'
        '    invoke-virtual {p1, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
        '\n'
        '    invoke-virtual {p1, p2}, Ljava/lang/StringBuilder;->append(Ljava/lang/Object;)Ljava/lang/StringBuilder;\n'
        '\n'
        '    const-string v1, ", "\n'
        '\n'
        '    invoke-virtual {p1, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
        '\n'
        '    invoke-virtual {p1, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;\n'
        '\n'
        '    invoke-virtual {p1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;\n'
        '\n'
        '    move-result-object p0\n'
        '\n'
        '    invoke-static {v0, p0}, Lcom/filemanager/common/utils/g2;->b(Ljava/lang/String;Ljava/lang/String;)V\n'
        '\n'
        '    return-object p2\n'
    )
    fixed = _replace_smali_method(data, signature, body)
    if fixed == data:
        raise ValueError('FileManager JavaFileHelper.safeCheck method not found')
    smali.write_text(fixed, encoding='utf-8')


blob_fixups: blob_fixups_user_type = {
    'system_ext/lib64/libAPSClient-cmd-jni.so': blob_fixup()
        .call(blob_fixup_apsclient_force_java_heif),
    'system_ext/framework/com.oplus.camera.unit.sdk.jar': blob_fixup()
        .apktool_unpack('patches-sdk')
        .patch_dir('patches-sdk')
        .call(blob_fixup_camera_unit_facebeauty_probe_path)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/OplusCamera/OplusCamera.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_opluscamera_font)
        .call(blob_fixup_opluscamera_blur_seginit_guard)
        .call(blob_fixup_strip_oem_permissions)
        .apktool_pack()
        .stripzip(),
    'system_ext/app/SystemUIPlugin/SystemUIPlugin.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_oplus_camera_system_properties)
        .call(blob_fixup_systemuiplugin_plugin_context_inflater)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/OppoGallery2/OppoGallery2.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_opluscamera_uses_library)
        .call(blob_fixup_oppogallery_op15_native_libs)
        .call(blob_fixup_oppogallery_receiver_flags)
        .call(blob_fixup_oppogallery_wallpaper_attach_intent)
        .call(blob_fixup_oppogallery_safe_box_custom_flag)
        .call(blob_fixup_oppogallery_google_photos_consent_on_verify_failure)
        .call(blob_fixup_oppogallery_google_photos_launch_consent_after_verify_failure)
        .call(blob_fixup_oppogallery_hide_google_photos_backup_settings)
        .call(blob_fixup_oppogallery_system_share_helper)
        .call(blob_fixup_strip_oem_permissions)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/StdID/StdID.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_stdid_receiver_flags)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/PhoneManager/PhoneManager.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_opluscamera_uses_library)
        .call(blob_fixup_phonemanager_secure_settings_permission)
        .call(blob_fixup_phonemanager_settings_category)
        .call(blob_fixup_phonemanager_permission_controller_package)
        .apktool_pack()
        .stripzip(),
    'system_ext/app/SafeCenter/SafeCenter.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_opluscamera_uses_library)
        .call(blob_fixup_safecenter_receiver_flags)
        .call(blob_fixup_safecenter_olock_support)
        .call(blob_fixup_safecenter_olock_theft_dark_theme)
        .apktool_pack()
        .stripzip(),
    'product/app/AONService/AONService.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_manifest)
        .call(blob_fixup_aonservice_settings_category)
        .apktool_pack()
        .stripzip(),
    'product/priv-app/AIUnit/AIUnit.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_manifest)
        .call(blob_fixup_aiunit_settings_category)
        .apktool_pack()
        .stripzip(),
    'system_ext/etc/permissions/vendor-oplus-hardware-cryptoeng.xml': blob_fixup()
        .call(blob_fixup_cryptoeng_permissions_xml),
    'odm/etc/permissions/vendor-oplus-hardware-cryptoeng.xml': blob_fixup()
        .call(blob_fixup_cryptoeng_permissions_xml),
    'odm/etc/init/vendor.oplus.hardware.cryptoeng@1.0-service_FDE.rc': blob_fixup()
        .call(blob_fixup_cryptoeng_init_rc),
    'odm/etc/vintf/manifest/manifest_oplus_cryptoeng.xml': blob_fixup()
        .call(blob_fixup_cryptoeng_manifest),
    'system_ext/app/FileManager/FileManager.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_opluscamera_uses_library)
        .call(blob_fixup_filemanager_safecheck_direct)
        .call(blob_fixup_filemanager_select_dir_current_path_fallback)
        .call(blob_fixup_filemanager_cut_skip_k0_when_same_disk)
        .call(blob_fixup_filemanager_copycut_skip_osense_scene)
        .call(blob_fixup_filemanager_superapp_zip_preview)
        .call(blob_fixup_filemanager_skip_osense_scene_actions)
        .apktool_pack()
        .stripzip(),
    'system_ext/app/Melody/Melody.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_opluscamera_uses_library)
        .call(blob_fixup_oplus_camera_system_properties)
        .call(blob_fixup_strip_oem_permissions)
        .call(blob_fixup_melody_repackaging_detector)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/UMS/UMS.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_opluscamera_uses_library)
        .call(blob_fixup_ums_activity_watcher_permission)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/OplusExSystemService/OplusExSystemService.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_opluscamera_uses_library)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/DCS/DCS.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_opluscamera_uses_library)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/FileEncryption/FileEncryption.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_opluscamera_uses_library)
        .call(blob_fixup_fileencryption_secure_settings_permission)
        .call(blob_fixup_fileencryption_biometric_enrollment_checks)
        .call(blob_fixup_oplus_camera_system_properties)
        .apktool_pack()
        .stripzip(),
    'system_ext/app/SecurityPermission/SecurityPermission.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_securitypermission_safe_permissions)
        .apktool_pack()
        .stripzip(),
}  # fmt: skip

namespace_imports = [
    'vendor/oppo/lighthouse',
    'vendor/oneplus/sm8850-common',
    'hardware/oplus',
]

module = ExtractUtilsModule(
    'lighthouse-camera',
    'oppo',
    device_rel_path='device/oppo/lighthouse-camera',
    blob_fixups=blob_fixups,
    lib_fixups=lib_fixups,
    namespace_imports=namespace_imports,
)

if __name__ == '__main__':
    utils = ExtractUtils.device(module)
    utils.run()
    
from pathlib import Path
import os
import re


CUSTOM_SOONG_BEGIN = "// BEGIN LIGHTHOUSE-CAMERA CUSTOM SOONG MODULES"
CUSTOM_SOONG_END = "// END LIGHTHOUSE-CAMERA CUSTOM SOONG MODULES"


def write_custom_android_bp():
    top = Path(os.environ.get(
        "ANDROID_BUILD_TOP",
        Path(__file__).resolve().parents[3],
    ))

    android_bp = top / "vendor" / "oppo" / "lighthouse-camera" / "Android.bp"
    if not android_bp.exists():
        return

    custom_block = f"""
{CUSTOM_SOONG_BEGIN}

dex_import {{
    name: "oplus-services",
    jars: ["proprietary/system/framework/oplus-services.jar"],
    system_ext_specific: false,
}}

prebuilt_overlay {{
    name: "aon.frameworkres.overlay.product",
    src: ":aon_frameworkres_overlay_apk",
    filename: "aon.frameworkres.overlay.product.apk",
    product_specific: true,
}}

{CUSTOM_SOONG_END}
"""

    old_text = android_bp.read_text()
    new_text = re.sub(
        rf"\n?{re.escape(CUSTOM_SOONG_BEGIN)}.*?{re.escape(CUSTOM_SOONG_END)}\n?",
        "",
        old_text,
        flags=re.S,
    ).rstrip() + "\n" + custom_block

    if new_text != old_text:
        android_bp.write_text(new_text)


write_custom_android_bp()
