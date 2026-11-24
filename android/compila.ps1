<#
.SYNOPSIS
  Compila l'app Android di Mull2Five. Istruzioni complete: docs/android.md.

.DESCRIPTION
  Rifà da capo il progetto Gradle da <Ambiente>\twa-manifest.json, che è l'unica
  cosa nel repository, e lo compila. Le icone le scarica dal sito: il sito di
  quell'ambiente dev'essere acceso e avere il commit con le icone.

  -Ambiente staging
      APK di prova, firmato con la chiave di debug di questo PC
      (%USERPROFILE%\.android\debug.keystore, la crea Gradle la prima volta).
      Esce in android\staging\mull2five-staging.apk, e lo script stampa
      l'impronta da mettere su Render in ANDROID_CERT_FINGERPRINTS dello staging.

  -Ambiente produzione
      AAB per Google Play (app-release-bundle.aab) e APK firmato, con la chiave
      di caricamento indicata in produzione\twa-manifest.json (signingKey).
      Le password le chiede Bubblewrap qui nel terminale.

  Prima volta su questo PC: android\strumenti.ps1.

.PARAMETER Installa
  Dopo la compilazione installa l'APK sul telefono collegato con il cavo (adb).
#>
param(
    [Parameter(Mandatory)][ValidateSet('staging', 'produzione')][string]$Ambiente,
    [switch]$Installa
)

$ErrorActionPreference = 'Stop'

function Invoke-Checked([string]$What, [scriptblock]$Command) {
    # Gradle e Bubblewrap scrivono avvisi su stderr: conta solo il codice d'uscita.
    $ErrorActionPreference = 'Continue'
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What è uscito con il codice $LASTEXITCODE" }
}

$configFile = Join-Path $HOME '.bubblewrap\config.json'
if (-not (Test-Path $configFile)) { throw "Manca $configFile`: prima va lanciato android\strumenti.ps1" }
$config = Get-Content $configFile -Raw | ConvertFrom-Json
$env:JAVA_HOME = $config.jdkPath
$env:ANDROID_HOME = $config.androidSdkPath

$twa = Get-Content (Join-Path $PSScriptRoot "$Ambiente\twa-manifest.json") -Raw | ConvertFrom-Json
$key = $twa.signingKey.path -replace '^~', $HOME
$alias = $twa.signingKey.alias
$bubblewrap = Join-Path $PSScriptRoot 'node_modules\@bubblewrap\cli\bin\bubblewrap.js'

Push-Location $PSScriptRoot
try {
    if (-not (Test-Path $bubblewrap)) { Invoke-Checked 'npm ci' { npm.cmd ci } }

    # Percorsi relativi: la cartella del progetto ha uno spazio nel nome.
    Invoke-Checked 'bubblewrap update' {
        node $bubblewrap update --skipVersionUpgrade "--manifest=$Ambiente/twa-manifest.json" "--directory=$Ambiente"
    }

    Set-Location $Ambiente
    if ($Ambiente -eq 'staging') {
        Invoke-Checked 'gradle' { .\gradlew.bat assembleDebug --no-daemon }
        $apk = Join-Path (Get-Location) 'mull2five-staging.apk'
        Copy-Item 'app\build\outputs\apk\debug\app-debug.apk' $apk -Force

        # La chiave di debug ha la stessa password su tutti i PC ("android"): non è un segreto.
        $keytool = Join-Path $config.jdkPath 'bin\keytool.exe'
        $sha = & $keytool -list -v -keystore $key -alias $alias -storepass android |
            Select-String 'SHA256:' | ForEach-Object { ($_ -split 'SHA256:')[1].Trim() }
        Write-Host ''
        Write-Host "Impronta della chiave di debug di questo PC: $sha"
        Write-Host 'Su Render, servizio mull2five-staging: ANDROID_CERT_FINGERPRINTS (separate da virgola se sono piu'' di una).'
    } else {
        if (-not (Test-Path $key)) { throw "Manca la chiave di caricamento $key (docs/android.md, ""La chiave di caricamento"")" }
        Invoke-Checked 'bubblewrap build' {
            node $bubblewrap build --skipPwaValidation "--signingKeyPath=$key" "--signingKeyAlias=$alias"
        }
        $apk = Join-Path (Get-Location) 'app-release-signed.apk'
        Write-Host ''
        Write-Host "Per Google Play: $(Join-Path (Get-Location) 'app-release-bundle.aab')"
    }
    Write-Host "APK: $apk"

    if ($Installa) {
        Invoke-Checked 'adb install' { & (Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe') install -r $apk }
    }
} finally {
    Pop-Location
}
