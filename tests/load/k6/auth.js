// E09-Q05 auth perf profile. Run against STAGING on recorded fixtures only (C-13.5):
//   k6 run -e BASE_URL=http://127.0.0.1:8000 -e CV_PERF_USER=... tests/load/k6/auth.js
// Credentials come from the environment (never committed). CV_CACHE_DISABLED=1 is the
// negative control: the session_bootstrap budget MUST then fail.
import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const J = { headers: { 'Content-Type': 'application/json' } };
const argon2Ms = new Trend('auth_argon2_step_ms', true);
const restMs = new Trend('auth_login_rest_ms', true);
const coldMs = new Trend('session_cold_ms', true);

export const options = {
  scenarios: {
    login_burst: { executor: 'constant-vus', vus: 5, duration: '30s', exec: 'loginBurst' },
    session_bootstrap: { executor: 'constant-arrival-rate', rate: 50, timeUnit: '1s',
      duration: '60s', preAllocatedVUs: 20, exec: 'sessionBootstrap', startTime: '35s' },
    stepup_burst: { executor: 'constant-vus', vus: 10, duration: '30s', exec: 'stepUp', startTime: '35s' },
    mfa_verify: { executor: 'constant-vus', vus: 10, duration: '30s', exec: 'mfaVerify', startTime: '35s' },
  },
  thresholds: {
    'http_req_duration{scenario:session_bootstrap}': ['p(95)<=100'], // warm cache, #13
    'http_req_duration{scenario:stepup_burst}': ['p(95)<=400'], // SCR-006
    'http_req_duration{scenario:mfa_verify}': ['p(95)<=400'], // SCR-002
    auth_argon2_step_ms: ['p(50)>=100'], // SR-011: cost must not be optimised away
  },
};

function login() {
  const r = http.post(`${BASE}/auth/login`, JSON.stringify({
    username: __ENV.CV_PERF_USER, password: __ENV.CV_PERF_PASSWORD }), J);
  // Server-Timing: argon2;dur=<ms> separates the hashing step from the rest.
  const m = /argon2;dur=([\d.]+)/.exec(r.headers['Server-Timing'] || '');
  if (m) { argon2Ms.add(parseFloat(m[1])); restMs.add(r.timings.duration - parseFloat(m[1])); }
  return r;
}

export function setup() {
  const argon = http.get(`${BASE}/auth/_perf/argon2-params`).json() || {};
  // Acceptance: fail the run if params are below m=64MiB, t=3, p=4.
  if (!(argon.m >= 65536 && argon.t >= 3 && argon.p >= 4)) {
    throw new Error(`Argon2id params below floor: ${JSON.stringify(argon)}`);
  }
  const r = login();
  return { token: r.json('access_token') };
}

export function loginBurst() {
  check(login(), { 'login ok': (r) => r.status === 200 || r.status === 202 });
}

export function sessionBootstrap(d) {
  const r = http.get(`${BASE}/auth/session`, { headers: { Authorization: `Bearer ${d.token}` },
    tags: { cache: __ENV.CV_CACHE_DISABLED ? 'off' : 'warm' } });
  check(r, { 'session 200': (x) => x.status === 200 });
}

export function stepUp(d) {
  http.post(`${BASE}/auth/step-up`, JSON.stringify({ password: __ENV.CV_PERF_PASSWORD }),
    { headers: { ...J.headers, Authorization: `Bearer ${d.token}` } });
}

export function mfaVerify(d) {
  http.post(`${BASE}/auth/mfa/verify`, JSON.stringify({ code: __ENV.CV_PERF_TOTP || '000000' }),
    { headers: { ...J.headers, Authorization: `Bearer ${d.token}` } });
}
