package com.coremasterkb.serving.api;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.Map;

/**
 * Centralized exception handling for the serving layer.
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /**
     * Handle known domain errors from the asset repository scope resolution.
     *
     * no_active_release        → 503 (service temporarily unavailable — no content to serve)
     * multiple_active_releases → 500 (configuration error — ambiguous state)
     * all other IAE            → 400 (bad request)
     */
    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, Object>> handleIllegalArgument(IllegalArgumentException ex) {
        String msg = ex.getMessage();
        if (msg == null) msg = "bad_request";

        switch (msg) {
            case "no_active_release" -> {
                log.warn("No active release found; returning 503");
                return ResponseEntity
                        .status(HttpStatus.SERVICE_UNAVAILABLE)
                        .body(errorBody("no_active_release",
                                "No active release is currently available. The service is not ready."));
            }
            case "multiple_active_releases" -> {
                log.error("Multiple active releases found; returning 500");
                return ResponseEntity
                        .status(HttpStatus.INTERNAL_SERVER_ERROR)
                        .body(errorBody("multiple_active_releases",
                                "Multiple active releases found — data configuration error."));
            }
            default -> {
                log.warn("Bad request: {}", msg);
                return ResponseEntity
                        .status(HttpStatus.BAD_REQUEST)
                        .body(errorBody("bad_request", msg));
            }
        }
    }

    /**
     * Catch-all for unexpected errors.
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handleGeneric(Exception ex) {
        log.error("Unexpected error", ex);
        return ResponseEntity
                .status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(errorBody("internal_error",
                        "An unexpected error occurred. Please try again later."));
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private Map<String, Object> errorBody(String code, String message) {
        return Map.of(
                "error", code,
                "message", message
        );
    }
}
