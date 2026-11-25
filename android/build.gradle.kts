// Le versioni stanno qui, una volta sola. AGP 8.9 e Gradle 8.11 sono quelli
// che strumenti.ps1 prepara; per salire di versione vedi docs/android.md.
plugins {
    id("com.android.application") version "8.9.1" apply false
    id("org.jetbrains.kotlin.android") version "2.1.21" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.1.21" apply false
    id("org.jetbrains.kotlin.plugin.serialization") version "2.1.21" apply false
    // Firebase, solo se c'è app/google-services.json (app/build.gradle.kts).
    id("com.google.gms.google-services") version "4.6.0" apply false
}
