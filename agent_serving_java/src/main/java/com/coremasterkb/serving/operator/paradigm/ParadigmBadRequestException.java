package com.coremasterkb.serving.operator.paradigm;

import com.coremasterkb.serving.operator.core.exceptions.OperatorException;

/** Client error in a paradigm management request (e.g. blank name, duplicate name); mapped to 400. */
public class ParadigmBadRequestException extends OperatorException {
    public ParadigmBadRequestException(String message) {
        super(message);
    }
}
