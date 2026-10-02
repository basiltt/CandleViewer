// E04-Q01 E04-TC-M04: /metrics scrape latency at full declared cardinality (budget: p95 < 50 ms).
// Run against staging only: k6 run -e BASE_URL=http://127.0.0.1:8000 metrics_scrape.k6.js
import http from "k6/http";
import { check } from "k6";

export const options = {
  vus: 1,
  duration: "2m",
  thresholds: { http_req_duration: ["p(95)<50"], checks: ["rate==1"] },
};

export default function () {
  const res = http.get(`${__ENV.BASE_URL}/metrics`);
  check(res, { "200": (r) => r.status === 200, "has body": (r) => r.body.length > 0 });
}
