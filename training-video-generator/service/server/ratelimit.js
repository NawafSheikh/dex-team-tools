'use strict';

/** Sliding window limiter, in memory. `now` is injectable for tests. */
function createLimiter(max, windowMs, now = Date.now) {
  const hits = [];
  return {
    /** Returns {allowed, retryAfterSec}. Records a hit only when allowed. */
    take() {
      const t = now();
      while (hits.length && hits[0] <= t - windowMs) hits.shift();
      if (hits.length >= max) return { allowed: false, retryAfterSec: Math.ceil((hits[0] + windowMs - t) / 1000) };
      hits.push(t);
      return { allowed: true, retryAfterSec: 0 };
    },
  };
}

module.exports = { createLimiter };
