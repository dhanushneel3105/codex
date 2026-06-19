import argparse
import json
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


DEFAULT_URL = "https://shop.amul.com/en/product/amul-high-protein-wheat-flour-65-g-or-pack-of-30-sachets"
DEFAULT_PINCODE = "560016"
DEFAULT_NOTIFY_EMAIL = "dhanushspjimr@gmail.com"
DEFAULT_PRODUCTS_FILE = Path(__file__).with_name("products.json")

UNAVAILABLE_TERMS = (
    "out of stock",
    "sold out",
    "currently unavailable",
    "not available",
    "notify me",
)

AVAILABLE_BUTTON_TERMS = (
    "add to cart",
    "add cart",
    "buy now",
)

AVAILABLE_TEXT_TERMS = (
    "add to cart",
    "in stock",
)

PRODUCT_SECTION_END_MARKERS = (
    "product information",
    "related products",
    "recently viewed",
    "customer review",
    "looking for great deals",
)


@dataclass
class StockStatus:
    available: bool
    reason: str
    page_title: str
    checked_at: str


@dataclass
class Product:
    key: str
    name: str
    url: str
    pincode: str
    notify_email: str


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def state_path() -> Path:
    default = Path(__file__).with_name("amul_stock_state.json")
    return Path(env("AMUL_STATE_FILE", str(default))).expanduser()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def status_to_dict(status: StockStatus) -> dict[str, Any]:
    return {
        "available": status.available,
        "reason": status.reason,
        "page_title": status.page_title,
        "checked_at": status.checked_at,
    }


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def product_key(product: dict[str, Any], index: int) -> str:
    raw_key = product.get("id") or product.get("name") or product.get("url") or f"product-{index + 1}"
    return str(raw_key).strip().lower().replace(" ", "-")


def load_products(args: argparse.Namespace) -> list[Product]:
    products_file = Path(args.products_file).expanduser()
    if args.url or not products_file.exists():
        return [
            Product(
                key="single-product",
                name="Amul product",
                url=args.url or DEFAULT_URL,
                pincode=args.pincode,
                notify_email=args.notify_email,
            )
        ]

    raw_products = json.loads(products_file.read_text(encoding="utf-8"))
    products: list[Product] = []

    for index, raw_product in enumerate(raw_products):
        url = raw_product.get("url")
        if not url:
            raise ValueError(f"Product at index {index} is missing a url.")
        products.append(
            Product(
                key=product_key(raw_product, index),
                name=raw_product.get("name") or f"Amul product {index + 1}",
                url=url,
                pincode=raw_product.get("pincode") or args.pincode,
                notify_email=raw_product.get("notify_email") or args.notify_email,
            )
        )

    return products


def click_visible_text(page, text: str, timeout: int = 1_500) -> bool:
    locator = page.get_by_text(text, exact=True)
    try:
        count = locator.count()
    except Exception:
        return False

    for index in range(count):
        candidate = locator.nth(index)
        try:
            if candidate.is_visible(timeout=timeout):
                candidate.click()
                return True
        except Exception:
            continue
    return False


def click_first_matching_button(page, labels: tuple[str, ...], timeout: int = 1_500) -> bool:
    for label in labels:
        try:
            button = page.get_by_role("button", name=label, exact=False).first
            if button.is_visible(timeout=timeout):
                button.click()
                return True
        except Exception:
            continue
    return False


def try_enter_pincode(page, pincode: str) -> None:
    for label in ("Select Pincodes", "Select Delivery Pincode", "Delivery Pincode"):
        try:
            trigger = page.get_by_text(label, exact=False).first
            if trigger.is_visible(timeout=2_000):
                trigger.click()
                page.wait_for_timeout(1_000)
                break
        except Exception:
            continue

    selectors = [
        "input[placeholder*='PIN' i]",
        "input[placeholder*='pincode' i]",
        "input[aria-label*='PIN' i]",
        "input[aria-label*='pincode' i]",
        "input[name*='pin' i]",
        "input[id*='pin' i]",
        "input[maxlength='6']",
        "input[pattern*='6']",
        "input[type='tel']",
    ]

    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=5_000)
            locator.fill(pincode)
            page.wait_for_timeout(1_500)
            if not click_visible_text(page, pincode):
                locator.press("Enter")
            break
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    click_first_matching_button(
        page,
        (
            "Submit",
            "Apply",
            "Check",
            "Confirm",
            "Continue",
            "Save",
            "Select",
            "Deliver",
            "Use",
            "Done",
        ),
    )

    page.wait_for_timeout(6_000)


def button_indicates_available(page) -> bool:
    for term in AVAILABLE_BUTTON_TERMS:
        try:
            button = page.get_by_role("button", name=term, exact=False).first
            if button.is_visible(timeout=1_000) and button.is_enabled(timeout=1_000):
                return True
        except Exception:
            continue
    return False


def text_indicates_available(body_text: str) -> bool:
    normalized = " ".join(body_text.lower().split())
    return any(term in normalized for term in AVAILABLE_TEXT_TERMS)


def main_product_stock_signal(body_text: str, product_names: tuple[str, ...]) -> tuple[bool | None, str | None]:
    normalized = " ".join(body_text.lower().split())
    start = -1

    for product_name in product_names:
        normalized_name = " ".join(product_name.lower().split())
        if not normalized_name:
            continue
        start = normalized.find(normalized_name)
        if start != -1:
            break

    if start == -1:
        return None, None

    section = normalized[start : start + 3_000]
    end_positions = [
        section.find(marker)
        for marker in PRODUCT_SECTION_END_MARKERS
        if section.find(marker) > 0
    ]
    if end_positions:
        section = section[: min(end_positions)]

    if any(term in section for term in ("sold out", "out of stock", "notify me")):
        return False, "Main product section says sold out/out of stock."
    if "in stock" in section:
        return True, "Main product section says in stock."
    if "add to cart" in section:
        return True, "Main product section contains add to cart without sold-out text."
    return None, None


