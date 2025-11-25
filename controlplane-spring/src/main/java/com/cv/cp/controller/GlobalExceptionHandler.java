package com.cv.cp.controller;

import io.grpc.Status;
import io.grpc.StatusRuntimeException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

  private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

  @ExceptionHandler(StatusRuntimeException.class)
  public ResponseEntity<CpResponse<Void>> handleStatusRuntimeException(StatusRuntimeException ex) {
    Status status = ex.getStatus();
    HttpStatus httpStatus;
    switch (status.getCode()) {
      case INVALID_ARGUMENT:
        httpStatus = HttpStatus.BAD_REQUEST;
        break;
      case NOT_FOUND:
        httpStatus = HttpStatus.NOT_FOUND;
        break;
      case ALREADY_EXISTS:
        httpStatus = HttpStatus.CONFLICT;
        break;
      case UNAVAILABLE:
        httpStatus = HttpStatus.SERVICE_UNAVAILABLE;
        break;
      default:
        httpStatus = HttpStatus.INTERNAL_SERVER_ERROR;
        break;
    }
    CpResponse<Void> body = new CpResponse<>();
    body.setCode(status.getCode().name());
    body.setMsg(status.getDescription());
    body.setData(null);
    log.warn("gRPC StatusRuntimeException mapped to HTTP {}: {}", httpStatus, status, ex);
    return ResponseEntity.status(httpStatus).body(body);
  }

  @ExceptionHandler(Exception.class)
  public ResponseEntity<CpResponse<Void>> handleGenericException(Exception ex) {
    log.error("Unhandled exception in controller", ex);
    CpResponse<Void> body = new CpResponse<>();
    body.setCode("INTERNAL");
    body.setMsg(ex.getMessage());
    body.setData(null);
    return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(body);
  }
}

