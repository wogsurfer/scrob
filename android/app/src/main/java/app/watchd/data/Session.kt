package app.watchd.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.store by preferencesDataStore("session")

/** Where Watchd is and the token the app signed in with, kept on the phone. */
data class Session(val server: String, val token: String?)

class SessionStore(private val context: Context) {
    private val serverKey = stringPreferencesKey("server")
    private val tokenKey = stringPreferencesKey("token")

    val session: Flow<Session> = context.store.data.map {
        Session(it[serverKey] ?: DEFAULT_SERVER, it[tokenKey])
    }

    suspend fun signIn(server: String, token: String) {
        context.store.edit {
            it[serverKey] = server
            it[tokenKey] = token
        }
    }

    suspend fun signOut() {
        context.store.edit { it.remove(tokenKey) }
    }

    companion object {
        /** The PC running Watchd, by its Tailscale name: works at home and away. */
        const val DEFAULT_SERVER = "http://your-server:7330"
    }
}