def metadata_indicates_available(html: str) -> bool:
    normalized = html.lower()
    return any(
        pattern in normalized
        for pattern in (
            "schema.org/instock",
            '"availability":"instock"',
            '"availability": "instock"',
            '"availability":"https://schema.org/instock"',
            '"availability": "https://schema.org/instock"',
        )
    )


def save_debug_snapshot(debug_dir: str | None, key: str, page, body_text: str, html: str) -> None:
    if not debug_dir:
        return

    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "-", key).strip("-") or "product"
    path = Path(debug_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{safe_key}.txt").write_text(body_text, encoding="utf-8")
    (path / f"{safe_key}.html").write_text(html, encoding="utf-8")
    page.screenshot(path=str(path / f"{safe_key}.png"), full_page=True)


def check_stock(product: Product, headless: bool, debug_dir: str | None, pause_on_complete: bool) -> StockStatus:
    checked_at = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page(
            viewport={"width": 1365, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
        )
        page.goto(product.url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2_000)
        try_enter_pincode(page, product.pincode)

        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PlaywrightTimeoutError:
            pass

        body_text = page.locator("body").inner_text(timeout=15_000).lower()
        html = page.content()
        title = page.title()
        title_without_brand = title.replace("Amul - ", "").strip()
        main_signal, main_reason = main_product_stock_signal(body_text, (product.name, title_without_brand, title))
        has_unavailable_text = any(term in body_text for term in UNAVAILABLE_TERMS)
        has_available_button = button_indicates_available(page)
        has_available_text = text_indicates_available(body_text)
        has_available_metadata = metadata_indicates_available(html)
        save_debug_snapshot(debug_dir, product.key, page, body_text, html)

        if pause_on_complete:
            print("pause_on_complete=true; press Enter in PowerShell to close the browser")
            input()

        browser.close()

    if main_signal is not None:
        return StockStatus(main_signal, main_reason or "Main product section determined availability.", title, checked_at)
    if has_available_button:
        return StockStatus(True, "Enabled buy/add-to-cart button found.", title, checked_at)
    if has_available_text:
        return StockStatus(True, "Page contains an in-stock/add-to-cart signal for the product.", title, checked_at)
    if has_available_metadata:
        return StockStatus(True, "Page metadata says the product is in stock.", title, checked_at)
    if has_unavailable_text:
        return StockStatus(False, "Unavailable stock text found on page.", title, checked_at)
    return StockStatus(False, "No enabled buy/add-to-cart button found.", title, checked_at)


def send_email(product: Product, status: StockStatus) -> None:
    smtp_user = env("GMAIL_SMTP_USER")
    smtp_password = env("GMAIL_APP_PASSWORD")
    smtp_host = env("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(env("SMTP_PORT", "465"))

    if not smtp_user or not smtp_password:
        raise RuntimeError("Missing GMAIL_SMTP_USER or GMAIL_APP_PASSWORD environment variable.")

    message = EmailMessage()
    message["Subject"] = f"Amul product appears to be in stock: {product.name}"
    message["From"] = smtp_user
    message["To"] = product.notify_email
    message.set_content(
        "\n".join(
            [
                f"{product.name} appears to be available.",
                "",
                f"Product: {product.url}",
                f"Pincode: {product.pincode}",
                f"Checked at: {status.checked_at}",
                f"Reason: {status.reason}",
                "",
                "Open the product page soon because stock may change quickly.",
            ]
        )
    )

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
        server.login(smtp_user, smtp_password)
        server.send_message(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Amul product availability and email when it becomes available.")
    parser.add_argument("--products-file", default=env("AMUL_PRODUCTS_FILE", str(DEFAULT_PRODUCTS_FILE)))
    parser.add_argument("--url", default=env("AMUL_PRODUCT_URL"))
    parser.add_argument("--pincode", default=env("AMUL_PINCODE", DEFAULT_PINCODE))
    parser.add_argument("--notify-email", default=env("NOTIFY_EMAIL", DEFAULT_NOTIFY_EMAIL))
    parser.add_argument("--headful", action="store_true", help="Show the browser window while checking.")
    parser.add_argument("--dry-run", action="store_true", help="Check stock and update state without sending email.")
    parser.add_argument("--force-email", action="store_true", help="Send email whenever available, even if already notified.")
    parser.add_argument("--debug-dir", help="Save page text, HTML, and screenshot for each product.")
    parser.add_argument("--pause-on-complete", action="store_true", help="Keep the browser open until Enter is pressed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = state_path()
    state = load_state(path)
    products_state = state.setdefault("products", {})
    products = load_products(args)
    print(f"products_file={Path(args.products_file).expanduser()}")

    for product in products:
        previous = products_state.get(product.key, {})
        status = check_stock(
            product,
            headless=not args.headful,
            debug_dir=args.debug_dir,
            pause_on_complete=args.pause_on_complete,
        )
        should_email = status.available and (args.force_email or previous.get("available") is not True)

        print(f"product={product.name}")
        print(f"url={product.url}")
        print(f"available={status.available}")
        print(f"reason={status.reason}")
        print(f"checked_at={status.checked_at}")

        if should_email and not args.dry_run:
            send_email(product, status)
            print(f"email_sent={product.notify_email}")
        elif should_email and args.dry_run:
            print("email_skipped=dry_run")
        else:
            print("email_sent=false")

        products_state[product.key] = status_to_dict(status)
        print("")

    save_state(path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
