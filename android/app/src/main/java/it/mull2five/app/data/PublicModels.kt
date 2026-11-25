package it.mull2five.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Il lato pubblico (backend/app/schemas.py): negozi, circuiti, manifestazioni,
 * l'archivio delle liste, i risultati di un torneo e il profilo di un giocatore.
 */

/** Un gioco di /games, con i formati che si possono scegliere. */
@Serializable
data class Game(
    val code: String,
    val name: String,
    val formats: List<String> = emptyList(),
    @SerialName("limited_formats") val limitedFormats: List<String> = emptyList(),
)

/** OrganizationOut: un negozio. */
@Serializable
data class Store(
    val id: Int,
    val slug: String,
    val name: String,
    val description: String = "",
    val city: String = "",
    val address: String = "",
    val website: String = "",
    val latitude: Double? = null,
    val longitude: Double? = null,
    @SerialName("is_premium") val isPremium: Boolean = false,
    @SerialName("upcoming_count") val upcomingCount: Int = 0,
    @SerialName("past_count") val pastCount: Int = 0,
    @SerialName("distance_km") val distanceKm: Double? = null,
)

/** LocationOut: una sede del negozio. */
@Serializable
data class StoreLocation(
    val id: Int,
    val name: String,
    val address: String = "",
    val city: String = "",
    val latitude: Double? = null,
    val longitude: Double? = null,
    val notes: String = "",
)

/** StoreProfileOut: la pagina del negozio. */
@Serializable
data class StorePage(
    val organization: Store,
    val locations: List<StoreLocation> = emptyList(),
    val upcoming: List<Tournament> = emptyList(),
    val past: List<Tournament> = emptyList(),
)

/** SeasonOut: un circuito, con le sue regole di punteggio. */
@Serializable
data class Circuit(
    val id: Int,
    val name: String,
    val slug: String? = null,
    val description: String = "",
    @SerialName("starts_on") val startsOn: String? = null,
    @SerialName("ends_on") val endsOn: String? = null,
    @SerialName("points_win") val pointsWin: Int = 3,
    @SerialName("points_draw") val pointsDraw: Int = 1,
    @SerialName("points_participation") val pointsParticipation: Int = 0,
    @SerialName("points_champion_bonus") val pointsChampionBonus: Int = 0,
    @SerialName("points_undefeated_bonus") val pointsUndefeatedBonus: Int = 0,
    @SerialName("drop_worst_scores") val dropWorstScores: Int = 0,
    @SerialName("drop_above_tournaments") val dropAboveTournaments: Int = 0,
    @SerialName("qualification_threshold") val qualificationThreshold: Int? = null,
    @SerialName("is_active") val isActive: Boolean = true,
    @SerialName("tournament_count") val tournamentCount: Int = 0,
)

/** LeaderboardRowOut. */
@Serializable
data class LeaderboardRow(
    val position: Int,
    @SerialName("player_name") val playerName: String,
    val points: Int = 0,
    val wins: Int = 0,
    val draws: Int = 0,
    val losses: Int = 0,
    @SerialName("tournaments_played") val tournamentsPlayed: Int = 0,
    val titles: Int = 0,
    val undefeated: Int = 0,
    val discarded: Int = 0,
)

/** SeriesPublicOut: la pagina del circuito. */
@Serializable
data class CircuitPage(
    val season: Circuit,
    val tournaments: List<Tournament> = emptyList(),
    val leaderboard: List<LeaderboardRow> = emptyList(),
)

/** EventOut: una manifestazione, con più tornei in uno o più giorni. */
@Serializable
data class Manifestation(
    val id: Int,
    val slug: String,
    val name: String,
    val description: String = "",
    val venue: String = "",
    val city: String = "",
    @SerialName("starts_on") val startsOn: String,
    @SerialName("ends_on") val endsOn: String? = null,
)

/** EventPublicOut. */
@Serializable
data class ManifestationPage(val event: Manifestation, val tournaments: List<Tournament> = emptyList())

