package com.coremasterkb.serving.observability;

import com.coremasterkb.serving.domain.ContextPack;
import com.coremasterkb.serving.domain.SearchRequest;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.stereotype.Component;

import java.util.UUID;

/**
 * Intercepts {@code SearchService.search()} to record query logs.
 * No business code is aware of this aspect.
 */
@Aspect
@Component
public class QueryLogAspect {

    private final QueryLogService queryLogService;

    public QueryLogAspect(QueryLogService queryLogService) {
        this.queryLogService = queryLogService;
    }

    @Around("execution(* com.coremasterkb.serving.application.SearchService.search(..))")
    public Object logSearch(ProceedingJoinPoint pjp) throws Throwable {
        long startMs = System.currentTimeMillis();
        String queryId = UUID.randomUUID().toString();
        SearchRequest request = (SearchRequest) pjp.getArgs()[0];

        ContextPack pack = null;
        try {
            Object result = pjp.proceed();
            if (result instanceof ContextPack cp) {
                pack = cp;
            }
            return result;
        } finally {
            queryLogService.record(queryId, request, pack, System.currentTimeMillis() - startMs);
        }
    }
}
