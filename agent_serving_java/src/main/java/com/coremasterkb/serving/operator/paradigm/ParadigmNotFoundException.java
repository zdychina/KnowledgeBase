package com.coremasterkb.serving.operator.paradigm;

import com.coremasterkb.serving.operator.core.exceptions.OperatorException;

/** Thrown when a paradigm id, or a requested paradigm version, does not exist (mapped to 404). */
public class ParadigmNotFoundException extends OperatorException {
    public ParadigmNotFoundException(String message) {
        super(message);
    }
}
