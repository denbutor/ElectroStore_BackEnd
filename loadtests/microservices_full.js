import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.TARGET_URL || "http://localhost:8000";
const PROFILE = (__ENV.PROFILE || "smoke").toLowerCase();

const CATEGORIES_PATH = __ENV.CATEGORIES_PATH || "/api/v1/categories";
const PRODUCTS_PATH = __ENV.PRODUCTS_PATH || "/api/v1/products/";
const AUTH_PROBE_PATH = __ENV.AUTH_PROBE_PATH || "/api/v1/auth/me";
const ORDER_PROBE_PATH = __ENV.ORDER_PROBE_PATH || "/api/v1/cart/";
const AI_PROBE_PATH = __ENV.AI_PROBE_PATH || "/api/v1/ai/health";
const AUTH_TOKEN = __ENV.AUTH_TOKEN || "";

const apiErrorRate = new Rate("api_error_rate");
const catalogLatency = new Trend("catalog_latency", true);
const authLatency = new Trend("auth_latency", true);
const orderLatency = new Trend("order_latency", true);
const aiLatency = new Trend("ai_latency", true);

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

function authHeaders() {
  const headers = { Accept: "application/json" };
  if (AUTH_TOKEN) {
    headers.Authorization = `Bearer ${AUTH_TOKEN}`;
  }
  return headers;
}

export default function () {
  const headers = authHeaders();

  // 1. Catalog service
  const catRes = http.get(`${BASE_URL}${CATEGORIES_PATH}`, {
    headers,
    redirects: 0,
    tags: { service: "catalog", endpoint: "categories" },
  });
  catalogLatency.add(catRes.timings.duration);

  const prodRes = http.get(`${BASE_URL}${PRODUCTS_PATH}`, {
    headers,
    redirects: 0,
    tags: { service: "catalog", endpoint: "products" },
  });
  catalogLatency.add(prodRes.timings.duration);

  const catalogOk =
    check(catRes, { "catalog categories 200": (r) => r.status === 200 }) &&
    check(prodRes, { "catalog products 200": (r) => r.status === 200 });

  // 2. Auth service probe
  const authRes = http.get(`${BASE_URL}${AUTH_PROBE_PATH}`, {
    headers,
    redirects: 0,
    tags: { service: "auth", endpoint: "probe" },
  });
  authLatency.add(authRes.timings.duration);
  const authOk = check(authRes, {
    "auth reachable (not 502/503/504)": (r) => ![502, 503, 504].includes(r.status),
  });

  // 3. Order service probe
  const orderRes = http.get(`${BASE_URL}${ORDER_PROBE_PATH}`, {
    headers,
    redirects: 0,
    tags: { service: "order", endpoint: "probe" },
  });
  orderLatency.add(orderRes.timings.duration);
  const orderOk = check(orderRes, {
    "order reachable (not 502/503/504)": (r) => ![502, 503, 504].includes(r.status),
  });

  // 4. AI service probe
  const aiRes = http.get(`${BASE_URL}${AI_PROBE_PATH}`, {
    headers,
    redirects: 0,
    tags: { service: "ai", endpoint: "probe" },
  });
  aiLatency.add(aiRes.timings.duration);
  const aiOk = check(aiRes, {
    "ai reachable (not 502/503/504)": (r) => ![502, 503, 504].includes(r.status),
  });

  apiErrorRate.add(!(catalogOk && authOk && orderOk && aiOk));
  sleep(0.5);
}