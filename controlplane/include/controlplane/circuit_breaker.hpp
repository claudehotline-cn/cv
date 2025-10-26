#pragma once
#include <string>

namespace controlplane::cb {

// Simple per-service (va/vsm) circuit breaker
// - Open after N consecutive failures
// - Stay open for cool_ms, then half-open with one trial
// - On success, close; on failure, reopen

bool allow(const std::string& service);      // check if request is allowed
void on_success(const std::string& service); // record success
void on_failure(const std::string& service); // record failure
bool is_open(const std::string& service);    // current open state

}

