import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

// Le notifiche all'istante con Firebase (notify/Push.kt) ci sono solo se qui
// accanto c'è google-services.json, che si scarica dalla console di Firebase e
// resta fuori dal repository (docs/android.md). Senza, l'app compila lo stesso
// e le notifiche le prende ogni 15 minuti.
if (file("google-services.json").exists()) apply(plugin = "com.google.gms.google-services")

// Per provarla con l'API di sviluppo: compila.ps1 -Api http://10.0.2.2:8000
// (dall'emulatore 10.0.2.2 è il PC). Senza, parla col sito del suo ambiente.
val apiOverride: String? = providers.gradleProperty("api").orNull?.trimEnd('/')
// -PfirmaDebug firma la release con la chiave di debug di questo PC, per provarla
// senza Google Play. Altrimenti la chiave di caricamento, se compila.ps1 ha messo
// le password nell'ambiente; senza, l'APK esce non firmato.
val firmaDebug = providers.gradleProperty("firmaDebug").isPresent
val uploadPassword: String? = providers.environmentVariable("M2F_KEYSTORE_PASSWORD").orNull

android {
    namespace = "it.mull2five.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "it.mull2five.app"
        minSdk = 26
        targetSdk = 36
        // Si alza a ogni versione caricata su Google Play (docs/android.md).
        versionCode = 2
        versionName = "2.0.0"
        buildConfigField("String", "API_OVERRIDE", "\"${apiOverride.orEmpty()}\"")
        manifestPlaceholders["cleartext"] = (apiOverride?.startsWith("http://") == true).toString()
    }

    flavorDimensions += "ambiente"
    productFlavors {
        create("produzione") {
            dimension = "ambiente"
            buildConfigField("String", "SITE_URL", "\"https://mull2five.it\"")
            manifestPlaceholders["siteHost"] = "mull2five.it"
        }
        create("staging") {
            dimension = "ambiente"
            applicationIdSuffix = ".staging"
            versionNameSuffix = "-staging"
            buildConfigField("String", "SITE_URL", "\"https://mull2five-staging.onrender.com\"")
            manifestPlaceholders["siteHost"] = "mull2five-staging.onrender.com"
        }
    }

    signingConfigs {
        create("caricamento") {
            storeFile = file(
                providers.environmentVariable("M2F_KEYSTORE")
                    .orElse(System.getProperty("user.home") + "/.mull2five/mull2five-upload.jks").get()
            )
            storePassword = uploadPassword
            keyAlias = providers.environmentVariable("M2F_KEY_ALIAS").orElse("upload").get()
            keyPassword = providers.environmentVariable("M2F_KEY_PASSWORD").orNull ?: uploadPassword
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = when {
                firmaDebug -> signingConfigs.getByName("debug")
                uploadPassword != null -> signingConfigs.getByName("caricamento")
                else -> null
            }
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/traduzioni"))
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

// I messaggi d'errore del server sono in italiano: l'app li traduce con gli
// stessi file del sito (frontend/locales), copiati negli asset a ogni compilazione.
val copiaTraduzioni = tasks.register<Copy>("copiaTraduzioni") {
    from(rootProject.file("../frontend/locales")) { include("*.json") }
    into(layout.buildDirectory.dir("generated/traduzioni/locales"))
}
tasks.named("preBuild") { dependsOn(copiaTraduzioni) }

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.05.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-core")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")

    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.navigation:navigation-compose:2.9.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.1")
    implementation("androidx.browser:browser:1.8.0")
    implementation("androidx.work:work-runtime-ktx:2.10.1")
    // La 35.2 porta kotlin-stdlib 2.1.21, lo stesso Kotlin di qui: una più nuova
    // potrebbe volerne uno che questo compilatore non legge.
    implementation(platform("com.google.firebase:firebase-bom:35.2.0"))
    implementation("com.google.firebase:firebase-messaging")

    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    testImplementation("junit:junit:4.13.2")
}
