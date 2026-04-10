#!/usr/bin/env python3
"""
Модуль автоматического бронирования через Playwright.
Управляет многошаговой формой на сайте hqrentals.eu
"""

import asyncio
import logging
import re
from typing import Optional
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

BOOKING_URL_TEMPLATE = (
    "{base}/public/car-rental/reservations/step1"
    "?new=true&brand={brand}"
)

# Mapping of location names → Select2 option values on hqrentals.eu
LOCATION_VALUES = {
    "Aeropuerto Barcelona":    "1",
    "Aeropuerto de Girona":    "3",
    "Badalona":                "5",
    "Barcelona Sants":         "4",
    "Blanes":                  "12",
    "Calella":                 "9",
    "El Masnou":               "6",
    "Empuriabrava":            "20",
    "Lloret de Mar":           "2",
    "L'Escala":                "19",
    "Malgrat de Mar":          "11",
    "Mataró":                  "8",
    "Palamos":                 "18",
    "Pineda de Mar":           "10",
    "Platja d'Aro":            "16",
    "Premiá de Mar":           "7",
    "Roses":                   "21",
    "Sant Antoni de Calonge":  "17",
    "Sant Feliu de Guixols":   "14",
    "S'Agaro":                 "15",
    "Tossa de Mar":            "13",
}


