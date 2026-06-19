# Amul Stock Bot Setup

This workspace contains a checker at `work/amul_stock_checker.py`.

It reads products from `work/products.json`.

Current products:

- Amul High Protein Wheat Flour - pack of 30 sachets
- Amul Chocolate Whey Protein - pack of 60 sachets

Both currently use pincode `560016` and notify `dhanushspjimr@gmail.com`.

## Add Another Product

Open `work/products.json` and add another object:

```json
{
  "id": "short-unique-id",
  "name": "Product name for the email",
  "url": "https://shop.amul.com/en/product/product-url",
  "pincode": "560016",
  "notify_email": "dhanushspjimr@gmail.com"
}
```

Keep the `id` unique for each product. The bot uses it to remember whether that specific product was already emailed.

## Gmail Requirement

Gmail SMTP requires an App Password. Do not use your normal Google password.

Create one from Google Account > Security > 2-Step Verification > App passwords.

Set these environment variables in the environment where the automation runs:

```powershell
$env:GMAIL_SMTP_USER="dhanushspjimr@gmail.com"
$env:GMAIL_APP_PASSWORD="your-16-character-app-password"
```

## Local Test

Install dependencies:

```powershell
pip install -r work/requirements.txt
python -m playwright install chromium
```

Run a dry check:

```powershell
python work/amul_stock_checker.py --dry-run
```

Run a forced email test after setting Gmail variables:

```powershell
python work/amul_stock_checker.py --force-email
```

## Recurring Automation

The recurring job should run this every four hours:

```powershell
python work/amul_stock_checker.py
```

The script stores separate status for each product in `work/amul_stock_state.json`, so it emails only when that specific product becomes available after previously being unavailable.
