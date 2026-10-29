import java.time.Duration
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "app.watchd"
    compileSdk = 37

    defaultConfig {
        applicationId = "app.watchd"
        minSdk = 28
        targetSdk = 37
        // Every build newer than the last, so the app's updater can tell:
        // minutes since 2026, and the build time as the name.
        val built = LocalDateTime.now()
        versionCode = Duration.between(LocalDateTime.of(2026, 1, 1, 0, 0), built).toMinutes().toInt()
        versionName = built.format(DateTimeFormatter.ofPattern("yyyy.MM.dd-HHmm"))
    }

    // Watchd's own key, kept outside the repo: its path and password are in
    // ~/.gradle/gradle.properties. Without them (another PC), the debug key.
    val keystore = providers.gradleProperty("WATCHD_KEYSTORE").orNull
    signingConfigs {
        if (keystore != null) {
            create("watchd") {
                storeFile = file(keystore)
                storePassword = providers.gradleProperty("WATCHD_KEY_PASSWORD").get()
                keyAlias = providers.gradleProperty("WATCHD_KEY_ALIAS").get()
                keyPassword = providers.gradleProperty("WATCHD_KEY_PASSWORD").get()
            }
        }
    }
    val signing = signingConfigs.findByName("watchd") ?: signingConfigs.getByName("debug")

    buildTypes {
        // Test builds and published ones share the key, so each installs over the other.
        debug {
            signingConfig = signing
        }
        release {
            isMinifyEnabled = false
            signingConfig = signing
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
    }
}

dependencies {
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.material.icons)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.navigation.compose)
    implementation(libs.coil.compose)
    implementation(libs.coil.okhttp)
    implementation(libs.coil.svg)
    implementation(libs.okhttp)
    implementation(libs.serialization.json)
    implementation(libs.datastore.preferences)
    implementation(libs.work.runtime)
    implementation(libs.glance.appwidget)
    debugImplementation(libs.compose.ui.tooling)
}
