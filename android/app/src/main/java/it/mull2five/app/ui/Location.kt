package it.mull2five.app.ui

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import android.os.CancellationSignal
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.core.location.LocationManagerCompat
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume

/**
 * "Vicino a me", come "Usa la mia posizione" sul sito: chiede il permesso la
 * prima volta, poi la posizione approssimativa. Resta sul telefono: va al
 * server solo come punto della ricerca. Null se il permesso manca o la
 * posizione non arriva.
 */
@Composable
fun rememberLocationRequest(onResult: (Pair<Double, Double>?) -> Unit): () -> Unit {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) scope.launch { onResult(currentLocation(context)) } else onResult(null)
    }
    return {
        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
        if (granted) scope.launch { onResult(currentLocation(context)) }
        else launcher.launch(Manifest.permission.ACCESS_COARSE_LOCATION)
    }
}

@SuppressLint("MissingPermission")
private suspend fun currentLocation(context: Context): Pair<Double, Double>? {
    val manager = context.getSystemService(LocationManager::class.java) ?: return null
    val provider = listOf(LocationManager.NETWORK_PROVIDER, LocationManager.GPS_PROVIDER, LocationManager.PASSIVE_PROVIDER)
        .firstOrNull(manager::isProviderEnabled) ?: return null
    val fresh = withTimeoutOrNull(15_000) {
        suspendCancellableCoroutine { cont ->
            val signal = CancellationSignal()
            cont.invokeOnCancellation { signal.cancel() }
            LocationManagerCompat.getCurrentLocation(manager, provider, signal, ContextCompat.getMainExecutor(context)) {
                cont.resume(it)
            }
        }
    }
    val location = fresh ?: manager.getLastKnownLocation(provider) ?: return null
    return location.latitude to location.longitude
}
