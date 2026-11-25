<#
.SYNOPSIS
  Compila l'app Android di Mull2Five (Kotlin e Jetpack Compose). Istruzioni
  complete: docs/android.md.

.DESCRIPTION
  -Ambiente staging
      L'app di prova, che parla con lo staging: pacchetto it.mull2five.app.staging,
      nome "M2F staging", firmata con la chiave di debug di questo PC
      (%USERPROFILE%\.android\debug.keystore, la crea Gradle la prima volta).
      Esce in android\mull2five-staging.apk.

  -Ambiente produzione -ChiaveDebug
      L'app vera (mull2five.it) firmata con la chiave di debug di questo PC, per
      provarla sul telefono senza Google Play: android\mull2five-produzione-debug.apk.
      Prima di installare quella di Google Play va disinstallata.

  -Ambiente produzione
      Per Google Play: android\mull2five-produzione.aab, e l'APK firmato allo
      stesso modo. La chiave di caricamento è %USERPROFILE%\.mull2five\mull2five-upload.jks
      (alias "upload"), o quella in M2F_KEYSTORE / M2F_KEY_ALIAS; la password
      la chiede lo script qui nel terminale e non resta scritta da nessuna parte.

  Alla fine stampa l'impronta SHA-256 della firma dell'APK: è quella che va su
  Render in ANDROID_CERT_FINGERPRINTS perché i link a /event.html si aprano
  nell'app. Per l'app scaricata da Google Play vale invece l'impronta della
  chiave di Google (Play Console, "Integrità dell'app").

  Prima volta su questo PC: android\strumenti.ps1.

.PARAMETER ChiaveDebug
  Firma con la chiave di debug invece che con quella di caricamento. Lo staging
  si firma sempre così.

.PARAMETER Installa
  Dopo la compilazione installa l'APK sul telefono collegato con il cavo (adb).

.PARAMETER Api
  Fa parlare l'app con un'altra API invece che col sito del suo ambiente. Per
  l'API di sviluppo sul PC, dall'emulatore: -Api http://10.0.2.2:8000
#>
param(
    [Parameter(Mandatory)][ValidateSet('staging', 'produzione')][string]$Ambiente,
    [switch]$ChiaveDebug,
    [switch]$Installa,
    [string]$Api
)

$ErrorActionPreference = 'Stop'

function Invoke-Checked([string]$What, [scriptblock]$Command) {
    # Gradle scrive avvisi su stderr: conta solo il codice d'uscita.
    $ErrorActionPreference = 'Continue'
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What è uscito con il codice $LASTEXITCODE" }
}

$configFile = Join-Path $HOME '.bubblewrap\config.json'
if (-not (Test-Path $configFile)) { throw "Manca $configFile`: prima va lanciato android\strumenti.ps1" }
$config = Get-Content $configFile -Raw | ConvertFrom-Json
$env:JAVA_HOME = $config.jdkPath
$env:ANDROID_HOME = $config.androidSdkPath
$env:Path = "$(Join-Path $config.jdkPath 'bin');$env:Path"

$flavor = (Get-Culture).TextInfo.ToTitleCase($Ambiente)   # staging → Staging, per i nomi dei task
$debug = $ChiaveDebug -or $Ambiente -eq 'staging'
$service = if ($Ambiente -eq 'staging') { 'mull2five-staging' } else { 'mull2five' }
$outputs = Join-Path $PSScriptRoot 'app\build\outputs'

$gradleArgs = @("assemble${flavor}Release", '--no-daemon', '--console=plain')
if ($Api) { $gradleArgs += "-Papi=$Api" }
if ($debug) {
    $gradleArgs += '-PfirmaDebug'
} else {
    $gradleArgs += "bundle${flavor}Release"
    $key = if ($env:M2F_KEYSTORE) { $env:M2F_KEYSTORE } else { Join-Path $HOME '.mull2five\mull2five-upload.jks' }
    if (-not (Test-Path $key)) { throw "Manca la chiave di caricamento $key (docs/android.md, ""La chiave di caricamento"")" }
    $secure = Read-Host "Password della chiave $key" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $env:M2F_KEYSTORE_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

Push-Location $PSScriptRoot
try {
    Invoke-Checked 'gradle' { .\gradlew.bat @gradleArgs }
} finally {
    Remove-Item Env:M2F_KEYSTORE_PASSWORD -ErrorAction SilentlyContinue
    Pop-Location
}

$name = if ($Ambiente -eq 'staging') { 'mull2five-staging' } elseif ($debug) { 'mull2five-produzione-debug' } else { 'mull2five-produzione' }
$apk = Join-Path $PSScriptRoot "$name.apk"
Copy-Item (Join-Path $outputs "apk\$Ambiente\release\app-$Ambiente-release.apk") $apk -Force
Write-Host ''
Write-Host "APK: $apk"
# Le notifiche all'istante vogliono app\google-services.json (docs/android.md, "Firebase").
if (Test-Path (Join-Path $PSScriptRoot 'app\google-services.json')) {
    Write-Host 'Firebase: si, notifiche all''istante.'
} else {
    Write-Host 'Firebase: no (manca app\google-services.json): notifiche ogni 15 minuti.'
}
if (-not $debug) {
    $aab = Join-Path $PSScriptRoot "$name.aab"
    Copy-Item (Join-Path $outputs "bundle\${Ambiente}Release\app-$Ambiente-release.aab") $aab -Force
    Write-Host "Per Google Play: $aab"
}

# L'impronta la si legge dall'APK, così non serve la password della chiave.
$buildTools = Get-ChildItem (Join-Path $env:ANDROID_HOME 'build-tools') -Directory |
    Sort-Object { [version]$_.Name } | Select-Object -Last 1
$apksigner = Join-Path $buildTools.FullName 'apksigner.bat'
$hex = & $apksigner verify --print-certs $apk | Select-String 'certificate SHA-256 digest: ([0-9a-f]+)' |
    ForEach-Object { $_.Matches[0].Groups[1].Value } | Select-Object -First 1
if ($hex) {
    $sha = (($hex.ToUpper() -split '(..)') | Where-Object { $_ }) -join ':'
    Write-Host "Impronta della firma: $sha"
    Write-Host "Su Render, servizio ${service}: ANDROID_CERT_FINGERPRINTS (separate da virgola se sono piu' di una)."
}

if ($Installa) {
    Invoke-Checked 'adb install' { & (Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe') install -r $apk }
}
