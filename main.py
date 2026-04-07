"""
Digital Product Delivery Server
Catches Stripe webhooks → emails buyer the purchased PDF.

Add products to PRODUCT_MAP — key is Stripe Price ID, value is file + name.
"""

import os, base64, traceback
from pathlib import Path

import stripe
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

stripe.api_key          = os.environ["STRIPE_SECRET_KEY"]
WEBHOOK_SECRET          = os.environ["STRIPE_WEBHOOK_SECRET"]
RESEND_API_KEY          = os.environ["RESEND_API_KEY"]
FROM_EMAIL              = os.environ.get("FROM_EMAIL", "delivery@krissanders.online")
PRODUCTS_DIR            = Path(__file__).parent / "products"

# ── Add products here ────────────────────────────────────────────────────────
# Key: Stripe Payment Link ID (plink_...)   Value: (filename in /products, display name)
PRODUCT_MAP = {
    os.environ.get("PLINK_INSPECTAI", ""): (
        "AI-Prompts-for-Home-Inspectors.pdf",
        "AI Prompts for Home Inspectors",
    ),
}
# ─────────────────────────────────────────────────────────────────────────────


def send_pdf(to_email: str, product_file: str, product_name: str):
    """Send PDF to buyer via Resend API."""
    import httpx

    pdf_path = PRODUCTS_DIR / product_file
    if not pdf_path.exists():
        raise FileNotFoundError(f"Product file not found: {pdf_path}")

    pdf_b64 = base64.b64encode(pdf_path.read_bytes()).decode()

    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
        json={
            "from": f"OperatorHQ <{FROM_EMAIL}>",
            "to": [to_email],
            "subject": f"Your download: {product_name}",
            "html": f"""
                <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px;">
                    <h2 style="color:#22c55e;">Your download is ready.</h2>
                    <p>Thanks for your purchase. Your copy of <strong>{product_name}</strong> is attached to this email.</p>
                    <p>If you have any questions, just reply to this email.</p>
                    <p style="color:#888;font-size:12px;margin-top:40px;">
                        OperatorHQ · krissanders.online
                    </p>
                </div>
            """,
            "attachments": [
                {
                    "filename": product_file,
                    "content": pdf_b64,
                }
            ],
        },
        timeout=30,
    )
    response.raise_for_status()


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        try:
            session      = event["data"]["object"]
            customer_details = session.get("customer_details") or {}
            if isinstance(customer_details, str):
                customer_details = {}
            buyer_email  = customer_details.get("email") if isinstance(customer_details, dict) else None
            payment_link = session.get("payment_link")

            # Handle both string and object forms of payment_link
            if isinstance(payment_link, dict):
                payment_link = payment_link.get("id")

            print(f"DEBUG: payment_link={payment_link}, email={buyer_email}")
            print(f"DEBUG: PRODUCT_MAP keys={list(PRODUCT_MAP.keys())}")

            if payment_link and payment_link in PRODUCT_MAP:
                filename, name = PRODUCT_MAP[payment_link]
                print(f"DEBUG: sending {filename} to {buyer_email}")
                send_pdf(buyer_email, filename, name)
                print(f"DEBUG: send_pdf completed")
            else:
                print(f"DEBUG: payment_link not in PRODUCT_MAP")
        except Exception as e:
            print(f"ERROR: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}
