'use strict';

/** An error that maps to an HTTP status and a machine readable code. */
class ApiError extends Error {
  constructor(status, code, message, extra) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.extra = extra || {};
  }
}

module.exports = { ApiError };
