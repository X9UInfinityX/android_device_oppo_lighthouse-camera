package com.oplus.inner.hardware.camera2.impl;

import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.CaptureResult;
import android.util.Log;
import java.lang.reflect.Field;
import java.lang.reflect.Method;

public class CameraMetadataNativeWrapper {
    private static final String TAG = "CameraMetadataNativeWrapper";

    public static long getMetadataPtr(Object obj) {
        if (obj == null) {
            return 0L;
        }

        try {
            Object nativeMeta = obj;

            if (obj instanceof CameraCharacteristics) {
                nativeMeta = getCameraCharacteristicsNative((CameraCharacteristics) obj);
            } else if (obj instanceof CaptureRequest) {
                nativeMeta = getCaptureRequestNative((CaptureRequest) obj);
            } else if (obj instanceof CaptureResult) {
                nativeMeta = getCaptureResultNative((CaptureResult) obj);
            }

            if (nativeMeta == null) {
                return 0L;
            }

            Field ptrField = nativeMeta.getClass().getDeclaredField("mMetadataPtr");
            ptrField.setAccessible(true);
            return ptrField.getLong(nativeMeta);
        } catch (Exception e) {
            Log.e(TAG, "Failed to get metadata ptr from " + obj.getClass().getName(), e);
            return 0L;
        }
    }

    private static Object getCameraCharacteristicsNative(CameraCharacteristics characteristics)
            throws Exception {
        try {
            Method getNativeCopy = CameraCharacteristics.class.getDeclaredMethod("getNativeCopy");
            getNativeCopy.setAccessible(true);
            return getNativeCopy.invoke(characteristics);
        } catch (Exception e) {
            Field properties = CameraCharacteristics.class.getDeclaredField("mProperties");
            properties.setAccessible(true);
            return properties.get(characteristics);
        }
    }

    private static Object getCaptureRequestNative(CaptureRequest request) throws Exception {
        try {
            Method getNativeCopy = CaptureRequest.class.getDeclaredMethod("getNativeCopy");
            getNativeCopy.setAccessible(true);
            return getNativeCopy.invoke(request);
        } catch (Exception e) {
            Field settings = CaptureRequest.class.getDeclaredField("mLogicalCameraSettings");
            settings.setAccessible(true);
            return settings.get(request);
        }
    }

    private static Object getCaptureResultNative(CaptureResult result) throws Exception {
        try {
            Method getNativeCopy = CaptureResult.class.getDeclaredMethod("getNativeCopy");
            getNativeCopy.setAccessible(true);
            return getNativeCopy.invoke(result);
        } catch (Exception e) {
            Field results = CaptureResult.class.getDeclaredField("mResults");
            results.setAccessible(true);
            return results.get(result);
        }
    }
}
