<#
.SYNOPSIS
  Gli strumenti per compilare l'app Android: JDK 17 e Android SDK, in
  %USERPROFILE%\.bubblewrap, con la configurazione che compila.ps1 legge.

.DESCRIPTION
  Una volta per PC; rilanciato, salta quello che c'è già. Circa 1 GB, più le
  librerie che Gradle scarica alla prima compilazione.
  La cartella si chiama così per la prima versione dell'app (il sito dentro
  Chrome, fatto con Bubblewrap): l'app nativa non lo usa più, ma i PC che
  l'avevano hanno già tutto lì. Si prendono il Temurin 17 a 64 bit e gli
  strumenti più recenti che hanno ancora sdkmanager, in tools\ dentro l'SDK:
  nella radice dell'SDK Gradle prenderebbe tutto l'SDK per un pacchetto solo e
  non troverebbe più le piattaforme.

  Istruzioni complete: docs/android.md.

.PARAMETER AccettoLicenzeSdk
  Accetta la licenza dell'Android SDK (https://developer.android.com/studio/terms)
  senza chiederla. Senza, sdkmanager la mostra e aspetta una "y" per ognuna.
#>
param([switch]$AccettoLicenzeSdk)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # con la barra, Invoke-WebRequest di PowerShell 5.1 è lentissimo

$root = Join-Path $HOME '.bubblewrap'
$jdkRoot = Join-Path $root 'jdk'
$sdk = Join-Path $root 'android_sdk'
# Quelle che vuole android/app/build.gradle.kts: la piattaforma è il suo
# compileSdk, e vanno alzate insieme (docs/android.md, "Aggiornare").
$buildTools = '36.1.0'
$platform = 'android-36'
# Gli strumenti 19.0: dai 23.0 sdkmanager è sostituito dalla "Android CLI", che
# non capisce "build-tools;36.1.0", scarica 300 MB in %USERPROFILE%\.android ed
# esce con 0 anche quando non installa niente.
$cmdlineToolsUrl = 'https://dl.google.com/android/repository/commandlinetools-win-13114758_latest.zip'
$jdkUrl = 'https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse?project=jdk'

New-Item -ItemType Directory -Force $jdkRoot, $sdk | Out-Null

# ── JDK 17 ──────────────────────────────────────────────────────────────────
$jdk = Get-ChildItem $jdkRoot -Directory -Filter 'jdk-17*' | Select-Object -First 1
if (-not $jdk) {
    $zip = Join-Path $root 'jdk17.zip'
    Write-Host 'Scarico il JDK 17 (Temurin, 64 bit, ~190 MB)...'
    Invoke-WebRequest $jdkUrl -OutFile $zip
    tar -xf $zip -C $jdkRoot
    Remove-Item $zip
    $jdk = Get-ChildItem $jdkRoot -Directory -Filter 'jdk-17*' | Select-Object -First 1
}
Write-Host "JDK: $($jdk.FullName)"

# ── Android SDK ─────────────────────────────────────────────────────────────
$sdkmanager = Join-Path $sdk 'tools\bin\sdkmanager.bat'
if (-not (Test-Path $sdkmanager)) {
    $zip = Join-Path $root 'cmdline-tools.zip'
    Write-Host 'Scarico gli strumenti dell''Android SDK (~140 MB)...'
    Invoke-WebRequest $cmdlineToolsUrl -OutFile $zip
    tar -xf $zip -C $root
    Move-Item (Join-Path $root 'cmdline-tools') (Join-Path $sdk 'tools')
    Remove-Item $zip
}

$env:JAVA_HOME = $jdk.FullName
if ($AccettoLicenzeSdk) {
    Write-Host 'Accetto le licenze dell''Android SDK...'
    (1..30 | ForEach-Object { 'y' }) | & $sdkmanager --licenses "--sdk_root=$sdk" | Out-Null
} else {
    & $sdkmanager --licenses "--sdk_root=$sdk"
}
Write-Host "Installo build-tools $buildTools, $platform e platform-tools..."
& $sdkmanager --install "build-tools;$buildTools" "platforms;$platform" 'platform-tools' "--sdk_root=$sdk"
# Il codice d'uscita non basta: si guarda se le cartelle ci sono davvero.
foreach ($dir in "build-tools\$buildTools", "platforms\$platform", 'platform-tools') {
    if (-not (Test-Path (Join-Path $sdk $dir))) { throw "sdkmanager non ha installato $dir" }
}

# ── La configurazione che compila.ps1 legge ─────────────────────────────────
# Senza BOM, come la scriveva la prima versione: ConvertFrom-Json la legge comunque.
$config = @{ jdkPath = $jdk.FullName; androidSdkPath = $sdk } | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $root 'config.json'), $config)
Write-Host "Pronto. Configurazione in $(Join-Path $root 'config.json')"
