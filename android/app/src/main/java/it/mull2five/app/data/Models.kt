package it.mull2five.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonPrimitive

/*
 * I dati come li dà l'API (backend/app/schemas.py), solo con i campi che l'app
 * usa: il resto lo ignora il parser. I nomi seguono gli schemi del server.
 */

/** TournamentOut. */
@Serializable
data class Tournament(
    val id: Int,
    val name: String,
    val format: String = "",
    val game: String = "mtg",
    @SerialName("best_of") val bestOf: Int = 3,
    @SerialName("allow_intentional_draws") val allowIntentionalDraws: Boolean = true,
    @SerialName("organizer_name") val organizerName: String? = null,
    @SerialName("organization_name") val organizationName: String? = null,
    @SerialName("organization_slug") val organizationSlug: String? = null,
    @SerialName("event_slug") val eventSlug: String? = null,
    @SerialName("event_name") val eventName: String? = null,
    @SerialName("season_id") val seasonId: Int? = null,
    @SerialName("rules_enforcement_level") val rel: String = "",
    @SerialName("distance_km") val distanceKm: Double? = null,
    @SerialName("pairings_public") val pairingsPublic: Boolean = true,
    @SerialName("standings_public") val standingsPublic: Boolean = true,
    @SerialName("decklists_public") val decklistsPublic: Boolean = false,
    @SerialName("event_type") val eventType: String = "locals",
    val venue: String = "",
    val city: String = "",
    val latitude: Double? = null,
    val longitude: Double? = null,
    @SerialName("starts_on") val startsOn: String,
    @SerialName("start_time") val startTime: String? = null,
    val capacity: Int = 0,
    @SerialName("entry_fee_cents") val entryFeeCents: Int = 0,
    @SerialName("entry_fee_now_cents") val entryFeeNowCents: Int = 0,
    @SerialName("early_bird_until") val earlyBirdUntil: String? = null,
    val currency: String = "EUR",
    val status: String = "published",
    val structure: String = "",
    @SerialName("swiss_rounds") val swissRounds: Int = 0,
    @SerialName("top_cut_size") val topCutSize: Int = 0,
    @SerialName("decklist_required") val decklistRequired: Boolean = false,
    @SerialName("decklist_locked") val decklistLocked: Boolean = false,
    @SerialName("decklist_formats") val decklistFormats: List<String> = listOf(""),
    @SerialName("check_in_required") val checkInRequired: Boolean = false,
    @SerialName("self_check_in_enabled") val selfCheckInEnabled: Boolean = false,
    @SerialName("registration_mode") val registrationMode: String = "open",
    @SerialName("refund_policy") val refundPolicy: String = "",
    val description: String = "",
    @SerialName("pay_at_event") val payAtEvent: Boolean = true,
    @SerialName("pay_stripe") val payStripe: Boolean = false,
    @SerialName("pay_paypal") val payPaypal: Boolean = false,
    @SerialName("registered_players") val registeredPlayers: Int = 0,
    val invites: Int = 0,
    val source: String = "",
    @SerialName("external_url") val externalUrl: String = "",
    @SerialName("is_online") val isOnline: Boolean = false,
    @SerialName("online_platform") val onlinePlatform: String = "",
    @SerialName("online_link") val onlineLink: String = "",
) {
    val place: String get() = listOf(venue, city).filter { it.isNotBlank() }.joinToString(", ")

    /** Lo sconto early bird è aperto: la quota piena va detta, o sembra il prezzo di sempre. */
    val earlyBirdOn: Boolean get() = earlyBirdUntil != null && entryFeeNowCents < entryFeeCents

    /** I tornei vetrina importati dal Locator di Wizards: ci si iscrive altrove. */
    val isShowcase: Boolean get() = source == "wizards"

    val isFull: Boolean get() = capacity in 1..registeredPlayers

    /** Negli eventi ufficiali l'ID Wizards serve: risultati e inviti arrivano lì. */
    val needsPublisherId: Boolean
        get() = eventType in setOf("rcq", "store_championship", "premier") || invites > 0

    /** I modi di pagare che il torneo accetta (event.js, paymentMethods). */
    fun paymentMethods(onlineEnabled: Boolean): List<String> = buildList {
        if (payAtEvent) add("at_event")
        if (onlineEnabled && payStripe) add("stripe")
        if (onlineEnabled && payPaypal) add("paypal")
    }
}

/** UserOut. */
@Serializable
data class User(
    val id: Int,
    val email: String,
    @SerialName("display_name") val displayName: String,
    val role: String = "player",
    @SerialName("public_id") val publicId: String = "",
)

/** RegistrationOut. */
@Serializable
data class Registration(
    val id: Int,
    @SerialName("tournament_id") val tournamentId: Int,
    @SerialName("wizards_account") val wizardsAccount: String = "",
    @SerialName("checked_in") val checkedIn: Boolean = false,
    val dropped: Boolean = false,
    val waitlisted: Boolean = false,
    @SerialName("decklist_status") val decklistStatus: String = "missing",
    @SerialName("payment_status") val paymentStatus: String = "pending",
    @SerialName("amount_due_cents") val amountDueCents: Int = 0,
    @SerialName("discount_code") val discountCode: String = "",
    @SerialName("fixed_table") val fixedTable: Int? = null,
    @SerialName("team_name") val teamName: String? = null,
    @SerialName("game_handle") val gameHandle: String = "",
    @SerialName("online_link") val onlineLink: String = "",
    @SerialName("payment_due_by") val paymentDueBy: String? = null,
    @SerialName("checkout_url") val checkoutUrl: String = "",
) {
    val isPaid: Boolean get() = paymentStatus == "paid" || paymentStatus == "confirmed"
}

