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
from pathlib import Path
import re
import shutil


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
        'com.oplus.permission.safe.CAMERA',
        'com.oplus.permission.safe.CAR_LINK',
        'com.oplus.permission.safe.CONNECTIVITY',
        'com.oplus.permission.safe.IOT',
        'com.oplus.permission.safe.LOG',
        'com.oplus.permission.safe.MEDIA',
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
        'com.oppo.permission.safe.PRIVATE',
        'com.oppo.permission.safe.SAU',
        'com.oppo.permission.safe.SECURITY',
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


def blob_fixup_aiunit_authorize_camera(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes2/com/oplus/aiunit/core/AIUnitServiceBinder.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    old = (
        '    :goto_3\n'
        '    new-instance v8, Ljava/lang/StringBuilder;\n'
    )
    new = (
        '    :goto_3\n'
        '    const-string v8, "com.oplus.camera"\n'
        '\n'
        '    invoke-static {v4, v8}, Lkotlin/jvm/internal/Intrinsics;->areEqual(Ljava/lang/Object;Ljava/lang/Object;)Z\n'
        '\n'
        '    move-result v8\n'
        '\n'
        '    if-nez v8, :cond_oplus_aiunit_trusted_auth\n'
        '\n'
        '    const-string v8, "com.oneplus.gallery"\n'
        '\n'
        '    invoke-static {v4, v8}, Lkotlin/jvm/internal/Intrinsics;->areEqual(Ljava/lang/Object;Ljava/lang/Object;)Z\n'
        '\n'
        '    move-result v8\n'
        '\n'
        '    if-eqz v8, :cond_oplus_aiunit_auth\n'
        '\n'
        '    :cond_oplus_aiunit_trusted_auth\n'
        '    move v5, v6\n'
        '\n'
        '    :cond_oplus_aiunit_auth\n'
        '    new-instance v8, Ljava/lang/StringBuilder;\n'
    )
    fixed = data.replace(old, new)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')

    smali = Path(tmp_dir) / 'smali_classes2/com/oplus/aiunit/AIUnitProvider.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    old = (
        '    :cond_3\n'
        '    invoke-virtual {p0}, Lcom/oplus/aiunit/base/component/BaseContentProvider;->a()Landroid/content/Context;\n'
    )
    new = (
        '    :cond_3\n'
        '    const-string v2, "com.oplus.camera"\n'
        '\n'
        '    invoke-static {p1, v2}, Lkotlin/jvm/internal/Intrinsics;->areEqual(Ljava/lang/Object;Ljava/lang/Object;)Z\n'
        '\n'
        '    move-result v2\n'
        '\n'
        '    if-nez v2, :cond_oplus_aiunit_provider_trusted_auth\n'
        '\n'
        '    const-string v2, "com.oneplus.gallery"\n'
        '\n'
        '    invoke-static {p1, v2}, Lkotlin/jvm/internal/Intrinsics;->areEqual(Ljava/lang/Object;Ljava/lang/Object;)Z\n'
        '\n'
        '    move-result v2\n'
        '\n'
        '    if-eqz v2, :cond_oplus_aiunit_provider_auth\n'
        '\n'
        '    :cond_oplus_aiunit_provider_trusted_auth\n'
        '    return v1\n'
        '\n'
        '    :cond_oplus_aiunit_provider_auth\n'
        '    invoke-virtual {p0}, Lcom/oplus/aiunit/base/component/BaseContentProvider;->a()Landroid/content/Context;\n'
    )
    fixed = data.replace(old, new, 1)
    old = (
        '    move-result-object v0\n'
        '\n'
        '    .line 5\n'
        '    if-nez v0, :cond_0\n'
    )
    new = (
        '    move-result-object v0\n'
        '\n'
        '    const-string v1, "com.oplus.camera"\n'
        '\n'
        '    invoke-static {v0, v1}, Lkotlin/jvm/internal/Intrinsics;->areEqual(Ljava/lang/Object;Ljava/lang/Object;)Z\n'
        '\n'
        '    move-result v1\n'
        '\n'
        '    if-nez v1, :cond_oplus_aiunit_remote_trusted_auth\n'
        '\n'
        '    const-string v1, "com.oneplus.gallery"\n'
        '\n'
        '    invoke-static {v0, v1}, Lkotlin/jvm/internal/Intrinsics;->areEqual(Ljava/lang/Object;Ljava/lang/Object;)Z\n'
        '\n'
        '    move-result v1\n'
        '\n'
        '    if-eqz v1, :cond_oplus_aiunit_remote_auth\n'
        '\n'
        '    :cond_oplus_aiunit_remote_trusted_auth\n'
        '    const/4 v1, 0x1\n'
        '\n'
        '    return v1\n'
        '\n'
        '    :cond_oplus_aiunit_remote_auth\n'
        '    .line 5\n'
        '    if-nez v0, :cond_0\n'
    )
    fixed = fixed.replace(old, new, 1)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_aiunit_plugin_so_permissions(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    smali = Path(tmp_dir) / 'smali_classes2/com/oplus/orange/core/utils/FileUtil.smali'
    data = smali.read_text(encoding='utf-8') if smali.exists() else ''
    old = (
        '    invoke-static {v2, v10, v11}, Lcom/oplus/orange/core/utils/FileUtil;->unzip(Ljava/util/zip/ZipFile;Ljava/util/zip/ZipEntry;Ljava/io/File;)V\n'
        '\n'
        '    .line 220\n'
        '    .line 221\n'
        '    .line 222\n'
        '    const/4 v10, 0x0\n'
    )
    new = (
        '    invoke-static {v2, v10, v11}, Lcom/oplus/orange/core/utils/FileUtil;->unzip(Ljava/util/zip/ZipFile;Ljava/util/zip/ZipEntry;Ljava/io/File;)V\n'
        '\n'
        '    const/4 v13, 0x1\n'
        '\n'
        '    invoke-virtual {v11, v13, v4}, Ljava/io/File;->setReadable(ZZ)Z\n'
        '\n'
        '    invoke-virtual {v11, v13, v4}, Ljava/io/File;->setExecutable(ZZ)Z\n'
        '\n'
        '    .line 220\n'
        '    .line 221\n'
        '    .line 222\n'
        '    const/4 v10, 0x0\n'
    )
    fixed = data.replace(old, new, 1)
    if fixed != data:
        smali.write_text(fixed, encoding='utf-8')


def blob_fixup_oplus_camera_system_properties(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    if tmp_dir is None:
        return

    for smali in Path(tmp_dir).glob('smali*/**/*.smali'):
        data = smali.read_text(encoding='utf-8')
        fixed = data.replace(
            'Lcom/oplus/wrapper/os/SystemProperties;',
            'Landroid/os/SystemProperties;',
        )
        if fixed != data:
            smali.write_text(fixed, encoding='utf-8')


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
            'com.oplus.DolIsStaggerState': 'com.oplus.capture.request.idx',
            'com.oplus.iris.aperture.switching': 'com.oplus.capture.request.idx',
            'com.oplus.control.face.dr': 'com.oplus.capture.request.idx',
            'com.oplus.fallback.stable': 'com.oplus.capture.request.idx',
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
            'com.oplus.aec.customAE.enable': 'com.oplus.macro.closeup.enable',
            'com.oplus.lsd.enable': 'com.oplus.capture.request.idx',
            'com.oplus.only.zoom.change': 'com.oplus.capture.request.idx',
            'com.oplus.config.aeExposureCompensation': 'com.oplus.capture.request.idx',
            'com.oplus.naturetone.state': 'com.oplus.capture.request.idx',
            'com.oplus.hal.fluency': 'com.oplus.capture.request.idx',
            'com.oplus.double.ois.wirecutoff.detection.sn': 'com.oplus.capture.request.idx',
            'com.oplus.izoom.ability.support': 'com.oplus.aps.zoom.feature',
            'com.oplus.mipiraw.online.bpc': 'com.oplus.capture.mipiraw.online.bpc',
            'com.oplus.algo.visualization.enable': 'com.oplus.multiobj.info.visualization',
            'com.oplus.camera.algo.visualization.enable': 'com.oplus.multiobj.info.visualization',
            'com.oplus.sod.enable': 'com.oplus.sod.touch.region',
            'com.oplus.process.pid': 'com.oplus.capture.request.idx',
            'com.oplus.caller.package.name': 'com.oplus.packageName',
            'com.oplus.camera.is.turn.on': 'com.oplus.is.sdk.camera.package',
            'com.oplus.device.orientation': 'com.oplus.preview.orientation',
            'com.oplus.TR.processing.state': 'com.oplus.capture.request.idx',
            'com.oplus.capture.request.idx_list': 'com.oplus.capture.request.idx',
            'com.oplus.facebeauty.custom': 'com.oplus.facebeauty.level',
            'com.oplus.picture.offset.time': 'com.oplus.capture.request.idx',
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

        if False and smali.match('*/com/oplus/ocs/camera/producer/info/CameraCharacteristicsHelper.smali'):
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
        if False and smali.match('*/com/oplus/ocs/camera/producer/device/Camera2Impl$2.smali'):
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
            # Do not replay cached preview or force photo_mode/rear camera here.
            # Those hacks can keep the display path tied to the old camera during switches.
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

        if smali.match('*/tk/e0.smali'):
            fixed = _replace_smali_method(
                fixed,
                'public static i()Z',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n',
            )
            fixed = _noop_smali_method(fixed, 'public final A(I)V')
            fixed = _noop_smali_method(fixed, 'public final u(Z)V')
            fixed = _noop_smali_method(fixed, 'public final z()V')

        if smali.match('*/d9/c.smali'):
            fixed = _noop_smali_method(fixed, 'public final run()V')

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
                '    .locals 6\n'
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

        if smali.match('*/com/oplus/camera/feature/integration/mirror/MirrorOplusEdrUtils.smali'):
            fixed = _noop_smali_method(fixed, 'static constructor <clinit>()V')
            fixed = _replace_smali_method(
                fixed,
                'public static setEdrAnimDuration(Landroid/view/SurfaceControl;Landroid/view/SurfaceControl$Transaction;II)Z',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n',
            )
            fixed = _replace_smali_method(
                fixed,
                'public static setEdrSdrRatio(Landroid/view/SurfaceControl;Landroid/view/SurfaceControl$Transaction;F)Z',
                '    .locals 1\n'
                '\n'
                '    const/4 v0, 0x0\n'
                '\n'
                '    return v0\n',
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
                '    .locals 2\n'
                '\n'
                '    invoke-super {p0, p1}, Lcom/oplus/ocs/camera/appinterface/CameraStateCallbackAdapter;->onCameraOpened(Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;)V\n'
                '\n'
                '    iget-object p0, p0, Lcom/oplus/ocs/camera/CameraStateCallbackAdapterV2;->mCameraStateCallback:Lcom/oplus/ocs/camera/CameraStateCallback;\n'
                '\n'
                '    new-instance v1, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;\n'
                '\n'
                '    invoke-direct {v1, p1}, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;-><init>(Lcom/oplus/ocs/camera/appinterface/CameraDeviceInterface;)V\n'
                '\n'
                '    if-eqz p0, :cond_0\n'
                '\n'
                '    new-instance v0, Lcom/oplus/ocs/camera/CameraDevice;\n'
                '\n'
                '    invoke-direct {v0, v1}, Lcom/oplus/ocs/camera/CameraDevice;-><init>(Lcom/oplus/ocs/camera/CameraDeviceAdapter;)V\n'
                '\n'
                '    invoke-virtual {p0, v0}, Lcom/oplus/ocs/camera/CameraStateCallback;->onCameraOpened(Lcom/oplus/ocs/camera/CameraDevice;)V\n'
                '\n'
                '    :cond_0\n'
                '    invoke-virtual {v1}, Lcom/oplus/ocs/camera/CameraDeviceAdapterV2;->op15ReplayCachedPreview()V\n'
                '\n'
                '    return-void\n',
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

        if smali.match('*/v7/d$a.smali'):
            fixed = re.sub(
                r'(?m)^\.implements Lcom/oplus/wrapper/hardware/devicestate/DeviceStateManager\$DeviceStateCallback;\n\n?',
                '',
                fixed,
            )

        fixed = fixed.replace(
            'Lcom/oplus/wrapper/hardware/devicestate/DeviceStateManager$DeviceStateCallback;',
            'Ljava/lang/Object;',
        )
        fixed = fixed.replace(
            'Lcom/oplus/wrapper/hardware/devicestate/DeviceStateManager;',
            'Ljava/lang/Object;',
        )
        fixed = fixed.replace(
            'Lcom/oplus/wrapper/hardware/devicestate/DeviceState;',
            'Ljava/lang/Object;',
        )

        if smali.match('*/v7/d$a.smali'):
            fixed = _noop_smali_method(fixed, 'public final onDeviceStateChanged(Ljava/lang/Object;)V')

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

blob_fixups: blob_fixups_user_type = {
    (
        'system_ext/framework/com.oplus.camera.unit.sdk.jar',
        'system_ext/framework/com.oplus.camera.unit.sdk.adapter.jar',
    ): blob_fixup()
        .apktool_unpack('patches/OplusCamera')
        .call(blob_fixup_oplus_camera_framework_shims)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/OplusCamera/OplusCamera.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_opluscamera_oppo_component_safe)
        .call(blob_fixup_oplus_camera_system_properties)
        .call(blob_fixup_oplus_camera_framework_shims)
        .apktool_pack()
        .stripzip(),
    'system_ext/app/AIUnit/AIUnit.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_src)
        .call(blob_fixup_aiunit_authorize_camera)
        .call(blob_fixup_aiunit_plugin_so_permissions)
        .call(blob_fixup_oplus_camera_framework_shims)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/OppoGallery2/OppoGallery2.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_oppogallery_op15_native_libs)
        .call(blob_fixup_oppogallery_receiver_flags)
        .apktool_pack()
        .stripzip(),
    'system_ext/app/SecurityPermission/SecurityPermission.apk': blob_fixup()
        .call(blob_fixup_apktool_unpack_full)
        .call(blob_fixup_securitypermission_safe_permissions)
        .apktool_pack()
        .stripzip(),
    'system_ext/priv-app/OplusAppPlatform/OplusAppPlatform.apk': blob_fixup(),
}  # fmt: skip

namespace_imports = [
    'vendor/oneplus/camera/camera',
    'vendor/oneplus/infiniti',
    'vendor/oneplus/sm8850-common',
    'hardware/oplus',
]

module = ExtractUtilsModule(
    'camera',
    'oneplus/camera',
    device_rel_path='vendor/oneplus/camera',
    blob_fixups=blob_fixups,
    lib_fixups=lib_fixups,
    namespace_imports=namespace_imports,
)

if __name__ == '__main__':
    utils = ExtractUtils.device(module)
    utils.run()
