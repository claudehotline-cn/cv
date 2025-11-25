package com.cv.cp.controller;

public class CpResponse<T> {

  private String code;
  private String msg;
  private T data;

  public CpResponse() {
  }

  public CpResponse(String code, String msg, T data) {
    this.code = code;
    this.msg = msg;
    this.data = data;
  }

  public static <T> CpResponse<T> ok(T data) {
    return new CpResponse<>("OK", null, data);
  }

  public static <T> CpResponse<T> accepted(T data) {
    return new CpResponse<>("ACCEPTED", null, data);
  }

  public static <T> CpResponse<T> invalidArgument(String message) {
    return new CpResponse<>("INVALID_ARGUMENT", message, null);
  }

  public String getCode() {
    return code;
  }

  public void setCode(String code) {
    this.code = code;
  }

  public String getMsg() {
    return msg;
  }

  public void setMsg(String msg) {
    this.msg = msg;
  }

  public T getData() {
    return data;
  }

  public void setData(T data) {
    this.data = data;
  }
}

