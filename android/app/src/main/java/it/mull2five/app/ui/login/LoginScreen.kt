package it.mull2five.app.ui.login

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import it.mull2five.app.R
import it.mull2five.app.ui.LocalContainer
import it.mull2five.app.ui.asString
import it.mull2five.app.ui.openInTab
import it.mull2five.app.ui.theme.Brand

/** Accedi o registrati: email e password, o Google. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LoginScreen(auth: AuthViewModel, onBack: () -> Unit) {
    var tab by rememberSaveable { mutableIntStateOf(0) }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.login_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.back))
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier.padding(padding).fillMaxSize().imePadding().verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp),
        ) {
            Image(
                painterResource(R.drawable.logo_mark),
                contentDescription = null,
                modifier = Modifier.padding(vertical = 16.dp).size(64.dp).align(Alignment.CenterHorizontally),
            )
            PrimaryTabRow(selectedTabIndex = tab, containerColor = MaterialTheme.colorScheme.background) {
                Tab(tab == 0, onClick = { tab = 0; auth.clearMessages() }, text = { Text(stringResource(R.string.login_tab_signin)) })
                Tab(tab == 1, onClick = { tab = 1; auth.clearMessages() }, text = { Text(stringResource(R.string.login_tab_signup)) })
            }
            Spacer(Modifier.height(20.dp))
            if (tab == 0) SignInForm(auth) else SignUpForm(auth)
            Messages(auth)
            if (auth.rules.googleLogin) {
                Row(Modifier.padding(vertical = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                    HorizontalDivider(Modifier.weight(1f))
                    Text(
                        stringResource(R.string.login_or),
                        modifier = Modifier.padding(horizontal = 12.dp),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    HorizontalDivider(Modifier.weight(1f))
                }
                val context = LocalContext.current
                OutlinedButton(
                    onClick = { auth.startGoogle(context) },
                    enabled = !auth.busy,
                    modifier = Modifier.fillMaxWidth().height(52.dp),
                ) { Text(stringResource(R.string.login_google)) }
            }
            Spacer(Modifier.height(32.dp))
        }
    }
}

@Composable
private fun SignInForm(auth: AuthViewModel) {
    var email by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        EmailField(email) { email = it }
        PasswordField(password) { password = it }
        SubmitButton(stringResource(R.string.login_submit), auth.busy, enabled = email.isNotBlank() && password.isNotEmpty()) {
            auth.login(email, password)
        }
        TextButton(onClick = { auth.forgotPassword(email) }, modifier = Modifier.align(Alignment.CenterHorizontally)) {
            Text(stringResource(R.string.login_forgot))
        }
    }
}

@Composable
private fun SignUpForm(auth: AuthViewModel) {
    var name by rememberSaveable { mutableStateOf("") }
    var email by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var age by rememberSaveable { mutableStateOf(false) }
    var terms by rememberSaveable { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        OutlinedTextField(
            name, { name = it },
            label = { Text(stringResource(R.string.signup_name)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        EmailField(email) { email = it }
        PasswordField(password, supporting = stringResource(R.string.signup_password_hint)) { password = it }
        ConsentChecks(auth.rules.minAccountAge, age, { age = it }, terms, { terms = it })
        SubmitButton(
            stringResource(R.string.signup_submit),
            auth.busy,
            enabled = name.length >= 2 && email.isNotBlank() && password.length >= 8 && age && terms,
        ) { auth.signup(name, email, password, age, terms) }
    }
}

/** Età minima e termini: li chiede il sito a tutti, anche a chi entra con Google. */
@Composable
fun ConsentChecks(
    minAge: Int,
    age: Boolean,
    onAge: (Boolean) -> Unit,
    terms: Boolean,
    onTerms: (Boolean) -> Unit,
) {
    val site = LocalContainer.current.siteUrl
    val context = LocalContext.current
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(age, onAge)
            Text(stringResource(R.string.signup_age, minAge), style = MaterialTheme.typography.bodyMedium)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(terms, onTerms)
            Text(stringResource(R.string.signup_terms), style = MaterialTheme.typography.bodyMedium)
        }
        Row(Modifier.padding(start = 36.dp)) {
            TextButton(onClick = { context.openInTab("$site/termini.html") }) { Text(stringResource(R.string.link_terms)) }
            TextButton(onClick = { context.openInTab("$site/privacy.html") }) { Text(stringResource(R.string.link_privacy)) }
        }
    }
}

@Composable
private fun EmailField(value: String, onChange: (String) -> Unit) {
    OutlinedTextField(
        value, onChange,
        label = { Text(stringResource(R.string.login_email)) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun PasswordField(value: String, supporting: String? = null, onChange: (String) -> Unit) {
    OutlinedTextField(
        value, onChange,
        label = { Text(stringResource(R.string.login_password)) },
        singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        supportingText = supporting?.let { { Text(it) } },
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
fun SubmitButton(text: String, busy: Boolean, enabled: Boolean = true, onClick: () -> Unit) {
    Button(onClick = onClick, enabled = enabled && !busy, modifier = Modifier.fillMaxWidth().height(52.dp)) {
        if (busy) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp) else Text(text)
    }
}

@Composable
fun Messages(auth: AuthViewModel) {
    auth.error?.let {
        Text(it.asString(), color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(top = 12.dp))
    }
    auth.notice?.let {
        Text(it.asString(), color = Brand.Green, modifier = Modifier.padding(top = 12.dp))
    }
}

/** Chi entra con Google per la prima volta: nome, età e termini, e l'account nasce. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GoogleSignupScreen(auth: AuthViewModel, onBack: () -> Unit) {
    val pending = auth.googleSignup
    var name by rememberSaveable { mutableStateOf(pending?.name.orEmpty()) }
    var age by rememberSaveable { mutableStateOf(false) }
    var terms by rememberSaveable { mutableStateOf(false) }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.google_signup_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.back))
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier.padding(padding).fillMaxSize().imePadding().verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (pending == null) {
                Text(stringResource(R.string.google_error_expired))
                return@Column
            }
            Text(stringResource(R.string.google_signup_intro, pending.email), style = MaterialTheme.typography.bodyLarge)
            OutlinedTextField(
                name, { name = it },
                label = { Text(stringResource(R.string.signup_name)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            ConsentChecks(auth.rules.minAccountAge, age, { age = it }, terms, { terms = it })
            SubmitButton(stringResource(R.string.signup_submit), auth.busy, enabled = name.length >= 2 && age && terms) {
                auth.completeGoogleSignup(name, age, terms)
            }
            Messages(auth)
        }
    }
}
