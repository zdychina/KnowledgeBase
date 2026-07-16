package com.coremasterkb.serving.operator.core.exceptions;

/** Base unchecked exception for the operator subsystem. */
public class OperatorException extends RuntimeException {
    public OperatorException(String message) {
        super(message);
    }

    public OperatorException(String message, Throwable cause) {
        super(message, cause);
    }
}
