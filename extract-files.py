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
import re
import shutil
import zipfile
from private_safe import blob_fixup_private_safe_unlock_dialog


APSCLIENT_STOCK_SHA256 = '0b5b49ae8845983f178279fe252c4aef8476d99b1f9470a7ead98e9095c3df39'
APSCLIENT_PATCHED_SHA256 = 'db43c7391dc2d5bc26d1c09b47b008488a2393cea1c0df909737a72e688c6419'
APSCLIENT_HEIF_DLOPEN_TARGETS = (
    (0x4F418, b'libHeifEncoderWrapper.so', b'xibHeifEncoderWrapper.so'),
    (0x4BE60, b'libNativeWinBuffExchange.so', b'xibNativeWinBuffExchange.so'),
)

_OPLUSCAMERA_DEX_STATE = {}


def _smali_dir_to_dex_name(smali_dir):
    if smali_dir.name == 'smali':
        return 'classes.dex'

    match = re.fullmatch(r'smali_classes(\d+)', smali_dir.name)
    if match is None:
        return None

    return f'classes{match.group(1)}.dex'


def _hash_smali_dir(smali_dir):
    digest = sha256()
    for smali in sorted(smali_dir.rglob('*.smali')):
        digest.update(str(smali.relative_to(smali_dir)).encode())
        digest.update(b'\0')
        digest.update(smali.read_bytes())
        digest.update(b'\0')
    return digest.digest()


def _get_smali_digests(tmp_dir):
    digests = {}
    for smali_dir in Path(tmp_dir).iterdir():
        dex_name = _smali_dir_to_dex_name(smali_dir)
        if dex_name is None or not smali_dir.is_dir():
            continue
        digests[dex_name] = _hash_smali_dir(smali_dir)
    return digests


