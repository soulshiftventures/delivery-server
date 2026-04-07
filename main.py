"""
Digital Product Delivery Server
Catches Stripe webhooks → emails buyer the purchased PDF.

Add products to PRODUCT_MAP — key is Stripe Price ID, value is file + name.
"""

import os, smtplib, base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

import stripe
from fastapi import FastAPI, Request, HTTPException
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
        session      = event["data"]["object"]
        buyer_email  = session.get("customer_details", {}).get("email")
        payment_link = session.get("payment_link")

        if payment_link and payment_link in PRODUCT_MAP:
            filename, name = PRODUCT_MAP[payment_link]
            send_pdf(buyer_email, filename, name)

    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}
