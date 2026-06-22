package com.coremasterkb.serving.operator.core.exceptions;

/** Thrown when a slot value does not match its declared {@code SlotType} (runtime binding check). */
public class SlotTypeMismatchException extends OperatorException {
    public SlotTypeMismatchException(String message) {
        super(message);
    }
}
