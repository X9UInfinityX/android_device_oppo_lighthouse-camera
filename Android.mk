LOCAL_PATH := $(call my-dir)

define oplus-gallery-qnn-lib
include $$(CLEAR_VARS)
LOCAL_MODULE := $(1)_gallery_app_lib
LOCAL_MODULE_CLASS := SHARED_LIBRARIES
LOCAL_MODULE_SUFFIX := .so
LOCAL_MODULE_STEM := $(1)
LOCAL_MODULE_TAGS := optional
LOCAL_SRC_FILES := configs/lib64/$(1).so
LOCAL_MODULE_PATH := $$(TARGET_OUT_SYSTEM_EXT)/priv-app/OppoGallery2/lib/arm64
LOCAL_CHECK_ELF_FILES := false
LOCAL_STRIP_MODULE := false
include $$(BUILD_PREBUILT)
endef

$(eval $(call oplus-gallery-qnn-lib,libQnnHtp))
$(eval $(call oplus-gallery-qnn-lib,libQnnHtpPrepare))
$(eval $(call oplus-gallery-qnn-lib,libQnnHtpV81Stub))
$(eval $(call oplus-gallery-qnn-lib,libQnnHtpV81CalculatorStub))
$(eval $(call oplus-gallery-qnn-lib,libQnnSaver))
$(eval $(call oplus-gallery-qnn-lib,libQnnSystem))
