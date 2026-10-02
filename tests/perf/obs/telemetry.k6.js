// E04-Q01 E04-TC-T06: frontend telemetry endpoint at expected session load.
// One push / 10 s / session; above that the endpoint must answer 429, never 5xx.
// k6 run -e BASE_URL=... -e TOKEN=<test session token> telemetry.k6.js
import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  scenarios: {
    sessions: { executor: "constant-vus", vus: 20, duration: "2m" },
  },
  thresholds: { http_req_failed: ["rate<0.01"], http_req_duration: ["p(95)<150"] },
};

const body = JSON.stringify({
  screen: "R-100",
  engine_version: "0.1.0",
  fe_frame_time_ms: { counts: [1, 0, 0, 0, 0, 0, 0, 0, 0] },
  fe_ws_decode_ms: { counts: [1, 0, 0, 0, 0, 0, 0, 0, 0] },
  fe_dropped_frames_total: 0,
  fe_gpu_memory_mb: 1.0,
});

export default function () {
  const res = http.post(`${__ENV.BASE_URL}/telemetry/frontend`, body, {
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${__ENV.TOKEN}` },
  });
  check(res, { "204 or 429": (r) => r.status === 204 || r.status === 429 });
  sleep(10);
}
