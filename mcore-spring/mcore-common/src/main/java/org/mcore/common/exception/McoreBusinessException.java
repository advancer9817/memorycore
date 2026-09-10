package org.mcore.common.exception;

import org.mcore.common.result.ErrorCode;

public class McoreBusinessException extends RuntimeException {
    private static final long serialVersionUID = 1L;

    private final String code;

    public McoreBusinessException(ErrorCode errorCode) {
        super(errorCode.getMessage());
        this.code = errorCode.getCode();
    }

    public McoreBusinessException(String code, String message) {
        super(message);
        this.code = code;
    }

    public String getCode() { return code; }
}
