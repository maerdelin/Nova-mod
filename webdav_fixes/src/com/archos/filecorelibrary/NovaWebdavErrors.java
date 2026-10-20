package com.archos.filecorelibrary;
import java.io.IOException;
import java.util.concurrent.CancellationException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
/** Exception classification only; never reads or opens a stream. */
public final class NovaWebdavErrors {
    private NovaWebdavErrors() { }
    public static final class RequestCancelledException extends IOException {
        public RequestCancelledException(String message, Throwable cause) { super(message, cause); }
    }
    private static final Pattern ACCESS_STATUS = Pattern.compile(
        "(?i)\\bHTTP(?:\\s+error)?\\s*[:=]?\\s*(401|403)\\b|\\b(401)\\s+Unauthorized\\b|\\b(403)\\s+Forbidden\\b");
    public static int failureDisposition(Throwable error) {
        if (Thread.currentThread().isInterrupted()) return 1;
        boolean denied = false;
        for (int depth = 0; error != null && depth < 16; depth++, error = error.getCause()) {
            if (error instanceof RequestCancelledException || error instanceof InterruptedException
                    || error instanceof CancellationException) return 1;
            denied |= accessStatus(error) != 0;
            if (error.getCause() == error) break;
        }
        return denied ? 2 : 0;
    }
    static int accessStatus(Throwable error) {
        try {
            Object status = error.getClass().getMethod("getStatusCode").invoke(error);
            if (status instanceof Number) {
                int code = ((Number) status).intValue(); if (code == 401 || code == 403) return code;
            }
        } catch (ReflectiveOperationException | SecurityException ignored) { }
        String message = error.getMessage();
        if (message != null) {
            Matcher m = ACCESS_STATUS.matcher(message);
            if (m.find()) for (int i = 1; i <= 3; i++)
                if (m.group(i) != null) return Integer.parseInt(m.group(i));
        }
        return 0;
    }
}
