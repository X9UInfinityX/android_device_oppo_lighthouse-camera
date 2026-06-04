package com.oplus.app;

import android.os.Binder;
import android.os.IBinder;
import android.os.IInterface;
import android.os.Parcel;
import android.os.RemoteException;

import java.util.List;
import java.util.Map;

public interface IOplusAccessControlManager extends IInterface {
    String DESCRIPTOR = "com.oplus.app.IOplusAccessControlManager";

    void setAccessControlAppsInfo(String type, Map accessControlInfo, int userId) throws RemoteException;

    Map getAccessControlAppsInfo(String type, int userId) throws RemoteException;

    void setAccessControlEnabled(String type, boolean enable, int userId) throws RemoteException;

    boolean getAccessControlEnabled(String type, int userId) throws RemoteException;

    void addEncryptPass(String packageName, int windowMode, int userId) throws RemoteException;

    boolean isEncryptPass(String packageName, int userId) throws RemoteException;

    boolean isEncryptedPackage(String packageName, int userId) throws RemoteException;

    boolean registerAccessControlObserver(String type, IOplusAccessControlObserver observer) throws RemoteException;

    boolean unregisterAccessControlObserver(String type, IOplusAccessControlObserver observer) throws RemoteException;

    void updateRusList(int type, List<String> addList, List<String> deleteList) throws RemoteException;

    class Default implements IOplusAccessControlManager {
        @Override
        public void setAccessControlAppsInfo(String type, Map accessControlInfo, int userId) throws RemoteException {
        }

        @Override
        public Map getAccessControlAppsInfo(String type, int userId) throws RemoteException {
            return null;
        }

        @Override
        public void setAccessControlEnabled(String type, boolean enable, int userId) throws RemoteException {
        }

        @Override
        public boolean getAccessControlEnabled(String type, int userId) throws RemoteException {
            return false;
        }

        @Override
        public void addEncryptPass(String packageName, int windowMode, int userId) throws RemoteException {
        }

        @Override
        public boolean isEncryptPass(String packageName, int userId) throws RemoteException {
            return false;
        }

        @Override
        public boolean isEncryptedPackage(String packageName, int userId) throws RemoteException {
            return false;
        }

        @Override
        public boolean registerAccessControlObserver(String type, IOplusAccessControlObserver observer) throws RemoteException {
            return false;
        }

        @Override
        public boolean unregisterAccessControlObserver(String type, IOplusAccessControlObserver observer) throws RemoteException {
            return false;
        }

        @Override
        public void updateRusList(int type, List<String> addList, List<String> deleteList) throws RemoteException {
        }

        @Override
        public IBinder asBinder() {
            return null;
        }
    }

    abstract class Stub extends Binder implements IOplusAccessControlManager {
        static final int TRANSACTION_setAccessControlAppsInfo = IBinder.FIRST_CALL_TRANSACTION;
        static final int TRANSACTION_getAccessControlAppsInfo = IBinder.FIRST_CALL_TRANSACTION + 1;
        static final int TRANSACTION_setAccessControlEnabled = IBinder.FIRST_CALL_TRANSACTION + 2;
        static final int TRANSACTION_getAccessControlEnabled = IBinder.FIRST_CALL_TRANSACTION + 3;
        static final int TRANSACTION_addEncryptPass = IBinder.FIRST_CALL_TRANSACTION + 4;
        static final int TRANSACTION_isEncryptPass = IBinder.FIRST_CALL_TRANSACTION + 5;
        static final int TRANSACTION_isEncryptedPackage = IBinder.FIRST_CALL_TRANSACTION + 6;
        static final int TRANSACTION_registerAccessControlObserver = IBinder.FIRST_CALL_TRANSACTION + 7;
        static final int TRANSACTION_unregisterAccessControlObserver = IBinder.FIRST_CALL_TRANSACTION + 8;
        static final int TRANSACTION_updateRusList = IBinder.FIRST_CALL_TRANSACTION + 9;

        public Stub() {
            attachInterface(this, DESCRIPTOR);
        }

        public static IOplusAccessControlManager asInterface(IBinder obj) {
            if (obj == null) {
                return null;
            }
            IInterface iin = obj.queryLocalInterface(DESCRIPTOR);
            if (iin instanceof IOplusAccessControlManager) {
                return (IOplusAccessControlManager) iin;
            }
            return new Proxy(obj);
        }

        @Override
        public IBinder asBinder() {
            return this;
        }

        private static class Proxy implements IOplusAccessControlManager {
            private final IBinder mRemote;

            Proxy(IBinder remote) {
                mRemote = remote;
            }

            @Override
            public IBinder asBinder() {
                return mRemote;
            }

            @Override
            public void setAccessControlAppsInfo(String type, Map accessControlInfo, int userId) throws RemoteException {
                Parcel data = Parcel.obtain(asBinder());
                Parcel reply = Parcel.obtain();
                try {
                    data.writeInterfaceToken(DESCRIPTOR);
                    data.writeString(type);
                    data.writeMap(accessControlInfo);
                    data.writeInt(userId);
                    mRemote.transact(TRANSACTION_setAccessControlAppsInfo, data, reply, 0);
                    reply.readException();
                } finally {
                    reply.recycle();
                    data.recycle();
                }
            }

