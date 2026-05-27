package com.coremasterkb.serving.observability;

import com.coremasterkb.serving.domain.ContextPack;
import com.coremasterkb.serving.domain.SearchRequest;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.UUID;

/**
 * Intercepts {@code SearchService.search()} to record query logs.
 * No business code is aware of this aspect.
 */
@Aspect
@Component
public class QueryLogAspect {

    private static final Logger log = LoggerFactory.getLogger(QueryLogAspect.class);

    private final QueryLogService queryLogService;

    public QueryLogAspect(QueryLogService queryLogService) {
        this.queryLogService = queryLogService;
    }

    @Around("execution(* com.coremasterkb.serving.application.SearchService.search(..))")
    public Object logSearch(ProceedingJoinPoint pjp) throws Throwable {
        long startMs = System.currentTimeMillis();
        String queryId = UUID.randomUUID().toString();
        SearchRequest request = (SearchRequest) pjp.getArgs()[0];

        log.info("[search] start id={} domain={} query=\"{}\"",
                queryId, request.domain(), abbreviate(request.query(), 60));

        ContextPack pack = null;
        Throwable thrown = null;
        try {
            Object result = pjp.proceed();
            if (result instanceof ContextPack cp) {
                pack = cp;
            }
            return result;
        } catch (Throwable t) {
            thrown = t;
            throw t;
        } finally {
            long durationMs = System.currentTimeMillis() - startMs;
            if (thrown != null) {
                log.warn("[search] error id={} domain={} duration={}ms error={}",
                        queryId, request.domain(), durationMs, thrown.getMessage());
            }
            queryLogService.record(queryId, request, pack, durationMs);
        }
    }

    private static String abbreviate(String s, int maxLen) {
        if (s == null) return "";
        return s.length() <= maxLen ? s : s.substring(0, maxLen) + "...";
    }
}
