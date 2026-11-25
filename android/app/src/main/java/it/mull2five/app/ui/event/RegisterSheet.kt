package it.mull2five.app.ui.event

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import it.mull2five.app.R
import it.mull2five.app.data.Formats
import it.mull2five.app.data.RegistrationField
import it.mull2five.app.data.RegistrationIn
import it.mull2five.app.data.Tournament
import it.mull2five.app.ui.login.SubmitButton
import kotlinx.serialization.json.JsonPrimitive

/** Il modulo d'iscrizione di event.html: ID Wizards, domande del torneo, codice sconto, come si paga. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RegisterSheet(
    t: Tournament,
    form: RegisterForm,
    busy: Boolean,
    error: String?,
    onDismiss: () -> Unit,
    onSubmit: (RegistrationIn) -> Unit,
) {
    var publisherId by rememberSaveable { mutableStateOf(form.publisherId) }
    var handle by rememberSaveable { mutableStateOf(form.handle) }
    var discount by rememberSaveable { mutableStateOf("") }
    var method by rememberSaveable { mutableStateOf(form.methods.firstOrNull()) }
    val answers = remember { mutableStateMapOf<Int, String>() }
    val paid = t.entryFeeNowCents > 0
    // Una quota senza un modo per pagarla: lo dice il sito, e non si va avanti.
    val noWayToPay = paid && form.methods.isEmpty()

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).imePadding()
                .padding(horizontal = 24.dp).padding(bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(stringResource(R.string.register_title), style = MaterialTheme.typography.titleLarge)
            Text(t.name, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)

            OutlinedTextField(
                publisherId, { publisherId = it },
                label = { Text(stringResource(if (t.game == "mtg") R.string.register_wizards else R.string.register_player_id)) },
                supportingText = {
                    Text(stringResource(if (t.needsPublisherId) R.string.register_id_needed else R.string.register_optional))
                },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            if (t.isOnline) {
                OutlinedTextField(
                    handle, { handle = it },
                    label = { Text(stringResource(R.string.register_handle)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            form.fields.forEach { field -> FieldInput(field, answers[field.id].orEmpty()) { answers[field.id] = it } }

            if (paid) {
                OutlinedTextField(
                    discount, { discount = it.take(32) },
                    label = { Text(stringResource(R.string.register_discount)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    stringResource(R.string.register_fee, Formats.money(t.entryFeeNowCents, t.currency)),
                    style = MaterialTheme.typography.titleMedium,
                )
            }
            if (paid && form.methods.isNotEmpty()) {
                Text(stringResource(R.string.register_how_to_pay), style = MaterialTheme.typography.labelLarge)
                form.methods.forEach { option ->
                    Choice(methodLabel(option), selected = method == option) { method = option }
                }
            }
            if (noWayToPay) {
                Text(stringResource(R.string.register_no_payment), color = MaterialTheme.colorScheme.error)
            }
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

            val online = method == "stripe" || method == "paypal"
            SubmitButton(
                stringResource(if (paid && online) R.string.register_go_pay else R.string.register_confirm),
                busy,
                enabled = !noWayToPay,
            ) {
                onSubmit(
                    RegistrationIn(
                        wizardsAccount = publisherId.trim(),
                        discountCode = discount.trim(),
                        gameHandle = handle.trim(),
                        answers = form.fields.associate { field ->
                            field.id.toString() to if (field.kind == "checkbox") JsonPrimitive(answers[field.id] == "true")
                            else JsonPrimitive(answers[field.id].orEmpty().trim())
                        },
                        paymentMethod = if (paid) method else null,
                    )
                )
            }
        }
    }
}

@Composable
private fun FieldInput(field: RegistrationField, value: String, onChange: (String) -> Unit) {
    val label = if (field.required) field.label else "${field.label} ${stringResource(R.string.register_optional)}"
    when (field.kind) {
        "checkbox" -> Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(value == "true", { onChange(it.toString()) })
            Text(label, style = MaterialTheme.typography.bodyMedium)
        }
        "choice" -> Column {
            Text(label, style = MaterialTheme.typography.labelLarge)
            field.options.forEach { option -> Choice(option, selected = value == option) { onChange(option) } }
        }
        else -> OutlinedTextField(
            value, { onChange(it.take(1000)) },
            label = { Text(label) },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
fun Choice(text: String, selected: Boolean, onSelect: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().selectable(selected = selected, onClick = onSelect, role = Role.RadioButton).padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, onClick = null)
        Text(text, modifier = Modifier.padding(start = 12.dp), style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
private fun methodLabel(method: String): String = stringResource(
    when (method) {
        "stripe" -> R.string.pay_stripe
        "paypal" -> R.string.pay_paypal
        else -> R.string.pay_at_event
    }
)
