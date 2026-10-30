.class public final Lcom/oplus/camera/port/RearRgbSensorKeepalive;
.super Ljava/lang/Object;
.implements Landroid/hardware/SensorEventListener;

.field private static sManager:Landroid/hardware/SensorManager;
.field private static sListener:Lcom/oplus/camera/port/RearRgbSensorKeepalive;

.method private constructor <init>()V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method

.method public static declared-synchronized start(Landroid/content/Context;)V
    .locals 4

    :try_start_0
    sget-object v1, Lcom/oplus/camera/port/RearRgbSensorKeepalive;->sListener:Lcom/oplus/camera/port/RearRgbSensorKeepalive;

    if-nez v1, :done

    const-string v1, "sensor"

    invoke-virtual {p0, v1}, Landroid/content/Context;->getSystemService(Ljava/lang/String;)Ljava/lang/Object;

    move-result-object v1

    check-cast v1, Landroid/hardware/SensorManager;

    if-eqz v1, :done

    const v2, 0x1fa266c

    invoke-virtual {v1, v2}, Landroid/hardware/SensorManager;->getDefaultSensor(I)Landroid/hardware/Sensor;

    move-result-object v2

    if-eqz v2, :done

    new-instance v3, Lcom/oplus/camera/port/RearRgbSensorKeepalive;

    invoke-direct {v3}, Lcom/oplus/camera/port/RearRgbSensorKeepalive;-><init>()V

    const/4 p0, 0x3

    invoke-virtual {v1, v3, v2, p0}, Landroid/hardware/SensorManager;->registerListener(Landroid/hardware/SensorEventListener;Landroid/hardware/Sensor;I)Z

    move-result p0

    if-eqz p0, :done

    sput-object v1, Lcom/oplus/camera/port/RearRgbSensorKeepalive;->sManager:Landroid/hardware/SensorManager;

    sput-object v3, Lcom/oplus/camera/port/RearRgbSensorKeepalive;->sListener:Lcom/oplus/camera/port/RearRgbSensorKeepalive;
    :try_end_0
    .catch Ljava/lang/RuntimeException; {:try_start_0 .. :try_end_0} :catch_0

    goto :done

    :catch_0
    move-exception p0

    const-string v1, "RearRgbKeepalive"

    const-string v2, "Rear RGB sensor registration failed"

    invoke-static {v1, v2, p0}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I

    :done
    return-void
.end method

.method public static declared-synchronized stop()V
    .locals 3

    sget-object v0, Lcom/oplus/camera/port/RearRgbSensorKeepalive;->sManager:Landroid/hardware/SensorManager;

    sget-object v1, Lcom/oplus/camera/port/RearRgbSensorKeepalive;->sListener:Lcom/oplus/camera/port/RearRgbSensorKeepalive;

    if-eqz v0, :clear

    if-eqz v1, :clear

    :try_start_0
    invoke-virtual {v0, v1}, Landroid/hardware/SensorManager;->unregisterListener(Landroid/hardware/SensorEventListener;)V
    :try_end_0
    .catch Ljava/lang/RuntimeException; {:try_start_0 .. :try_end_0} :catch_0

    goto :clear

    :catch_0
    move-exception v2

    const-string v0, "RearRgbKeepalive"

    const-string v1, "Rear RGB sensor removal failed"

    invoke-static {v0, v1, v2}, Landroid/util/Log;->w(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I

    :clear
    const/4 v0, 0x0

    sput-object v0, Lcom/oplus/camera/port/RearRgbSensorKeepalive;->sManager:Landroid/hardware/SensorManager;

    sput-object v0, Lcom/oplus/camera/port/RearRgbSensorKeepalive;->sListener:Lcom/oplus/camera/port/RearRgbSensorKeepalive;

    return-void
.end method

.method public onAccuracyChanged(Landroid/hardware/Sensor;I)V
    .locals 0

    return-void
.end method

.method public onSensorChanged(Landroid/hardware/SensorEvent;)V
    .locals 0

    return-void
.end method
