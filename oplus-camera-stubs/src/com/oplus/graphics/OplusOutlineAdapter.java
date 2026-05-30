package com.oplus.graphics;

import android.graphics.Outline;
import android.graphics.Rect;

public class OplusOutlineAdapter {
    private final Outline mOutline;

    public OplusOutlineAdapter(Outline outline, int force) {
        mOutline = outline;
    }

    public void setSmoothRoundRect(int left, int top, int right, int bottom, float radius) {
        if (mOutline != null) {
            mOutline.setRoundRect(left, top, right, bottom, radius);
        }
    }

    public void setSmoothRoundRect(Rect rect, float radius) {
        if (mOutline != null && rect != null) {
            mOutline.setRoundRect(rect, radius);
        }
    }
}
