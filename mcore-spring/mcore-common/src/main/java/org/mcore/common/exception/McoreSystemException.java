package org.mcore.common.exception;

import org.mcore.common.result.ErrorCode;

public class McoreSystemException extends RuntimeException {
    private static final long serialVersionUID = 1L;

    private final String code;

    public McoreSystemException(ErrorCode errorCode, Throwable cause) {
        super(errorCode.getMessage(), cause);
        this.code = errorCode.getCode();
    }

    public McoreSystemException(String code, String message, Throwable cause) {
        super(message, cause);
        this.code = code;
    }

    public String getCode() { return code; }
}
