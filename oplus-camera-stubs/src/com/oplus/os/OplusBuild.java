package com.oplus.os;

import android.content.Context;
import android.os.Build;
import android.provider.Settings;

public class OplusBuild {
    public static final int UNKNOWN = 0;
    public static final int OplusOS_12_0 = 23;
    public static final int OplusOS_12_1 = 24;
    public static final int OplusOS_12_2 = 25;
    public static final int OplusOS_16_0 = 37;

    public static class VERSION {
        public static final String RELEASE = "V16.0.0";
        public static final int SDK_VERSION = OplusOS_16_0;
        public static final int SDK_SUB_VERSION = 28;
    }

    public static int getOplusOSVERSION() {
        return VERSION.SDK_VERSION;
    }

    public static boolean setDeviceName(String name) {
        return true;
    }

    public static String getDeviceName() {
        return Build.MODEL;
    }

    public static String getDeviceName(Context context) {
        String name = Settings.Global.getString(context.getContentResolver(), Settings.Global.DEVICE_NAME);
        if (name == null || name.trim().isEmpty()) {
            return Build.MODEL;
        }
        return name;
    }

    public static void putDeviceName(Context context, String deviceName) {
        if (deviceName != null) {
            Settings.Global.putString(context.getContentResolver(), Settings.Global.DEVICE_NAME, deviceName);
        }
    }

    public static void setDeviceName(Context context, String deviceName) {
        putDeviceName(context, deviceName);
    }

    public static String getVersionProp(String property) {
        return VERSION.RELEASE;
    }
}
