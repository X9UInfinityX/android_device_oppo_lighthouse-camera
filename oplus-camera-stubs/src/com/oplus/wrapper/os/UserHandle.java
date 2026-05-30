package com.oplus.wrapper.os;

public final class UserHandle {
    private UserHandle() {
    }

    public static int myUserId() {
        return android.os.UserHandle.myUserId();
    }
}
