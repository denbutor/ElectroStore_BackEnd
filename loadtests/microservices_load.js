import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.TARGET_URL || "http://localhost:8000";
const PROFILE = (__ENV.PROFILE || "smoke").toLowerCase();
const CATEGORIES_PATH = __ENV.CATEGORIES_PATH || "/api/v1/categories";
const PRODUCTS_PATH = __ENV.PRODUCTS_PATH || "/api/v1/products";

const apiErrorRate = new Rate("api_error_rate");
const catalogLatency = new Trend("catalog_latency", true);

const PROFILES = {
  smoke: {
    vus: 2,
    duration: "20s",
  },
  load: {
    stages: [
      { duration: "20s", target: 10 },
      { duration: "40s", target: 25 },
      { duration: "20s", target: 0 },
    ],
  },
  spike: {
    stages: [
      { duration: "10s", target: 5 },
      { duration: "10s", target: 60 },
      { duration: "20s", target: 60 },
      { duration: "15s", target: 5 },
      { duration: "10s", target: 0 },
    ],
  },
};

export const options = {
  ...(PROFILES[PROFILE] || PROFILES.smoke),
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<1000", "p(99)<2500"],
    api_error_rate: ["rate<0.05"],
  },
};

export default function () {
  const catRes = http.get(`${BASE_URL}${CATEGORIES_PATH}`, {
    tags: { endpoint: "categories" },
  });
  catalogLatency.add(catRes.timings.duration);

  const prodRes = http.get(`${BASE_URL}${PRODUCTS_PATH}`, {
    tags: { endpoint: "products" },
  });
  catalogLatency.add(prodRes.timings.duration);

  const ok = check(catRes, {
    "categories status is 200": (r) => r.status === 200,
  }) && check(prodRes, {
    "products status is 200": (r) => r.status === 200,
  });

  apiErrorRate.add(!ok);
  sleep(0.5);
}