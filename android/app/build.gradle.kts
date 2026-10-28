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
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // A personal, sideloaded app: the debug key signs release builds too.
            signingConfig = signingConfigs.getByName("debug")
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
    implementation(libs.code.scanner)
    debugImplementation(libs.compose.ui.tooling)
}
