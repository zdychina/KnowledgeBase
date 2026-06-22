package com.coremasterkb.serving.operator.core.exceptions;

import com.coremasterkb.serving.operator.engine.CompileError;

import java.util.List;

/** Thrown when a paradigm fails compile-time validation; carries the full structured error list. */
public class ParadigmCompileException extends OperatorException {

    private final transient List<CompileError> errors;

    public ParadigmCompileException(List<CompileError> errors) {
        super("paradigm_compile_failed: " + errors.size() + " error(s)");
        this.errors = errors != null ? List.copyOf(errors) : List.of();
    }

    public List<CompileError> errors() {
        return errors;
    }
}
