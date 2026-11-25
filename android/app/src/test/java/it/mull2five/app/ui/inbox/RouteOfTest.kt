package it.mull2five.app.ui.inbox

import it.mull2five.app.ui.Routes
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Gli indirizzi li scrive services/inbox.py: event_url, live_url, TICKETS_URL. */
class RouteOfTest {
    @Test
    fun `i percorsi del sito diventano schermate dell'app`() {
        assertEquals(Routes.event(12), routeOf("/event.html?id=12"))
        assertEquals(Routes.myTournament(7), routeOf("/my-registrations.html?t=7"))
        assertEquals(Routes.MINE, routeOf("/my-registrations.html"))
        assertEquals(Routes.TICKETS, routeOf("/tickets.html"))
    }

    @Test
    fun `il resto resta sulla campanella`() {
        assertNull(routeOf(""))
        assertNull(routeOf("/event.html"))
        assertNull(routeOf("/event.html?id=abc"))
        assertNull(routeOf("/altro.html?id=1"))
        assertNull(routeOf("https://altro.sito/event.html?id=1"))
        assertNull(routeOf("//altro.sito/event.html?id=1"))
    }
}