/** MyRegistrationOut: un'iscrizione con il suo torneo. */
@Serializable
data class MyRegistration(val tournament: Tournament, val registration: Registration)

/** PairingOut. */
@Serializable
data class Pairing(
    val id: Int,
    @SerialName("table_number") val tableNumber: Int = 0,
    @SerialName("player_a") val playerA: String,
    @SerialName("player_a_registration_id") val playerARegistrationId: Int,
    @SerialName("player_b") val playerB: String? = null,
    @SerialName("player_b_registration_id") val playerBRegistrationId: Int? = null,
    val result: String = "",
    @SerialName("report_status") val reportStatus: String = "",
    @SerialName("report_score") val reportScore: String = "",
    @SerialName("report_reporter_registration_id") val reportReporterRegistrationId: Int? = null,
    @SerialName("player_a_handle") val playerAHandle: String = "",
    @SerialName("player_b_handle") val playerBHandle: String = "",
)

/** RoundOut. */
@Serializable
data class Round(
    val id: Int,
    val number: Int,
    val phase: String = "swiss",
    @SerialName("is_published") val isPublished: Boolean = true,
    @SerialName("ends_at") val endsAt: String? = null,
    val pairings: List<Pairing> = emptyList(),
)

/** StandingOut. */
@Serializable
data class Standing(
    val position: Int,
    @SerialName("registration_id") val registrationId: Int,
    val name: String,
    val dropped: Boolean = false,
    val points: Int = 0,
    val record: String = "",
)

/** RegistrationFieldOut: le domande in più che l'organizzatore mette al torneo. */
@Serializable
data class RegistrationField(
    val id: Int,
    val label: String,
    val kind: String = "text",
    val options: List<String> = emptyList(),
    val required: Boolean = false,
)

/** SavedDeckOut: le liste salvate nel profilo. */
@Serializable
data class SavedDeck(
    val id: Int,
    val name: String,
    val game: String = "mtg",
    val format: String = "",
    val archetype: String = "",
    @SerialName("raw_text") val rawText: String = "",
    @SerialName("main_count") val mainCount: Int = 0,
    @SerialName("side_count") val sideCount: Int = 0,
    /** Le regole del formato non rispettate (numero di carte, copie): vuoto, è a posto. */
    val errors: List<String> = emptyList(),
)

@Serializable
data class Payment(@SerialName("checkout_url") val checkoutUrl: String = "")

@Serializable
data class PaymentOptions(val online: Boolean = false)

@Serializable
data class AuthRules(
    @SerialName("min_account_age") val minAccountAge: Int = 14,
    @SerialName("google_login") val googleLogin: Boolean = false,
)

@Serializable
data class TokenOut(@SerialName("access_token") val accessToken: String)

/** GoogleFinishOut: il token, o i dati per completare la registrazione. */
@Serializable
data class GoogleFinish(
    @SerialName("access_token") val accessToken: String? = null,
    @SerialName("linked_existing") val linkedExisting: Boolean = false,
    @SerialName("signup_email") val signupEmail: String? = null,
    @SerialName("signup_name") val signupName: String? = null,
)

// ── Quello che l'app manda ────────────────────────────────────────────────

@Serializable
data class LoginIn(val email: String, val password: String)

@Serializable
data class SignupIn(
    val email: String,
    @SerialName("display_name") val displayName: String,
    val password: String,
    @SerialName("age_confirmed") val ageConfirmed: Boolean,
    @SerialName("terms_accepted") val termsAccepted: Boolean,
)

@Serializable
data class EmailIn(val email: String)

@Serializable
data class GoogleCodeIn(val code: String, val verifier: String)

@Serializable
data class GoogleSignupIn(
    val code: String,
    val verifier: String,
    @SerialName("display_name") val displayName: String,
    @SerialName("age_confirmed") val ageConfirmed: Boolean,
    @SerialName("terms_accepted") val termsAccepted: Boolean,
)

/** RegistrationCreate. */
@Serializable
data class RegistrationIn(
    @SerialName("wizards_account") val wizardsAccount: String = "",
    @SerialName("discount_code") val discountCode: String = "",
    @SerialName("game_handle") val gameHandle: String = "",
    val answers: Map<String, JsonPrimitive> = emptyMap(),
    @SerialName("payment_method") val paymentMethod: String? = null,
)

/** PairingResultIn: i game vinti da A e da B, come li vede il pairing. */
@Serializable
data class ResultIn(
    @SerialName("match_wins_a") val matchWinsA: Int,
    @SerialName("match_wins_b") val matchWinsB: Int,
    val draws: Int = 0,
)

@Serializable
data class RejectIn(val note: String = "")

@Serializable
data class CheckoutIn(val provider: String)

/** DecklistCreate. */
@Serializable
data class DecklistIn(
    @SerialName("raw_text") val rawText: String,
    val archetype: String = "",
    val format: String = "",
)
