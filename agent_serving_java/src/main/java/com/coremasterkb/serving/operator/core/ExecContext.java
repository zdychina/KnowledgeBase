package com.coremasterkb.serving.operator.core;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Per-execution shared context. Operators are stateless singletons; all mutable request state
 * lives here so operator instances stay thread-safe and cacheable.
 *
 * <p>{@code attributes} carries cross-operator helper data (e.g. {@code releaseId}, {@code buildId}
 * stuffed by {@code scope_resolve}). {@code nodeTraces} accumulates per-node timing when
 * {@code debug} is on.</p>
 */
public final class ExecContext {

    /** A single node's execution trace entry. */
    public record NodeTrace(String nodeId, String operatorType, long durationMs, String summary) {}

    private final String requestId;
    private final String domain;
    private final String channel;
    private final boolean debug;
    private volatile String query;
    private final Map<String, Object> attributes = new ConcurrentHashMap<>();
    private final List<NodeTrace> nodeTraces = new CopyOnWriteArrayList<>();

    public ExecContext(String requestId, String domain, String channel, boolean debug) {
        this.requestId = requestId;
        this.domain = domain;
        this.channel = channel;
        this.debug = debug;
    }

    /** The request query, available to entry operators (e.g. request_input). */
    public String query() { return query; }
    public void setQuery(String query) { this.query = query; }

    public String requestId() { return requestId; }
    public String domain()    { return domain; }
    public String channel()   { return channel; }
    public boolean debug()    { return debug; }

    public Map<String, Object> attributes() { return attributes; }

    public void putAttribute(String key, Object value) {
        if (value != null) attributes.put(key, value);
    }

    public List<NodeTrace> nodeTraces() { return nodeTraces; }

    public void addNodeTrace(NodeTrace trace) {
        nodeTraces.add(trace);
    }
}
