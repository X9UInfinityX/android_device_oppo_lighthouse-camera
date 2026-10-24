# SPDX-License-Identifier: Apache-2.0
# Adapted from OP15InfinityX/android_device_oneplus_infiniti-camera
# commit 73cae650db7c01cc66e273f00f400fbfd032f20d (Daniel210191).

from pathlib import Path
import re


def blob_fixup_private_safe_unlock_dialog(ctx, file, file_path, *args, tmp_dir=None, **kwargs):
    """Size the embedded preferences to their dialog, not the full screen."""
    if tmp_dir is None:
        raise ValueError('Private Safe dialog fix requires decoded sources')

    root = Path(tmp_dir)
    fragments = list(root.glob(
        'smali*/com/oplus/encryption/settings/UnlockTypePreferenceFragment.smali'))
    scrolls = list(root.glob(
        'smali*/com/coui/appcompat/scrollview/COUINestedScrollView.smali'))
    if len(fragments) != 1 or len(scrolls) != 1:
        raise ValueError('Private Safe dialog implementation changed')

    fragment = fragments[0]
    data = fragment.read_text(encoding='utf-8')
    if ':ix_unlock_dialog_sized' not in data:
        match = re.search(
            r'^\.method public final onCreateView\([^\n]*\n.*?^\.end method',
            data, re.M | re.S,
        )
        if match is None:
            raise ValueError('Private Safe onCreateView not found')
        body = match[0]
        for anchor in ('    .locals 1', 'Ll8/h;->appBarLayout:I',
                       '    return-object p1'):
            if body.count(anchor) != 1:
                raise ValueError(f'Private Safe dialog anchor changed: {anchor}')
        body = body.replace('    .locals 1', '    .locals 2', 1)
        body = body.replace('Ll8/h;->appBarLayout:I', 'Ll8/h;->appbar_layout:I', 1)
        body = body.replace('    return-object p1', '''    # Measure the RecyclerView and both dialog containers by their content.
    invoke-virtual {p0}, Landroid/view/View;->getLayoutParams()Landroid/view/ViewGroup$LayoutParams;
    move-result-object v0
    if-eqz v0, :ix_unlock_list_sized
    const/4 v1, -0x2
    iput v1, v0, Landroid/view/ViewGroup$LayoutParams;->height:I
    invoke-virtual {p0, v0}, Landroid/view/View;->setLayoutParams(Landroid/view/ViewGroup$LayoutParams;)V
    :ix_unlock_list_sized
    const v0, 0x102003f
    invoke-virtual {p1, v0}, Landroid/view/View;->findViewById(I)Landroid/view/View;
    move-result-object p0
    if-eqz p0, :ix_unlock_container_sized
    invoke-virtual {p0}, Landroid/view/View;->getLayoutParams()Landroid/view/ViewGroup$LayoutParams;
    move-result-object v0
    if-eqz v0, :ix_unlock_container_sized
    const/4 v1, -0x2
    iput v1, v0, Landroid/view/ViewGroup$LayoutParams;->height:I
    invoke-virtual {p0, v0}, Landroid/view/View;->setLayoutParams(Landroid/view/ViewGroup$LayoutParams;)V
    :ix_unlock_container_sized
    invoke-virtual {p1}, Landroid/view/View;->getLayoutParams()Landroid/view/ViewGroup$LayoutParams;
    move-result-object v0
    if-eqz v0, :ix_unlock_dialog_sized
    const/4 v1, -0x2
    iput v1, v0, Landroid/view/ViewGroup$LayoutParams;->height:I
    invoke-virtual {p1, v0}, Landroid/view/View;->setLayoutParams(Landroid/view/ViewGroup$LayoutParams;)V
    :ix_unlock_dialog_sized
    const/4 p2, 0x0
    invoke-virtual {p1, p2}, Landroid/view/View;->setBackgroundColor(I)V
    return-object p1''', 1)
        fragment.write_text(data[:match.start()] + body + data[match.end():],
                            encoding='utf-8')

    scroll = scrolls[0]
    data = scroll.read_text(encoding='utf-8')
    if 'ixHasRawScrollApi' in data:
        return
    match = re.search(r'^\.method public final scrollTo\(II\)V\n.*?^\.end method',
                      data, re.M | re.S)
    if match is None:
        raise ValueError('Private Safe COUI scrollTo not found')
    body = match[0]
    anchor = '    if-eqz v2, :cond_3'
    fallback = ('invoke-super {p0, p1, p2}, '
                'Landroidx/core/widget/NestedScrollView;->scrollTo(II)V')
    if body.count(anchor) != 1 or fallback not in body or data.count('# instance fields\n') != 1:
        raise ValueError('Private Safe COUI raw-scroll branch changed')
    cls = 'Lcom/coui/appcompat/scrollview/COUINestedScrollView;'
    body = body.replace(anchor, anchor + f'''
    invoke-static {{}}, {cls}->ixHasRawScrollApi()Z
    move-result v2
    if-eqz v2, :cond_3''', 1)
    data = data[:match.start()] + body + data[match.end():]
    data = data.replace('# instance fields\n',
                        '.field private static volatile ixRawScrollApiAvailable:Ljava/lang/Boolean;\n\n# instance fields\n', 1)
    data += f'''
.method private static ixHasRawScrollApi()Z
    .locals 3
    sget-object v0, {cls}->ixRawScrollApiAvailable:Ljava/lang/Boolean;
    if-eqz v0, :ix_probe_raw_scroll
    invoke-virtual {{v0}}, Ljava/lang/Boolean;->booleanValue()Z
    move-result v0
    return v0
    :ix_probe_raw_scroll
    :ix_raw_scroll_try
    const-class v0, Landroid/view/View;
    const-string v1, "getViewWrapper"
    const/4 v2, 0x0
    new-array v2, v2, [Ljava/lang/Class;
    invoke-virtual {{v0, v1, v2}}, Ljava/lang/Class;->getMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;
    move-result-object v0
    invoke-virtual {{v0}}, Ljava/lang/reflect/Method;->getReturnType()Ljava/lang/Class;
    move-result-object v0
    const-string v1, "getViewExt"
    invoke-virtual {{v0, v1, v2}}, Ljava/lang/Class;->getMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;
    move-result-object v0
    invoke-virtual {{v0}}, Ljava/lang/reflect/Method;->getReturnType()Ljava/lang/Class;
    move-result-object v0
    sget-object v1, Ljava/lang/Integer;->TYPE:Ljava/lang/Class;
    filled-new-array {{v1}}, [Ljava/lang/Class;
    move-result-object v2
    const-string v1, "setScrollXForColor"
    invoke-virtual {{v0, v1, v2}}, Ljava/lang/Class;->getMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;
    const-string v1, "setScrollYForColor"
    invoke-virtual {{v0, v1, v2}}, Ljava/lang/Class;->getMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;
    :ix_raw_scroll_end
    .catch Ljava/lang/ReflectiveOperationException; {{:ix_raw_scroll_try .. :ix_raw_scroll_end}} :ix_raw_scroll_absent
    .catch Ljava/lang/SecurityException; {{:ix_raw_scroll_try .. :ix_raw_scroll_end}} :ix_raw_scroll_absent
    const/4 v0, 0x1
    goto :ix_raw_scroll_store
    :ix_raw_scroll_absent
    move-exception v0
    const/4 v0, 0x0
    :ix_raw_scroll_store
    invoke-static {{v0}}, Ljava/lang/Boolean;->valueOf(Z)Ljava/lang/Boolean;
    move-result-object v1
    sput-object v1, {cls}->ixRawScrollApiAvailable:Ljava/lang/Boolean;
    return v0
.end method
'''
    scroll.write_text(data, encoding='utf-8')
