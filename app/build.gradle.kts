import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val signingProperties = Properties().apply {
    val propertiesFile = rootProject.file("local.properties")
    if (propertiesFile.isFile) {
        propertiesFile.inputStream().use { load(it) }
    }
}

val betaStoreFile = signingProperties.getProperty("halocue.betaStoreFile")
val betaStorePassword = signingProperties.getProperty("halocue.betaStorePassword")
val betaKeyAlias = signingProperties.getProperty("halocue.betaKeyAlias")
val betaKeyPassword = signingProperties.getProperty("halocue.betaKeyPassword")
val hasBetaSigning = listOf(
    betaStoreFile,
    betaStorePassword,
    betaKeyAlias,
    betaKeyPassword,
).all { !it.isNullOrBlank() }
val requiresBetaSigning = gradle.startParameter.taskNames.any {
    it.contains("release", ignoreCase = true) || it.contains("deviceBeta", ignoreCase = true)
}
if (requiresBetaSigning && !hasBetaSigning) {
    error("Release builds require the halocue.beta* properties in local.properties")
}

android {
    namespace = "com.halocue.android"
    compileSdk = 36

    buildFeatures {
        buildConfig = true
    }

    defaultConfig {
        applicationId = "com.halocue.android"
        minSdk = 24
        targetSdk = 36
        versionCode = 6
        versionName = "0.4.0-beta.1"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    signingConfigs {
        if (hasBetaSigning) {
            create("betaRelease") {
                storeFile = file(requireNotNull(betaStoreFile))
                storePassword = betaStorePassword
                keyAlias = betaKeyAlias
                keyPassword = betaKeyPassword
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            if (hasBetaSigning) {
                signingConfig = signingConfigs.getByName("betaRelease")
            }
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
        create("deviceBeta") {
            initWith(getByName("release"))
            applicationIdSuffix = ".devicebeta"
            versionNameSuffix = "-device"
            matchingFallbacks += listOf("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        pip {
            install("pillow==11.0.0")
        }
    }
}

dependencies {
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("androidx.core:core-ktx:1.16.0")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
    androidTestImplementation("androidx.test.espresso:espresso-web:3.6.1")
}