def blob_fixup_opluscamera_capture_dex(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    """Keep stock dex payloads so apktool only replaces dex files we patch."""
    if tmp_dir is None:
        return

    with zipfile.ZipFile(file_path, 'r') as apk:
        original_dex = {
            info.filename: (info, apk.read(info))
            for info in apk.infolist()
            if re.fullmatch(r'classes(?:\d+)?\.dex', info.filename)
        }

    _OPLUSCAMERA_DEX_STATE[file_path] = {
        'digests': _get_smali_digests(tmp_dir),
        'dex': original_dex,
    }


def blob_fixup_opluscamera_restore_untouched_dex(
    ctx,
    file,
    file_path,
    *args,
    tmp_dir=None,
    **kwargs,
):
    """Restore original dex files whose decoded smali was not modified."""
    if tmp_dir is None:
        return

    state = _OPLUSCAMERA_DEX_STATE.pop(file_path)
    current_digests = _get_smali_digests(tmp_dir)
    original_digests = state['digests']
    original_dex = state['dex']

    restore_names = {
        dex_name
        for dex_name in original_dex
        if current_digests.get(dex_name) == original_digests.get(dex_name)
    }
    if not restore_names:
        return

    apk_path = Path(file_path)
    rebuilt_path = apk_path.with_name(f'{apk_path.name}.dex-restored')
    try:
        with zipfile.ZipFile(apk_path, 'r') as rebuilt_apk:
            rebuilt_infos = {
                info.filename: info for info in rebuilt_apk.infolist()
            }
            with zipfile.ZipFile(rebuilt_path, 'w') as restored_apk:
                restored_apk.comment = rebuilt_apk.comment
                for info in rebuilt_apk.infolist():
                    if info.filename in restore_names:
                        continue
                    restored_apk.writestr(info, rebuilt_apk.read(info))

                for dex_name in sorted(restore_names):
                    original_info, dex_data = original_dex[dex_name]
                    info = rebuilt_infos.get(dex_name, original_info)
                    restored_apk.writestr(info, dex_data)

        shutil.copystat(apk_path, rebuilt_path)
        rebuilt_path.replace(apk_path)
    finally:
        rebuilt_path.unlink(missing_ok=True)


def blob_fixup_opluscamera_rear_rgb_sensor(
    ctx, file, file_path, *args, tmp_dir=None, **kwargs,
):
    """Keep the stock rear RGB sensor active during a Camera session.

    ColorOS normally registers this sensor from its display service. The
    AOSP display service does not call that Oplus extension, leaving the
    camera's color-sensor channel without samples on this device.
    """
    if tmp_dir is None:
        return

    camera_smali = _find_smali(
        tmp_dir, 'com/oplus/camera/Camera.smali', 'OplusCamera activity',
    )
    data = camera_smali.read_text(encoding='utf-8')
    start = (
        '    invoke-static {p0}, '
        'Lcom/oplus/camera/port/RearRgbSensorKeepalive;->start(Landroid/content/Context;)V\n'
    )
    stop = (
        '    invoke-static {}, '
        'Lcom/oplus/camera/port/RearRgbSensorKeepalive;->stop()V\n'
    )
    anchors = (
        (
            '.method public b0(Landroid/os/Bundle;)V\n    .locals 7\n',
            '.method public b0(Landroid/os/Bundle;)V\n    .locals 7\n\n' + start,
        ),
        (
            '    :cond_0\n'
            '    invoke-static {p0}, Lqa/n3;->a(Landroid/content/Context;)Landroid/app/KeyguardManager;\n',
            '    :cond_0\n' + start +
            '    invoke-static {p0}, Lqa/n3;->a(Landroid/content/Context;)Landroid/app/KeyguardManager;\n',
        ),
        (
            '    invoke-virtual {v0}, Lcom/oplus/camera/CameraManager;->g2()V\n',
            '    invoke-virtual {v0}, Lcom/oplus/camera/CameraManager;->g2()V\n\n' + stop,
        ),
    )
    for original, replacement in anchors:
        if data.count(original) != 1:
            raise ValueError(f'OplusCamera rear RGB lifecycle anchor missing: {original!r}')
        data = data.replace(original, replacement, 1)
    camera_smali.write_text(data, encoding='utf-8')

    helper = camera_smali.parent / 'port' / 'RearRgbSensorKeepalive.smali'
    if helper.exists():
        raise ValueError('OplusCamera rear RGB helper already exists')
    helper.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        Path(__file__).parent / 'patches-camera' / 'RearRgbSensorKeepalive.smali',
        helper,
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
        'liboplus-uah-client',
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


def _find_smali(tmp_dir: str, relative_path: str, description: str) -> Path:
    smali = next(Path(tmp_dir).glob(f'smali*/{relative_path}'), None)
    if smali is None:
        raise ValueError(f'{description} smali not found')
    return smali


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


def blob_fixup_gestureui_search_settings_namespace(
    ctx,
    file,
    file_path,
    *args,
    tmp_dir=None,
    **kwargs,
):
    # GestureSearchIndexablesProvider stores its private non-indexable-key
    # cache through Settings.System. AOSP rejects app-defined System settings,
    # and the resulting provider exception crashes SettingsIntelligence while
    # it builds the search index. Keep the same key and move all accesses to
    # Settings.Secure, where the provider already stores its related cache.
    if tmp_dir is None:
        return

    smali = next(
        (
            path
            for path in Path(tmp_dir).glob('smali*/**/*.smali')
            if '"GestureSettingsProviderUtils"'
            in path.read_text(encoding='utf-8', errors='ignore')
            and '"com.oplus.gesture_nonIndexKey"'
            in path.read_text(encoding='utf-8', errors='ignore')
        ),
        None,
    )
    if smali is None:
        raise ValueError('OplusGestureUI GestureSettingsProviderUtils smali not found')
    data = smali.read_text(encoding='utf-8')
    key = 'com.oplus.gesture_nonIndexKey'
    # Method c() reuses the register holding the key for its final write, so
    # the literal occurs twice even though there are three settings accesses.
    if data.count(key) != 2:
        raise ValueError('OplusGestureUI non-indexable cache key count changed')

    put_system = (
        'Landroid/provider/Settings$System;->putString('
        'Landroid/content/ContentResolver;Ljava/lang/String;Ljava/lang/String;)Z'
    )
    put_secure = put_system.replace('Settings$System', 'Settings$Secure')
    get_system = (
        'Landroid/provider/Settings$System;->getString('
        'Landroid/content/ContentResolver;Ljava/lang/String;)Ljava/lang/String;'
    )
    get_secure = get_system.replace('Settings$System', 'Settings$Secure')

    if data.count(put_system) != 2 or data.count(get_system) != 1:
        raise ValueError('OplusGestureUI Settings.System access pattern changed')

    fixed = data.replace(put_system, put_secure).replace(get_system, get_secure)
    smali.write_text(fixed, encoding='utf-8')


def blob_fixup_gestureui_settings_search(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # Google Settings Intelligence requires the root tag of every XML exposed
    # by a SearchIndexablesProvider to be the unqualified PreferenceScreen.
    # AndroidX's inflater still resolves that tag to androidx.preference.
    if tmp_dir is None:
        return

    xml_dir = Path(tmp_dir) / 'res/xml'
    old_open = '<androidx.preference.PreferenceScreen'
    old_close = '</androidx.preference.PreferenceScreen>'
    new_open = '<PreferenceScreen'
    new_close = '</PreferenceScreen>'
    old_roots = []
    new_roots = []

    for preference_xml in sorted(xml_dir.glob('*.xml')):
        data = preference_xml.read_text(encoding='utf-8')
        if old_open in data:
            if data.count(old_open) != 1 or data.count(old_close) != 1:
                raise ValueError(
                    f'OplusGestureUI PreferenceScreen structure changed: {preference_xml.name}'
                )
            preference_xml.write_text(
                data.replace(old_open, new_open, 1).replace(old_close, new_close, 1),
                encoding='utf-8',
            )
            old_roots.append(preference_xml.name)
        elif new_open in data:
            new_roots.append(preference_xml.name)

    if len(old_roots) + len(new_roots) != 19:
        raise ValueError(
            'OplusGestureUI indexed PreferenceScreen XML count changed: '
            f'{len(old_roots) + len(new_roots)}'
        )


def blob_fixup_gestureui_light_press_default(
    ctx,
    file,
    file_path,
    *args,
    tmp_dir=None,
    **kwargs,
):
    # ColorOS provisions the camera-button light-press setting outside the
    # read-only product image. Recreate that fresh-user state without
    # overwriting an explicit user choice stored in Settings.Secure.
    if tmp_dir is None:
        return

    smali = next(
        (
            path
            for path in Path(tmp_dir).glob('smali*/**/*.smali')
            if '"SpruceKeyUtils"' in path.read_text(encoding='utf-8', errors='ignore')
            and '"oplus_camera_light_press_spruce"'
            in path.read_text(encoding='utf-8', errors='ignore')
            and '"resetNotificationManagerSettings"'
            in path.read_text(encoding='utf-8', errors='ignore')
            and '"doubleTapSettingsState is null"'
            in path.read_text(encoding='utf-8', errors='ignore')
        ),
        None,
    )
    if smali is None:
        raise ValueError('OplusGestureUI SpruceKeyUtils smali not found')
    data = smali.read_text(encoding='utf-8')

    def enable_light_press_in_method(data: str, marker: str, description: str) -> str:
        marker_idx = data.find(marker)
        method_start = data.rfind('.method ', 0, marker_idx)
        method_end = data.find('.end method', marker_idx)
        if marker_idx < 0 or method_start < 0 or method_end < 0:
            raise ValueError(f'OplusGestureUI {description} method not found')
        method_end += len('.end method')
        method = data[method_start:method_end]

        enabled_registers = re.findall(r'const/4 ([vp]\d+), 0x1', method)
        if len(enabled_registers) != 1:
            raise ValueError(
                f'OplusGestureUI {description} enabled-value register changed'
            )
        enabled_register = enabled_registers[0]
        setting_pattern = (
            r'(const-string (?P<key_register>[vp]\d+), '
            r'"oplus_camera_light_press_spruce".*?'
            r'invoke-static \{(?P<context>[vp]\d+), (?P=key_register), )'
            r'(?P<value>[vp]\d+)'
            r'(, (?P<user>[vp]\d+)\}, '
            r'Lcom/oplus/gesture/util/GestureUtil;->setSecureIntForUser\('
            r'Landroid/content/Context;Ljava/lang/String;II\)V)'
        )
        method, count = re.subn(
            setting_pattern,
            rf'\g<1>{enabled_register}\g<5>',
            method,
            count=1,
            flags=re.DOTALL,
        )
        if count != 1:
            raise ValueError(
                f'OplusGestureUI {description} light-press default not patched'
            )
        return data[:method_start] + method + data[method_end:]

    data = enable_light_press_in_method(
        data,
        '"doubleTapSettingsState is null"',
        'fresh-user defaults',
    )
    data = enable_light_press_in_method(
        data,
        '"resetNotificationManagerSettings"',
        'reset defaults',
    )
    smali.write_text(data, encoding='utf-8')


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

    process_smali = next(
        (
            path
            for path in Path(tmp_dir).glob('smali*/**/*.smali')
            if '"OplusBlurProcess"' in path.read_text(encoding='utf-8', errors='ignore')
            and '->segInit(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;II)[I' in path.read_text(encoding='utf-8', errors='ignore')
            and 'monitor-enter' in path.read_text(encoding='utf-8', errors='ignore')
        ),
        None,
    )
    if process_smali is None:
        raise ValueError('OplusCamera blur process smali not found')

    data = process_smali.read_text(encoding='utf-8', errors='ignore')
    if not re.search(r'/(?:odm/)?etc/camera/singleblur/personseg\.bin', data):
        raise ValueError('OplusCamera blur process segInit anchor not found')

    monitor_match = re.search(r'    monitor-enter (?P<register>[vp]\d+)\n', data)
    if monitor_match is None:
        raise ValueError('OplusCamera blur process monitor anchor not found')
    monitor_register = monitor_match.group('register')
    fixed, count = re.subn(
        r'(?s)(invoke-virtual/range \{[vp]\d+ \.\. [vp]\d+\}, Lcom/oplus/ocs/camera/OplusBlurPreviewHelper;->segInit\(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;II\)\[I.*?'
        r'move-result-object (?P<result>[vp]\d+).*?'
        r'sput-object (?P=result), L[^;]+;->[A-Za-z0-9_$]+:\[I)',
        r'\1'
        '\n\n'
        r'    if-nez \g<result>, :cond_lighthouse_blur_seginit_ok\n'
        '\n'
        '    const/4 v0, 0x0\n'
        '\n'
        f'    monitor-exit {monitor_register}\n'
        '\n'
        '    return v0\n'
        '\n'
        '    :cond_lighthouse_blur_seginit_ok',
        data,
        count=1,
    )
    if count != 1:
        raise ValueError('OplusCamera blur process segInit write not patched')
    process_smali.write_text(fixed, encoding='utf-8')

    texture_smali = next(
        (
            path
            for path in Path(tmp_dir).glob('smali*/**/*.smali')
            if '"initSegForSizeChange, segInit, cost: "' in path.read_text(encoding='utf-8', errors='ignore')
            and '->segInit(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;II)[I' in path.read_text(encoding='utf-8', errors='ignore')
        ),
        None,
    )
    if texture_smali is None:
        raise ValueError('OplusCamera blur texture smali not found')

    data = texture_smali.read_text(encoding='utf-8', errors='ignore')
    if 'initSegForSizeChange, segInit, cost: ' not in data:
        raise ValueError('OplusCamera blur size-change segInit anchor not found')

    fixed, count = re.subn(
        r'(?s)(invoke-virtual/range \{[vp]\d+ \.\. [vp]\d+\}, Lcom/oplus/ocs/camera/OplusBlurPreviewHelper;->segInit\(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;II\)\[I.*?'
        r'move-result-object (?P<result>[vp]\d+).*?'
        r'sput-object (?P=result), L[^;]+;->[A-Za-z0-9_$]+:\[I)',
        r'\1'
        '\n\n'
        r'    if-nez \g<result>, :cond_lighthouse_blur_size_seginit_ok\n'
        '\n'
        '    return-void\n'
        '\n'
        '    :cond_lighthouse_blur_size_seginit_ok',
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

    smali = next(
        (
            path
            for path in Path(tmp_dir).glob('smali*/**/*.smali')
            if '.source "BiometricsUnlockManager.kt"' in path.read_text(encoding='utf-8', errors='ignore')
        ),
        None,
    )
    if smali is None:
        raise ValueError('FileEncryption biometric helper not found')
    data = smali.read_text(encoding='utf-8')

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
    biometric_methods = re.findall(
        r'(?ms)^\.method public static final (?P<name>\w+)\(Landroid/content/Context;\)Z\n'
        r'(?P<body>.*?)^\.end method$',
        data,
    )
    face_methods = [
        name for name, body in biometric_methods
        if 'OplusFaceManager' in body and 'hasEnrolledTemplates' in body
    ]
    fingerprint_methods = [
        name for name, body in biometric_methods
        if 'const-string v1, "fingerprint"' in body
    ]
    if len(face_methods) != 1 or len(fingerprint_methods) != 1:
        raise ValueError(
            'Expected one face and one fingerprint enrollment method, found '
            f'{len(face_methods)} and {len(fingerprint_methods)}'
        )

    fixed = _replace_smali_method(
        data,
        f'public static final {face_methods[0]}(Landroid/content/Context;)Z',
        face_body,
    )
    fixed = _replace_smali_method(
        fixed,
        f'public static final {fingerprint_methods[0]}(Landroid/content/Context;)Z',
        fingerprint_body,
    )
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


def blob_fixup_aiunit_settings_search(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    # Google Settings Intelligence only accepts an unqualified PreferenceScreen
    # root while indexing XML returned by a SearchIndexablesProvider. AndroidX's
    # inflater still resolves the unqualified tag to androidx.preference.
    if tmp_dir is None:
        return

    preference_xml = Path(tmp_dir) / 'res/xml/fragment_ai_service_platform.xml'
    data = preference_xml.read_text(encoding='utf-8') if preference_xml.exists() else ''
    if not data:
        raise ValueError('AIUnit AI Service Engine preference XML not found')

    old_open = '<androidx.preference.PreferenceScreen'
    old_close = '</androidx.preference.PreferenceScreen>'
    new_open = '<PreferenceScreen'
    new_close = '</PreferenceScreen>'

    if old_open not in data or old_close not in data:
        if new_open in data and new_close in data:
            return
        raise ValueError('AIUnit AI Service Engine PreferenceScreen root not found')

    preference_xml.write_text(
        data.replace(old_open, new_open, 1).replace(old_close, new_close, 1),
        encoding='utf-8',
    )


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
    fixed = data.replace(
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
    fixed = fixed.replace(old, '')
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

    candidates = []
    for smali in Path(tmp_dir).glob('smali*/**/*.smali'):
        data = smali.read_text(encoding='utf-8')
        if (
            'public final J(Landroid/content/Context;)Z' in data
            and '[isSupportOLock] isSupport:false' in data
            and 'OLockManager' in data
        ):
            candidates.append((smali, data))

    if len(candidates) != 1:
        raise ValueError(
            f'Expected one SafeCenter OLock support method, found {len(candidates)}'
        )

    smali, data = candidates[0]
    fixed = _replace_smali_method(
        data,
        'public final J(Landroid/content/Context;)Z',
        '    .locals 1\n'
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

    # BroadcastDispatcher's proxy path carries the caller's flags in p2/v9.
    # Force RECEIVER_NOT_EXPORTED while preserving all unrelated flag bits.
    dispatcher = next(
        (
            path
            for path in Path(tmp_dir).glob('smali*/**/*.smali')
            if '.source "BroadcastDispatcher.kt"' in path.read_text(encoding='utf-8', errors='ignore')
            and 'Lcom/oplus/gallery/foundation/uikit/broadcast/bus/ProxyReceiver;' in path.read_text(encoding='utf-8', errors='ignore')
        ),
        None,
    )
    if dispatcher is None:
        raise ValueError('OppoGallery2 BroadcastDispatcher not found')
    data = dispatcher.read_text(encoding='utf-8')
    dispatcher_pattern = re.compile(
        r'(    move v9, p2\n)'
        r'(?P<middle>(?:\n|    \.line \d+\n)*)'
        r'(    invoke-virtual/range \{v4 \.\. v9\}, Landroid/content/Context;->registerReceiver\(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;I\)Landroid/content/Intent;\n)'
    )
    fixed, count = dispatcher_pattern.subn(
        r'\1'
        r'\n'
        r'    and-int/lit8 v9, v9, -0x3\n'
        r'\n'
        r'    or-int/lit8 v9, v9, 0x4\n'
        r'\g<middle>\3',
        data,
        count=1,
    )
    if count != 1 and 'or-int/lit8 v9, v9, 0x4' not in data:
        raise ValueError('OppoGallery2 BroadcastDispatcher receiver flag patch point not found')
    dispatcher.write_text(fixed, encoding='utf-8')

    # ActionReceiver is a second, independent registration path with flags in
    # its properties object. Apply the same exported-bit normalization there.
    receiver = _find_smali(
        tmp_dir,
        'com/oplus/gallery/foundation/uikit/broadcast/bus/ActionReceiver.smali',
        'OppoGallery2 ActionReceiver',
    )
    data = receiver.read_text(encoding='utf-8')
    pattern = re.compile(
        r'(    iget (?P<flags>v\d+), v0, L[^;]+;->c:I\n)'
        r'(?P<middle>(?:\n|    \.line \d+\n|    move-object v3, p0\n)*)'
        r'(    invoke-virtual/range \{v2 \.\. (?P=flags)\}, Landroid/content/Context;->registerReceiver\(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;Ljava/lang/String;Landroid/os/Handler;I\)Landroid/content/Intent;\n)'
    )
    fixed, count = pattern.subn(
        r'\1'
        r'\n'
        r'    and-int/lit8 \g<flags>, \g<flags>, -0x3\n'
        r'\n'
        r'    or-int/lit8 \g<flags>, \g<flags>, 0x4\n'
        r'\g<middle>\3',
        data,
        count=1,
    )
    if count != 1 and 'or-int/lit8 v7, v7, 0x4' not in data:
        raise ValueError('OppoGallery2 ActionReceiver receiver flag patch point not found')
    receiver.write_text(fixed, encoding='utf-8')


def blob_fixup_oppogallery_wallpaper_attach_intent(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = _find_smali(
        tmp_dir,
        'com/oplus/gallery/pictureeditorpage/PictureEditorDM.smali',
        'OppoGallery2 PictureEditorDM',
    )
    data = smali.read_text(encoding='utf-8')
    if 'getCropAndSetWallpaperIntent' not in data:
        raise ValueError('OppoGallery2 wallpaper crop-intent implementation not found')
    replacement = (
        '.method public final a(Landroid/app/Activity;Landroid/net/Uri;Z)V\n'
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
        '    const-string v1, "is_live_photo"\n'
        '\n'
        '    invoke-virtual {v0, v1, p3}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Z)Landroid/content/Intent;\n'
        '\n'
        '    invoke-virtual {p1, v0}, Landroid/app/Activity;->startActivity(Landroid/content/Intent;)V\n'
        '\n'
        '    return-void\n'
        '.end method\n'
    )
    fixed, count = re.subn(
        r'\.method public final a\(Landroid/app/Activity;Landroid/net/Uri;Z\)V\n.*?\.end method',
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
            for path in Path(tmp_dir).glob('smali*/com/oplus/aiunit/vision/*.smali')
            if '.source "ConfigAbilityWrapper.kt"' in path.read_text(encoding='utf-8', errors='ignore')
            and re.search(
                r'\.method public static final \w+\(Ljava/lang/String;ZZ\)Z',
                path.read_text(encoding='utf-8', errors='ignore'),
            )
        ),
        None,
    )
    if smali is None:
        raise ValueError('OppoGallery2 ConfigAbilityWrapper not found')
    data = smali.read_text(encoding='utf-8')
    method_match = re.search(
        r'\.method public static final (?P<name>\w+)\(Ljava/lang/String;ZZ\)Z\n'
        r'    \.locals 3\n',
        data,
    )
    if method_match is None:
        raise ValueError('OppoGallery2 SafeBox config method not found')
    pattern = re.compile(re.escape(method_match.group(0)))
    insert = (
        method_match.group(0) +
        '    const-string v0, "feature_is_support_user_custom_safe_box"\n'
        '\n'
        '    invoke-static {p0, v0}, Lkotlin/jvm/internal/Intrinsics;->areEqual(Ljava/lang/Object;Ljava/lang/Object;)Z\n'
        '\n'
        '    move-result v0\n'
        '\n'
        '    if-eqz v0, :oplus_safe_box_config_default\n'
        '\n'
        '    const/4 p0, 0x1\n'
        '\n'
        '    return p0\n'
        '\n'
        '    :oplus_safe_box_config_default\n'
    )
    fixed, count = pattern.subn(insert, data, count=1)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')
    elif ':oplus_safe_box_config_default' not in data:
        raise ValueError('OppoGallery2 SafeBox config patch point not found')


def blob_fixup_oppogallery_google_photos_consent_on_verify_failure(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    # GCloudPageHelper registers this listener before verifyAppState(). Stock
    # only opens the backup page when the callback boolean is true. On a port,
    # verification can return false before Google Photos has shown its consent
    # UI, so continue through the existing page helper for either result.
    smali = next(
        (
            path
            for path in Path(tmp_dir).glob('smali*/**/*.smali')
            if '.source "GCloudPageHelper.kt"' in path.read_text(encoding='utf-8', errors='ignore')
            and 'Lcom/oplus/gallery/framework/abilities/gcloudsync/utils/GCloudPageHelper;->e:' in path.read_text(encoding='utf-8', errors='ignore')
            and '.method public final a(Z)V' in path.read_text(encoding='utf-8', errors='ignore')
        ),
        None,
    )
    if smali is None:
        raise ValueError('OppoGallery2 GCloudPageHelper verification listener not found')
    data = smali.read_text(encoding='utf-8')
    method = re.search(
        r'(?ms)^\.method public final a\(Z\)V\n.*?^\.end method',
        data,
    )
    if (
        method is None
        or 'Lcom/oplus/gallery/framework/abilities/gcloudsync/utils/GCloudPageHelper;->e:'
        not in method.group(0)
    ):
        raise ValueError('OppoGallery2 GCloudPageHelper callback method not found')
    fixed_method, count = re.subn(
        r'    if-eqz p1, :(?P<label>cond_[0-9a-f]+)\n',
        '    nop\n',
        method.group(0),
        count=1,
    )
    if count != 1 and '    nop\n' not in method.group(0):
        raise ValueError('OppoGallery2 GCloudPageHelper verify-result branch not found')
    smali.write_text(data[:method.start()] + fixed_method + data[method.end():], encoding='utf-8')


def blob_fixup_oppogallery_hide_google_photos_backup_settings(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    # Remove the photo-page backup action from the current action-definition
    # map. The concrete h0u rule still exists, but without this map entry it is
    # never exposed by the overflow menu.
    menu_map = next(
        (
            path
            for path in Path(tmp_dir).glob('smali*/com/oplus/aiunit/vision/*.smali')
            if '"action_backup_to_cloud"' in path.read_text(encoding='utf-8', errors='ignore')
            and 'Ljava/util/LinkedHashMap;' in path.read_text(encoding='utf-8', errors='ignore')
            and '0x4000000000000000L' in path.read_text(encoding='utf-8', errors='ignore')
        ),
        None,
    )
    if menu_map is None:
        raise ValueError('OppoGallery2 backup-to-cloud menu map not found')
    data = menu_map.read_text(encoding='utf-8')
    pattern = re.compile(
        r'(?P<entry>'
        r'    sget (?P<id>v\d+), Lcom/oplus/gallery/photo_page/R\$id;->action_backup_to_cloud:I\n'
        r'.*?'
        r'    const-string(?:/jumbo)? (?P<name>v\d+), "action_backup_to_cloud"\n'
        r'.*?'
        r'    invoke-static/range \{v0 \.\. v6\}, L(?P<owner>[^;]+);->a\(Ljava/util/LinkedHashMap;ILjava/lang/String;JZZ\)V\n'
        r')',
        re.DOTALL,
    )

    def remove_backup_action(match: re.Match) -> str:
        return (
            match.group('entry')
            + '\n'
            + f'    sget {match.group("id")}, Lcom/oplus/gallery/photo_page/R$id;->action_backup_to_cloud:I\n'
            + '\n'
            + f'    invoke-static {{{match.group("id")}}}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;\n'
            + '\n'
            + f'    move-result-object {match.group("id")}\n'
            + '\n'
            + f'    invoke-virtual {{v0, {match.group("id")}}}, Ljava/util/LinkedHashMap;->remove(Ljava/lang/Object;)Ljava/lang/Object;\n'
        )

    fixed, count = pattern.subn(remove_backup_action, data, count=1)
    if count != 1 and 'action_backup_to_cloud' in data and 'LinkedHashMap;->remove' not in data:
        raise ValueError('OppoGallery2 backup-to-cloud menu entry not patched')
    menu_map.write_text(fixed, encoding='utf-8')

    # The 17.0.0.101 Settings screen places the Google Photos entry under one
    # category. Remove that category immediately after inflating the screen;
    # s1() already handles the resulting missing child preference.
    settings = _find_smali(
        tmp_dir,
        'com/oplus/gallery/settingpage/SettingsActivity$SettingFragment.smali',
        'OppoGallery2 Settings fragment',
    )
    data = settings.read_text(encoding='utf-8')
    screen_pattern = re.compile(
        r'(    iput-object (?P<screen>[vp]\d+), p0, '
        r'Lcom/oplus/gallery/settingpage/SettingsActivity\$SettingFragment;->l:'
        r'Landroidx/preference/PreferenceScreen;\n)'
    )
    fixed, count = screen_pattern.subn(
        lambda match: (
            match.group(0)
            + '\n'
            + f'    if-eqz {match.group("screen")}, :oplus_hide_google_photos_backup_settings_done\n'
            + '\n'
            + '    const-string v1, "pref_category_cloud_sync_key"\n'
            + '\n'
            + f'    invoke-virtual {{{match.group("screen")}, v1}}, Landroidx/preference/PreferenceGroup;->removePreferenceRecursively(Ljava/lang/CharSequence;)Z\n'
            + '\n'
            + '    :oplus_hide_google_photos_backup_settings_done\n'
        ),
        data,
        count=1,
    )
    if count != 1 and ':oplus_hide_google_photos_backup_settings_done' not in data:
        raise ValueError('OppoGallery2 Google Photos Settings category patch point not found')
    settings.write_text(fixed, encoding='utf-8')


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

    smali = next(
        (
            path
            for path in Path(tmp_dir).glob('smali*/**/*.smali')
            if '.source "ShareHelper.kt"' in path.read_text(encoding='utf-8', errors='ignore')
            and 'feature_is_support_user_custom_gallery_share' in path.read_text(encoding='utf-8', errors='ignore')
        ),
        None,
    )
    if smali is None:
        raise ValueError('OppoGallery2 ShareHelper smali not found')

    data = smali.read_text(encoding='utf-8', errors='ignore')
    # The feature gate above this block remains intact. Only bypass the
    # product flag that chooses Oplus's private share page, entering the
    # existing Android chooser branch at cond_2 instead.
    branch = re.compile(
        r'    sget-object (?P<result>v\d+), Lcom/oplus/aiunit/vision/[^;]+;->m0:Lkotlin/Lazy;\n'
        r'.*?'
        r'    move-result (?P=result)\n'
        r'(?:\n|    \.line \d+\n)*'
        r'    const/4 (?P<zero>v\d+), 0x0\n'
        r'(?:\n|    \.line \d+\n)*'
        r'    if-nez (?P=result), :(?P<label>cond_[0-9a-f]+)\n',
        re.DOTALL,
    )
    fixed, count = branch.subn(
        lambda match: (
            f'    const/4 {match.group("zero")}, 0x0\n'
            '\n'
            f'    goto :{match.group("label")}\n'
        ),
        data,
        count=1,
    )
    if count != 1:
        raise ValueError('OppoGallery2 ShareHelper system-share patch point not found')

    uri_body = (
        '    .locals 5\n'
        '\n'
        '    const-string v0, "<this>"\n'
        '\n'
        '    invoke-static {p0, v0}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullParameter(Ljava/lang/Object;Ljava/lang/String;)V\n'
        '\n'
        '    invoke-virtual {p0}, Lcom/oplus/aiunit/vision/j7v;->f()Lcom/oplus/gallery/business_lib/model/data/base/MediaObject;\n'
        '\n'
        '    move-result-object v0\n'
        '\n'
        '    instance-of v1, v0, Lcom/oplus/aiunit/vision/o3q;\n'
        '\n'
        '    if-eqz v1, :cond_fallback\n'
        '\n'
        '    check-cast v0, Lcom/oplus/aiunit/vision/o3q;\n'
        '\n'
        '    invoke-virtual {v0}, Lcom/oplus/aiunit/vision/o3q;->A()Ljava/lang/String;\n'
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
        '    sget-object v1, Lcom/oplus/aiunit/vision/teb;->a:Lcom/coloros/gallery3d/app/App;\n'
        '\n'
        '    if-eqz v1, :cond_fallback\n'
        '\n'
        '    new-instance v2, Lcom/oplus/aiunit/vision/j1i;\n'
        '\n'
        '    invoke-direct {v2, v0}, Lcom/oplus/aiunit/vision/j1i;-><init>(Ljava/lang/String;)V\n'
        '\n'
        '    const/4 v0, 0x0\n'
        '\n'
        '    new-array v0, v0, [Ljava/lang/String;\n'
        '\n'
        '    invoke-static {v1, v2, v0}, Lcom/oplus/gallery/foundation/fileaccess/GalleryFileProvider$a;->e(Landroid/content/Context;Lcom/oplus/aiunit/vision/j1i;[Ljava/lang/String;)Landroid/net/Uri;\n'
        '\n'
        '    move-result-object v0\n'
        '\n'
        '    return-object v0\n'
        '\n'
        '    :cond_fallback\n'
        '    invoke-static {p0}, Lcom/oplus/aiunit/vision/mfb0;->i(Lcom/oplus/aiunit/vision/j7v;)Z\n'
        '\n'
        '    move-result v0\n'
        '\n'
        '    const-string v1, "external_primary"\n'
        '\n'
        '    if-eqz v0, :cond_0\n'
        '\n'
        '    iget-object p0, p0, Lcom/oplus/aiunit/vision/j7v;->b:Ljava/lang/String;\n'
        '\n'
        '    const/4 v0, 0x1\n'
        '\n'
        '    invoke-static {v0, p0, v1}, Lcom/oplus/aiunit/vision/b7q;->i(ILjava/lang/String;Ljava/lang/String;)Landroid/net/Uri;\n'
        '\n'
        '    move-result-object p0\n'
        '\n'
        '    goto :goto_0\n'
        '\n'
        '    :cond_0\n'
        '    invoke-static {p0}, Lcom/oplus/aiunit/vision/mfb0;->j(Lcom/oplus/aiunit/vision/j7v;)Z\n'
        '\n'
        '    move-result v0\n'
        '\n'
        '    if-eqz v0, :cond_1\n'
        '\n'
        '    iget-object p0, p0, Lcom/oplus/aiunit/vision/j7v;->b:Ljava/lang/String;\n'
        '\n'
        '    const/4 v0, 0x3\n'
        '\n'
        '    invoke-static {v0, p0, v1}, Lcom/oplus/aiunit/vision/b7q;->i(ILjava/lang/String;Ljava/lang/String;)Landroid/net/Uri;\n'
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
        'public static c(Lcom/oplus/aiunit/vision/j7v;)Landroid/net/Uri;',
        uri_body,
    )
    if fixed == before_uri:
        raise ValueError('OppoGallery2 ShareHelper URI patch point not found')
    smali.write_text(fixed, encoding='utf-8')


def blob_fixup_oppogallery_lighthouse_native_libs(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    manifest = Path(tmp_dir) / 'AndroidManifest.xml'
    data = manifest.read_text(encoding='utf-8') if manifest.exists() else ''
    new = [
        '        <uses-native-library android:name="/odm/lib64/libQnnHtp.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/libQnnHtpPrepare.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/libQnnHtpV81Stub.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/libQnnHtpV81CalculatorStub.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/libQnnSaver.so" android:required="false"/>\n',
        '        <uses-native-library android:name="/odm/lib64/libQnnSystem.so" android:required="false"/>\n',
    ]

    # The stock manifest carries duplicated references to a V75 aiboost
    # directory that does not exist in the Lighthouse dump. Remove every
    # member of that obsolete path family, including duplicates, and place the
    # actual root-level V81 dependencies at the first old entry's position.
    obsolete = re.compile(
        r'        <uses-native-library android:name="/odm/lib64/'
        r'(?:aiboost/|Skel_signed/aiboost/)[^"]+" android:required="false"/>\n'
    )
    matches = list(obsolete.finditer(data))
    if matches:
        insert_at = matches[0].start()
        fixed = obsolete.sub('', data)
        fixed = fixed[:insert_at] + ''.join(new) + fixed[insert_at:]
    elif new[-1] in data:
        fixed = data
    else:
        insert_after = '        <uses-native-library android:name="libOpenCL.so" android:required="true"/>\n'
        fixed = data.replace(insert_after, insert_after + ''.join(new), 1)
        if fixed == data:
            raise ValueError('OppoGallery2 native-library insertion point not found')

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
    # ColorOS 17.0.0.101 resolves the hash through b(Context), with c(Context)
    # reading the APK signature, d(Context) querying PackageManager, and
    # e(Context) detecting LSPatch. Return the verified stock certificate hash
    # from every hash path and make only the LSPatch predicate false.
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

    smali = next(
        (
            path
            for path in Path(tmp_dir).glob('smali*/**/*.smali')
            if '.source "RepackagingDetector.java"' in path.read_text(encoding='utf-8', errors='ignore')
            and 'getCurrentSignatureHash' in path.read_text(encoding='utf-8', errors='ignore')
            and 'LSPatch detected in assets directory!' in path.read_text(encoding='utf-8', errors='ignore')
        ),
        None,
    )
    if smali is None:
        raise ValueError('Melody RepackagingDetector not found')

    data = smali.read_text(encoding='utf-8')
    fixed = data
    for method in ('b', 'c', 'd'):
        fixed = _replace_smali_method(
            fixed,
            f'public static {method}(Landroid/content/Context;)[B',
            key_body,
        )
    fixed = _replace_smali_method(
        fixed,
        'public static e(Landroid/content/Context;)Z',
        lspatch_body,
    )
    if fixed == data:
        raise ValueError('Melody RepackagingDetector methods not patched')
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
    # unintentionally enabled the native route that stock CPH2841 COS17 does not use.
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
        'liboplus-uah-client',
    ): lib_fixup_system_ext_suffix,
}

def blob_fixup_filemanager_select_dir_current_path_fallback(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return
    smali = _find_smali(
        tmp_dir,
        'com/oplus/selectdir/SelectDirPathPanelFragment.smali',
        'FileManager select-directory panel',
    )
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


def blob_fixup_filemanager_safecheck_direct(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return
    smali = next(
        (
            path
            for path in Path(tmp_dir).glob('smali*/com/filemanager/common/fileutils/*.smali')
            if '"JavaFileHelper"' in path.read_text(encoding='utf-8', errors='ignore')
            and '"safeCheck start"' in path.read_text(encoding='utf-8', errors='ignore')
        ),
        None,
    )
    if smali is None:
        raise ValueError('FileManager JavaFileHelper.safeCheck class not found')
    data = smali.read_text(encoding='utf-8')
    signature_match = re.search(
        r'^\.method (?P<signature>public final [A-Za-z0-9_$]+\((?P<function>L[^;]+;)Ljava/lang/Object;\)Ljava/lang/Object;)$',
        data,
        re.MULTILINE,
    )
    if signature_match is None:
        raise ValueError('FileManager JavaFileHelper.safeCheck signature not found')
    signature = signature_match.group('signature')
    function_type = signature_match.group('function')
    body = (
        '    .locals 3\n'
        '\n'
        '    const-string p0, "method"\n'
        '\n'
        '    invoke-static {p1, p0}, Lkotlin/jvm/internal/p;->h(Ljava/lang/Object;Ljava/lang/String;)V\n'
        '\n'
        '    const-string p0, "safeCheck direct"\n'
        '\n'
        '    const-string v0, "JavaFileHelper"\n'
        '\n'
        '    invoke-static {v0, p0}, Lcom/filemanager/common/utils/u3;->b(Ljava/lang/String;Ljava/lang/String;)V\n'
        '\n'
        '    :try_start_0\n'
        f'    invoke-interface {{p1}}, {function_type}->invoke()Ljava/lang/Object;\n'
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
        '    invoke-static {v0, p0}, Lcom/filemanager/common/utils/u3;->b(Ljava/lang/String;Ljava/lang/String;)V\n'
        '\n'
        '    return-object p2\n'
    )
    fixed = _replace_smali_method(data, signature, body)
    if fixed == data:
        raise ValueError('FileManager JavaFileHelper.safeCheck method not found')
    smali.write_text(fixed, encoding='utf-8')


blob_fixups: blob_fixups_user_type = {
    'system_ext/lib64/libcsextimpl.so': blob_fixup()
        .replace_needed(
            'android.hardware.camera.device-V3-ndk.so',
            'android.hardware.camera.device-V4-ndk.so',
        )
        .replace_needed(
            'android.hardware.camera.provider-V3-ndk.so',
            'android.hardware.camera.provider-V4-ndk.so',
        ),
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
        .call(blob_fixup_opluscamera_capture_dex)
        .call(blob_fixup_opluscamera_rear_rgb_sensor)
        .call(blob_fixup_opluscamera_font)
        .call(blob_fixup_opluscamera_blur_seginit_guard)
        .call(blob_fixup_strip_oem_permissions)
        .apktool_pack()
        .call(blob_fixup_opluscamera_restore_untouched_dex)
        .stripzip(),
    'system_ext/app/SystemUIPlugin/SystemUIPlugin.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_oplus_camera_system_properties)
        .apktool_pack()
        .stripzip(),
    'system_ext/app/OplusGestureUI/OplusGestureUI.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_gestureui_light_press_default)
        .call(blob_fixup_gestureui_search_settings_namespace)
        .call(blob_fixup_gestureui_settings_search)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/OppoGallery2/OppoGallery2.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_opluscamera_uses_library)
        .call(blob_fixup_oppogallery_lighthouse_native_libs)
        .call(blob_fixup_oppogallery_receiver_flags)
        .call(blob_fixup_oppogallery_wallpaper_attach_intent)
        .call(blob_fixup_oppogallery_safe_box_custom_flag)
        .call(blob_fixup_oppogallery_google_photos_consent_on_verify_failure)
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
        .call(blob_fixup_aiunit_settings_search)
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
        .call(blob_fixup_private_safe_unlock_dialog)
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