class CarRentalBooking:
    """Управляет сессией бронирования автомобиля."""

    def __init__(self, base_url: str, brand_uuid: str):
        self.base_url = base_url.rstrip("/")
        self.brand = brand_uuid
        self.ssid: Optional[str] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ────────────────────────────────────────────────────────────────
    # Внутренние утилиты
    # ────────────────────────────────────────────────────────────────

    async def _launch(self) -> Page:
        """Запускаем headless Chromium и возвращаем страницу."""
        playwright = await async_playwright().start()
        self._playwright = playwright
        self._browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
        return self._page

    async def _close(self):
        """Закрываем браузер."""
        try:
            if self._browser:
                await self._browser.close()
            if hasattr(self, "_playwright") and self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"Ошибка при закрытии браузера: {e}")

    async def _extract_ssid(self, page: Page) -> Optional[str]:
        """Извлекаем ssid из текущего URL."""
        url = page.url
        match = re.search(r"ssid=([^&]+)", url)
        if match:
            return match.group(1)
        return None

    async def _set_field(self, page: Page, field_id: str, value: str):
        """Очищаем поле и вводим значение по ID."""
        locator = page.locator(f"#{field_id}")
        await locator.click(timeout=5000)
        await locator.triple_click(timeout=5000)
        await locator.fill(value)
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(200)

    async def _select_location(self, page: Page, select_id: str, location_name: str):
        """
        Выбираем локацию через Select2.
        select_id: 'pick_up_location' или 'return_location'
        """
        # Находим числовой value по имени локации
        value = LOCATION_VALUES.get(location_name)
        if not value:
            # Нечёткий поиск если точного совпадения нет
            for name, val in LOCATION_VALUES.items():
                if location_name.lower() in name.lower() or name.lower() in location_name.lower():
                    value = val
                    logger.info(f"Нечёткое совпадение локации: '{location_name}' → '{name}' (value={val})")
                    break

        if not value:
            logger.error(f"Локация не найдена: '{location_name}'")
            return

        try:
            # Устанавливаем значение через jQuery Select2 API
            await page.evaluate(f"""
                (function() {{
                    var sel = document.getElementById('{select_id}');
                    if (sel) {{
                        sel.value = '{value}';
                        // Trigger jQuery change event for Select2
                        if (window.jQuery) {{
                            jQuery(sel).trigger('change');
                        }} else {{
                            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                        }}
                    }}
                }})();
            """)
            await page.wait_for_timeout(400)
            logger.info(f"Локация '{location_name}' (value={value}) установлена в #{select_id}")
        except Exception as e:
            logger.error(f"Ошибка установки локации '{location_name}': {e}")

    async def _fill_step1(self, page: Page, booking_data: dict):
        """Заполняем шаг 1: даты, времена, локации."""
        # Заполняем дату получения
        await self._set_field(page, "pick_up_date", booking_data["pickup_date"])

        # Заполняем время получения
        await self._set_field(page, "pick_up_time", booking_data["pickup_time"])

        # Заполняем дату возврата
        await self._set_field(page, "return_date", booking_data["return_date"])

        # Заполняем время возврата
        await self._set_field(page, "return_time", booking_data["return_time"])

        # Выбираем локации через Select2
        await self._select_location(page, "pick_up_location", booking_data["pickup_location"])
        await self._select_location(page, "return_location", booking_data["return_location"])

        await page.wait_for_timeout(300)

    # ────────────────────────────────────────────────────────────────
    # Публичный API
    # ────────────────────────────────────────────────────────────────

    async def get_available_cars(self, booking_data: dict) -> list[dict]:
        """
        Заполняем шаг 1 (даты + локации) и парсим шаг 2 (список авто).
        Возвращает список словарей с информацией об авто.
        """
        page = await self._launch()
        cars = []
        try:
            # ── Шаг 1: Даты и локации ──────────────────────────────
            start_url = BOOKING_URL_TEMPLATE.format(base=self.base_url, brand=self.brand)
            await page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)

            # Сохраняем ssid
            self.ssid = await self._extract_ssid(page)
            logger.info(f"SSID сессии: {self.ssid}")

            # Заполняем все поля шага 1
            await self._fill_step1(page, booking_data)

            # Кликаем "Next Step"
            next_btn = page.locator("button.btn-primary, button[type='submit'], input[type='submit']").last
            await next_btn.click(timeout=10000)
            await page.wait_for_load_state("domcontentloaded", timeout=25000)
            await page.wait_for_timeout(2000)

            # ── Шаг 2: Список автомобилей ──────────────────────────
            logger.info(f"Текущий URL после шага 1: {page.url}")

            # Парсим карточки автомобилей
            cars = await self._parse_cars(page)
            logger.info(f"Найдено автомобилей: {len(cars)}")

        except PWTimeout as e:
            logger.error(f"Таймаут при загрузке страницы: {e}")
        except Exception as e:
            logger.error(f"Ошибка при получении авто: {e}", exc_info=True)
        finally:
            await self._close()

        return cars

    async def _parse_cars(self, page: Page) -> list[dict]:
        """Парсим список доступных автомобилей со страницы шага 2."""
        cars = []
        try:
            # Ждём появления карточек авто — несколько вариантов селекторов
            try:
                await page.wait_for_selector(
                    ".vehicle-item, .car-item, .vehicle-card, [class*='vehicle'], "
                    "[class*='car-card'], table tbody tr, .panel",
                    timeout=12000,
                )
            except PWTimeout:
                logger.warning("Стандартные карточки авто не найдены, продолжаем парсинг...")

            # Получаем через JavaScript все карточки авто
            car_data = await page.evaluate("""() => {
                const results = [];

                // Вариант 1: карточки vehicle
                const vehicleCards = document.querySelectorAll(
                    '.vehicle-item, .vehicle-card, .car-item, .car-card, ' +
                    '[data-vehicle-id], [data-car-id], .vehicle, .panel-body'
                );

                vehicleCards.forEach((card, idx) => {
                    const nameEl = card.querySelector(
                        'h2, h3, h4, .vehicle-name, .car-name, ' +
                        '[class*="name"], [class*="title"]'
                    );
                    const priceEl = card.querySelector(
                        '[class*="price"], [class*="cost"], [class*="rate"], ' +
                        '.price, .total'
                    );
                    const imgEl = card.querySelector('img');
                    const categoryEl = card.querySelector(
                        '[class*="category"], [class*="class"], [class*="type"]'
                    );
                    const btnEl = card.querySelector(
                        'button, a[href*="step"], [type="submit"]'
                    );

                    if (nameEl || priceEl) {
                        results.push({
                            name: nameEl ? nameEl.textContent.trim() : `Auto ${idx+1}`,
                            price: priceEl ? priceEl.textContent.trim().replace(/[^\\d.,]/g, '') : 'N/A',
                            price_raw: priceEl ? priceEl.textContent.trim() : '',
                            category: categoryEl ? categoryEl.textContent.trim() : '',
                            image: imgEl ? imgEl.src : '',
                            select_btn: btnEl ? btnEl.textContent.trim() : '',
                            idx: idx,
                        });
                    }
                });

                // Вариант 2: строки таблицы
                if (results.length === 0) {
                    const rows = document.querySelectorAll('table tbody tr');
                    rows.forEach((row, idx) => {
                        const cells = row.querySelectorAll('td');
                        if (cells.length >= 2) {
                            const priceEl = row.querySelector('[class*="price"]');
                            const nameText = cells[0] ? cells[0].textContent.trim() : '';
                            if (nameText && nameText.length > 1) {
                                results.push({
                                    name: nameText,
                                    price: priceEl ? priceEl.textContent.trim().replace(/[^\\d.,]/g, '') :
                                           (cells[cells.length-1] ? cells[cells.length-1].textContent.trim() : 'N/A'),
                                    price_raw: priceEl ? priceEl.textContent.trim() : '',
                                    category: cells[1] ? cells[1].textContent.trim() : '',
                                    image: '',
                                    idx: idx,
                                });
                            }
                        }
                    });
                }

                return results;
            }""")

            if car_data and len(car_data) > 0:
                for car in car_data:
                    name = car.get("name", "").strip()
                    if name and len(name) > 1 and name.lower() not in ["select", "book", "next"]:
                        price_str = car.get("price", "0").replace(",", ".").strip()
                        try:
                            price = float(price_str) if price_str and price_str != "N/A" else None
                        except ValueError:
                            price = None

                        cars.append({
                            "name": name,
                            "price": price if price else car.get("price_raw", "N/A"),
                            "category": car.get("category", ""),
                            "image": car.get("image", ""),
                            "idx": car.get("idx", len(cars)),
                        })

            # Дедупликация по имени
            seen = set()
            unique_cars = []
            for car in cars:
                key = car["name"].lower()
                if key not in seen and len(key) > 2:
                    seen.add(key)
                    unique_cars.append(car)
            cars = unique_cars[:15]

        except Exception as e:
            logger.error(f"Ошибка парсинга авто: {e}", exc_info=True)

        if not cars:
            logger.warning("Авто не найдены через парсинг — возможно изменилась структура страницы")
            # Сделаем скриншот для диагностики
            try:
                await page.screenshot(path="/tmp/debug_step2.png")
                logger.info("Скриншот сохранён в /tmp/debug_step2.png")
            except Exception:
                pass

        return cars

    async def complete_booking(self, booking_data: dict) -> dict:
        """
        Проходим все шаги бронирования:
        Step 1 → Step 2 (выбор авто) → Step 3 (extras) → Step 4 (клиент) → Step 5 (confirm)
        """
        page = await self._launch()
        result = {"success": False, "booking_id": None, "error": None}

        try:
            # ── Шаг 1: Даты и локации ──────────────────────────────
            start_url = BOOKING_URL_TEMPLATE.format(base=self.base_url, brand=self.brand)
            await page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)

            await self._fill_step1(page, booking_data)

            # Следующий шаг
            next_btn = page.locator("button.btn-primary, button[type='submit'], input[type='submit']").last
            await next_btn.click(timeout=10000)
            await page.wait_for_load_state("domcontentloaded", timeout=25000)
            await page.wait_for_timeout(2000)
            logger.info(f"Step 2 URL: {page.url}")

            # ── Шаг 2: Выбор автомобиля ────────────────────────────
            car_idx = booking_data.get("selected_car_idx", 0)
            selected = await self._select_car_on_page(page, car_idx)
            if not selected:
                result["error"] = "Не удалось выбрать автомобиль на шаге 2"
                return result

            await page.wait_for_load_state("domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
            logger.info(f"Step 3 URL: {page.url}")

            # ── Шаг 3: Доп. опции (extras) — просто Next ───────────
            await self._click_next(page)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await page.wait_for_timeout(1500)
            logger.info(f"Step 4 URL: {page.url}")

            # ── Шаг 4: Данные клиента ──────────────────────────────
            filled = await self._fill_customer_form(page, booking_data)
            if not filled:
                result["error"] = "Не удалось заполнить форму клиента"
                return result

            await self._click_next(page)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            logger.info(f"Step 5 URL: {page.url}")

            # ── Шаг 5: Подтверждение ───────────────────────────────
            booking_id = await self._confirm_and_get_id(page)
            if booking_id:
                result["success"] = True
                result["booking_id"] = booking_id
            else:
                if "step5" in page.url or "step6" in page.url or "confirm" in page.url or "payment" in page.url:
                    result["success"] = True
                    result["booking_id"] = await self._extract_ssid(page) or "CONFIRMED"
                else:
                    result["error"] = "Не удалось получить подтверждение"

        except PWTimeout as e:
            logger.error(f"Таймаут при бронировании: {e}")
            result["error"] = "Превышено время ожидания сайта. Попробуйте позже."
        except Exception as e:
            logger.error(f"Ошибка при бронировании: {e}", exc_info=True)
            result["error"] = str(e)
        finally:
            await self._close()

        return result

    async def _select_car_on_page(self, page: Page, car_idx: int) -> bool:
        """Выбираем автомобиль на шаге 2."""
        try:
            # Ищем кнопки "Select" / "Book" / "Choose" на странице
            select_buttons = page.get_by_role("button", name=re.compile(r"select|book|choose|rent|next|reserve", re.I))
            count = await select_buttons.count()
            logger.info(f"Найдено кнопок выбора авто: {count}")

            if count == 0:
                # Пробуем через ссылки
                select_links = page.locator("a").filter(has_text=re.compile(r"select|book|choose|rent", re.I))
                count = await select_links.count()
                if count > 0:
                    idx = min(car_idx, count - 1)
                    await select_links.nth(idx).click()
                    return True

            if count > 0:
                idx = min(car_idx, count - 1)
                await select_buttons.nth(idx).click()
                return True

            # Последний вариант: кликаем на карточку авто напрямую
            cards = page.locator(".vehicle-item, .vehicle-card, .car-card, [data-vehicle-id], .panel")
            card_count = await cards.count()
            if card_count > 0:
                idx = min(car_idx, card_count - 1)
                btn = cards.nth(idx).get_by_role("button").first
                await btn.click()
                return True

        except Exception as e:
            logger.error(f"Ошибка выбора авто: {e}")

        return False

    async def _fill_customer_form(self, page: Page, data: dict) -> bool:
        """Заполняем форму клиента на шаге 4."""
        try:
            await page.wait_for_selector("input[type='text'], input[type='email'], input[type='tel']", timeout=8000)

            field_mappings = [
                (r"first.?name|fname|given.?name|nombre", data["first_name"]),
                (r"last.?name|lname|surname|apellido", data["last_name"]),
                (r"email|e-mail|correo", data["email"]),
                (r"phone|tel|mobile|celular|movil", data["phone"]),
            ]

            for pattern, value in field_mappings:
                filled = await self._fill_field_by_pattern(page, pattern, value)
                if filled:
                    logger.info(f"Поле '{pattern}' заполнено: {value}")
                else:
                    logger.warning(f"Поле '{pattern}' не найдено")

            all_text_inputs = page.locator("input[type='text']:visible, input[type='email']:visible, input[type='tel']:visible")
            count = await all_text_inputs.count()
            logger.info(f"Всего полей ввода на шаге 4: {count}")

            if count >= 2:
                for i in range(min(count, 6)):
                    field = all_text_inputs.nth(i)
                    current_val = await field.input_value()
                    if not current_val:
                        placeholder = await field.get_attribute("placeholder") or ""
                        name_attr = await field.get_attribute("name") or ""
                        combined = (placeholder + name_attr).lower()

                        if "first" in combined or "name" in combined or "nombre" in combined:
                            await field.fill(data["first_name"])
                        elif "last" in combined or "surname" in combined or "apellido" in combined:
                            await field.fill(data["last_name"])
                        elif "email" in combined or "mail" in combined:
                            await field.fill(data["email"])
                        elif "phone" in combined or "tel" in combined or "mobile" in combined:
                            await field.fill(data["phone"])

            return True

        except Exception as e:
            logger.error(f"Ошибка заполнения формы клиента: {e}", exc_info=True)
            return False

    async def _fill_field_by_pattern(self, page: Page, pattern: str, value: str) -> bool:
        """Заполняем поле по паттерну в name/placeholder/id."""
        try:
            filled = await page.evaluate(f"""(args) => {{
                const pattern = new RegExp(args.pattern, 'i');
                const inputs = document.querySelectorAll('input[type="text"], input[type="email"], input[type="tel"], input:not([type="hidden"]):not([type="submit"]):not([type="checkbox"])');
                for (const inp of inputs) {{
                    const attrs = [inp.name, inp.placeholder, inp.id, inp.getAttribute('data-name')].join(' ');
                    if (pattern.test(attrs)) {{
                        inp.value = args.value;
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        return true;
                    }}
                }}
                return false;
            }}""", {"pattern": pattern, "value": value})
            return filled
        except Exception:
            return False

    async def _click_next(self, page: Page):
        """Кликаем кнопку следующего шага."""
        try:
            for selector in [
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Next')",
                "button:has-text('Continue')",
                "button:has-text('Siguiente')",
                ".btn-primary",
            ]:
                btn = page.locator(selector).last
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    return
        except Exception as e:
            logger.warning(f"Не удалось кликнуть Next: {e}")

    async def _confirm_and_get_id(self, page: Page) -> Optional[str]:
        """Кликаем подтверждение на шаге 5 и получаем номер бронирования."""
        try:
            await self._click_next(page)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)

            booking_id = await page.evaluate("""() => {
                const patterns = [
                    /booking.*?[#:]?\\s*([A-Z0-9-]{4,})/i,
                    /reservation.*?[#:]?\\s*([A-Z0-9-]{4,})/i,
                    /confirmation.*?[#:]?\\s*([A-Z0-9-]{4,})/i,
                    /reference.*?[#:]?\\s*([A-Z0-9-]{4,})/i,
                    /number.*?[#:]?\\s*([A-Z0-9-]{4,})/i,
                ];

                const text = document.body.innerText;
                for (const pattern of patterns) {
                    const match = text.match(pattern);
                    if (match) return match[1];
                }

                const idEl = document.querySelector(
                    '[class*="booking-id"], [class*="confirmation"], [class*="reference"], ' +
                    '[id*="booking"], [id*="confirmation"]'
                );
                if (idEl) return idEl.textContent.trim();

                return null;
            }""")

            if booking_id:
                logger.info(f"Номер бронирования: {booking_id}")
                return booking_id

            ssid = await self._extract_ssid(page)
            return ssid

        except Exception as e:
            logger.error(f"Ошибка при подтверждении: {e}")
            return None
