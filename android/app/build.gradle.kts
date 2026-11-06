import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// Versionen står ét sted: VERSION i tilbudsagent.py
val appVersion: String = Regex("""VERSION\s*=\s*"([^"]+)"""")
    .find(rootProject.file("../tilbudsagent.py").readText())!!.groupValues[1]

// Python-kode og app.html mv. kopieres fra repoets rod, så der kun er én kopi at vedligeholde
val genPython = layout.buildDirectory.dir("generated/python")
val genAssets = layout.buildDirectory.dir("generated/res-assets")

val syncKilder by tasks.registering(Copy::class) {
    from(rootProject.file("../")) { include("tilbudsagent.py", "webapp.py", "steder.py") }
    from(file("src/main/python")) { include("android_main.py") }
    into(genPython)
}
val syncRes by tasks.registering(Copy::class) {
    from(rootProject.file("../")) { include("app.html", "config.toml", "varer.csv") }
    into(genAssets.map { it.dir("res") })
}
tasks.matching { it.name == "preBuild" }.configureEach { dependsOn(syncKilder, syncRes) }

android {
    namespace = "dk.pwrtzner.tilbudsagent"
    compileSdk = 34

    defaultConfig {
        applicationId = "dk.pwrtzner.tilbudsagent"
        minSdk = 29
        targetSdk = 34
        versionCode = (project.findProperty("versionCode") as String?)?.toInt() ?: 1
        versionName = appVersion
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    signingConfigs {
        create("udgivelse") {
            val ks = System.getenv("KEYSTORE_FIL")
            if (ks != null) {
                storeFile = file(ks)
                storePassword = System.getenv("KEYSTORE_KODE")
                keyAlias = System.getenv("NOEGLE_ALIAS")
                keyPassword = System.getenv("KEYSTORE_KODE")
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (System.getenv("KEYSTORE_FIL") != null) signingConfigs.getByName("udgivelse")
                            else signingConfigs.getByName("debug")
        }
    }
    sourceSets.getByName("main").assets.srcDir(genAssets)
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

chaquopy {
    defaultConfig {
        version = "3.12"
    }
    sourceSets {
        getByName("main") { srcDir(genPython) }
    }
}
