# Тести відмовостійкості мікросервісного бекенду ElectroStore

## 1. Зупинка та відновлення `electro_catalog_service`
- **Стан до збою:** `/api/v1/categories` -> `200` (`0.56 s`).
- **Під час зупинки (`docker stop`):** `/api/v1/categories` -> `502 Bad Gateway` (`38.36 s`); незалежний сервіс `auth` (`/api/v1/auth/me`) -> `404` (`0.14 s`), збій не каскадував на інші сервіси.
- **Відновлення (`docker start`):** повернення до `200 OK` за **`3.14 s`**.

## 2. Зупинка та відновлення `electro_redis`
- **Під час зупинки (`docker stop`):** `/api/v1/categories` -> `200` (`0.008 s`), `/api/v1/cart/` -> `401 {"detail":"Not authenticated"}` (`0.005 s`) без некерованих помилок `5xx`.
- **Відновлення (`docker start`):** `redis-cli ping` -> `PONG` за **`0.96 s`**, сервіси продовжили роботу в штатному режимі.
