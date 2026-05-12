package com.coremasterkb.serving.api;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.Map;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, Object>> handleIllegalArgument(IllegalArgumentException ex) {
        if ("no_active_release".equals(ex.getMessage())) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body(Map.of("error", "no_active_release", "message", "No active release found for the requested domain"));
        }
        if ("multiple_active_releases".equals(ex.getMessage())) {
            return ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("error", "multiple_active_releases", "message", "Multiple active releases found"));
        }
        log.warn("Bad request: {}", ex.getMessage());
        return ResponseEntity.badRequest()
                .body(Map.of("error", "bad_request", "message", ex.getMessage()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handleGeneric(Exception ex) {
        log.error("Unhandled exception", ex);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(Map.of("error", "internal_error", "message", "Internal server error"));
    }
}