/** ArchiveDeckOut / ArchiveDeckDetailOut: una lista dell'archivio pubblico. */
@Serializable
data class ArchiveDeck(
    @SerialName("decklist_id") val decklistId: Int,
    @SerialName("tournament_id") val tournamentId: Int,
    @SerialName("tournament_name") val tournamentName: String,
    @SerialName("starts_on") val startsOn: String,
    @SerialName("store_name") val storeName: String? = null,
    val format: String = "",
    val position: Int = 0,
    val players: Int = 0,
    @SerialName("player_name") val playerName: String = "",
    val archetype: String = "",
    val record: String = "",
    val points: Int = 0,
    @SerialName("main_count") val mainCount: Int = 0,
    @SerialName("side_count") val sideCount: Int = 0,
    @SerialName("raw_text") val rawText: String = "",
)

/** ArchivePageOut. */
@Serializable
data class ArchivePage(
    val total: Int = 0,
    val page: Int = 1,
    @SerialName("per_page") val perPage: Int = 25,
    val items: List<ArchiveDeck> = emptyList(),
)

@Serializable
data class ArchetypeShare(
    val archetype: String,
    val lists: Int = 0,
    val share: Double = 0.0,
    val top8: Int = 0,
    val wins: Int = 0,
)

@Serializable
data class CardShare(val name: String, val lists: Int = 0, val share: Double = 0.0, val copies: Double = 0.0)

/** ArchiveMetaOut: il metagame dell'archivio. */
@Serializable
data class ArchiveMeta(
    @SerialName("total_lists") val totalLists: Int = 0,
    val archetypes: List<ArchetypeShare> = emptyList(),
    @SerialName("top_cards") val topCards: List<CardShare> = emptyList(),
)

/** PublicStandingRow: la classifica finale, con la lista se è pubblica. */
@Serializable
data class PublicStanding(
    val position: Int,
    val name: String,
    val points: Int = 0,
    val record: String = "",
    val archetype: String = "",
    val decklist: String? = null,
)

/** PublicResultsOut. */
@Serializable
data class PublicResults(
    val name: String,
    val format: String = "",
    @SerialName("starts_on") val startsOn: String,
    val status: String = "",
    @SerialName("standings_public") val standingsPublic: Boolean = false,
    @SerialName("decklists_public") val decklistsPublic: Boolean = false,
    val standings: List<PublicStanding> = emptyList(),
)

/** MetaStatRow: un archetipo nel torneo. */
@Serializable
data class MetaRow(
    val archetype: String,
    val players: Int = 0,
    val wins: Int = 0,
    val draws: Int = 0,
    val losses: Int = 0,
    @SerialName("win_rate") val winRate: Double = 0.0,
)

/** BracketMatchOut: un match del taglio. */
@Serializable
data class BracketMatch(
    @SerialName("pairing_id") val pairingId: Int,
    @SerialName("round_number") val roundNumber: Int,
    @SerialName("table_number") val tableNumber: Int = 0,
    @SerialName("player_a") val playerA: String,
    @SerialName("player_b") val playerB: String? = null,
    @SerialName("match_wins_a") val matchWinsA: Int = 0,
    @SerialName("match_wins_b") val matchWinsB: Int = 0,
    val winner: String? = null,
)

/** PlayerHistoryRowOut: un torneo giocato. */
@Serializable
data class HistoryRow(
    @SerialName("tournament_id") val tournamentId: Int,
    @SerialName("tournament_name") val tournamentName: String,
    @SerialName("starts_on") val startsOn: String,
    val format: String = "",
    val status: String = "",
    val placement: Int? = null,
    val record: String = "",
    val points: Int = 0,
    @SerialName("event_type") val eventType: String = "locals",
    val invited: Boolean = false,
)

/** PlayerBreakdownRow: il record in un formato o con un archetipo. */
@Serializable
data class Breakdown(
    val label: String,
    val tournaments: Int = 0,
    val wins: Int = 0,
    val draws: Int = 0,
    val losses: Int = 0,
    @SerialName("win_rate") val winRate: Double = 0.0,
)

/** PlayerPublicProfileOut: il profilo pubblico (player.html). */
@Serializable
data class PlayerProfile(
    @SerialName("display_name") val displayName: String,
    @SerialName("public_id") val publicId: String = "",
    @SerialName("tournaments_played") val tournamentsPlayed: Int = 0,
    @SerialName("total_points") val totalPoints: Int = 0,
    val wins: Int = 0,
    val draws: Int = 0,
    val losses: Int = 0,
    val rows: List<HistoryRow> = emptyList(),
    @SerialName("by_format") val byFormat: List<Breakdown> = emptyList(),
    @SerialName("by_archetype") val byArchetype: List<Breakdown> = emptyList(),
)