            @Override
            public Map getAccessControlAppsInfo(String type, int userId) throws RemoteException {
                Parcel data = Parcel.obtain(asBinder());
                Parcel reply = Parcel.obtain();
                try {
                    data.writeInterfaceToken(DESCRIPTOR);
                    data.writeString(type);
                    data.writeInt(userId);
                    mRemote.transact(TRANSACTION_getAccessControlAppsInfo, data, reply, 0);
                    reply.readException();
                    return reply.readHashMap(getClass().getClassLoader());
                } finally {
                    reply.recycle();
                    data.recycle();
                }
            }

            @Override
            public void setAccessControlEnabled(String type, boolean enable, int userId) throws RemoteException {
                Parcel data = Parcel.obtain(asBinder());
                Parcel reply = Parcel.obtain();
                try {
                    data.writeInterfaceToken(DESCRIPTOR);
                    data.writeString(type);
                    data.writeBoolean(enable);
                    data.writeInt(userId);
                    mRemote.transact(TRANSACTION_setAccessControlEnabled, data, reply, 0);
                    reply.readException();
                } finally {
                    reply.recycle();
                    data.recycle();
                }
            }

            @Override
            public boolean getAccessControlEnabled(String type, int userId) throws RemoteException {
                Parcel data = Parcel.obtain(asBinder());
                Parcel reply = Parcel.obtain();
                try {
                    data.writeInterfaceToken(DESCRIPTOR);
                    data.writeString(type);
                    data.writeInt(userId);
                    mRemote.transact(TRANSACTION_getAccessControlEnabled, data, reply, 0);
                    reply.readException();
                    return reply.readBoolean();
                } finally {
                    reply.recycle();
                    data.recycle();
                }
            }

            @Override
            public void addEncryptPass(String packageName, int windowMode, int userId) throws RemoteException {
                Parcel data = Parcel.obtain(asBinder());
                Parcel reply = Parcel.obtain();
                try {
                    data.writeInterfaceToken(DESCRIPTOR);
                    data.writeString(packageName);
                    data.writeInt(windowMode);
                    data.writeInt(userId);
                    mRemote.transact(TRANSACTION_addEncryptPass, data, reply, 0);
                    reply.readException();
                } finally {
                    reply.recycle();
                    data.recycle();
                }
            }

            @Override
            public boolean isEncryptPass(String packageName, int userId) throws RemoteException {
                Parcel data = Parcel.obtain(asBinder());
                Parcel reply = Parcel.obtain();
                try {
                    data.writeInterfaceToken(DESCRIPTOR);
                    data.writeString(packageName);
                    data.writeInt(userId);
                    mRemote.transact(TRANSACTION_isEncryptPass, data, reply, 0);
                    reply.readException();
                    return reply.readBoolean();
                } finally {
                    reply.recycle();
                    data.recycle();
                }
            }

            @Override
            public boolean isEncryptedPackage(String packageName, int userId) throws RemoteException {
                Parcel data = Parcel.obtain(asBinder());
                Parcel reply = Parcel.obtain();
                try {
                    data.writeInterfaceToken(DESCRIPTOR);
                    data.writeString(packageName);
                    data.writeInt(userId);
                    mRemote.transact(TRANSACTION_isEncryptedPackage, data, reply, 0);
                    reply.readException();
                    return reply.readBoolean();
                } finally {
                    reply.recycle();
                    data.recycle();
                }
            }

            @Override
            public boolean registerAccessControlObserver(String type, IOplusAccessControlObserver observer) throws RemoteException {
                Parcel data = Parcel.obtain(asBinder());
                Parcel reply = Parcel.obtain();
                try {
                    data.writeInterfaceToken(DESCRIPTOR);
                    data.writeString(type);
                    data.writeStrongInterface(observer);
                    mRemote.transact(TRANSACTION_registerAccessControlObserver, data, reply, 0);
                    reply.readException();
                    return reply.readBoolean();
                } finally {
                    reply.recycle();
                    data.recycle();
                }
            }

            @Override
            public boolean unregisterAccessControlObserver(String type, IOplusAccessControlObserver observer) throws RemoteException {
                Parcel data = Parcel.obtain(asBinder());
                Parcel reply = Parcel.obtain();
                try {
                    data.writeInterfaceToken(DESCRIPTOR);
                    data.writeString(type);
                    data.writeStrongInterface(observer);
                    mRemote.transact(TRANSACTION_unregisterAccessControlObserver, data, reply, 0);
                    reply.readException();
                    return reply.readBoolean();
                } finally {
                    reply.recycle();
                    data.recycle();
                }
            }

            @Override
            public void updateRusList(int type, List<String> addList, List<String> deleteList) throws RemoteException {
                Parcel data = Parcel.obtain(asBinder());
                Parcel reply = Parcel.obtain();
                try {
                    data.writeInterfaceToken(DESCRIPTOR);
                    data.writeInt(type);
                    data.writeStringList(addList);
                    data.writeStringList(deleteList);
                    mRemote.transact(TRANSACTION_updateRusList, data, reply, 0);
                    reply.readException();
                } finally {
                    reply.recycle();
                    data.recycle();
                }
            }
        }
    }
}
