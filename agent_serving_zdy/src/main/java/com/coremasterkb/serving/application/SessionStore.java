package com.coremasterkb.serving.application;

import org.springframework.stereotype.Component;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;

/**
 * In-memory session store for multi-turn query context accumulation.
 *
 * <p>Each session holds up to {@value #MAX_TURNS} prior queries (FIFO eviction).
 * All operations are thread-safe. Store is process-local; sessions are lost on restart.</p>
 */
@Component
public class SessionStore {

    static final int MAX_TURNS = 10;

    private final ConcurrentHashMap<String, Deque<String>> sessions = new ConcurrentHashMap<>();

    /**
     * Returns a snapshot of prior queries for the session, oldest first.
     * Returns an empty list when the session does not exist.
     */
    public List<String> getPriorQueries(String sessionId) {
        Deque<String> turns = sessions.get(sessionId);
        if (turns == null || turns.isEmpty()) {
            return List.of();
        }
        return List.copyOf(turns);
    }

    /**
     * Records a new query turn in the session, evicting the oldest if over capacity.
     */
    public void recordTurn(String sessionId, String query) {
        sessions.compute(sessionId, (id, turns) -> {
            if (turns == null) turns = new ArrayDeque<>();
            turns.addLast(query);
            while (turns.size() > MAX_TURNS) turns.removeFirst();
            return turns;
        });
    }
}
