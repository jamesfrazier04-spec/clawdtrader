import os
import json
import uuid
import asyncio
from pathlib import Path

import stripe
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from services.ai_service import generate_content
from services.email_service import send_delivery_email

load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

SERVICES = {
    "blog_post":     {"name": "Blog Post (500 words)",        "price": 1500,  "desc": "SEO-optimized blog post on any topic"},
    "product_desc":  {"name": "Product Description",          "price": 1000,  "desc": "Compelling copy that converts browsers to buyers"},
    "social_pack":   {"name": "Social Media Pack (5 posts)",  "price": 2000,  "desc": "5 platform-ready posts for Twitter, LinkedIn, Instagram, Facebook"},
    "newsletter":    {"name": "Email Newsletter",             "price": 2500,  "desc": "Full newsletter with subject line, body, and CTA"},
}

ORDERS_FILE = Path(__file__).parent / "data" / "orders.jsonl"
ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)

# In-memory pending orders (keyed by order_id, before payment confirmed)
pending_orders: dict[str, dict] = {}


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "services": SERVICES})


@app.post("/create-checkout-session")
async def create_checkout_session(request: Request):
    form = await request.form()
    service_type = form.get("service_type")
    email        = form.get("email", "").strip()
    topic        = form.get("topic", "").strip()
    style        = form.get("style", "professional").strip()
    details      = form.get("details", "").strip()

    if service_type not in SERVICES:
        raise HTTPException(status_code=400, detail="Invalid service type")
    if not email or not topic:
        raise HTTPException(status_code=400, detail="Email and topic are required")

    order_id = str(uuid.uuid4())
    pending_orders[order_id] = {
        "order_id":     order_id,
        "service_type": service_type,
        "email":        email,
        "topic":        topic,
        "style":        style,
        "details":      details,
        "status":       "pending_payment",
    }

    base_url = os.getenv("BASE_URL", "http://localhost:8080")
    service  = SERVICES[service_type]

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency":     "usd",
                "product_data": {"name": service["name"], "description": service["desc"]},
                "unit_amount":  service["price"],
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"{base_url}/success?order_id={order_id}",
        cancel_url=f"{base_url}/cancel",
        metadata={"order_id": order_id},
        customer_email=email,
    )

    return RedirectResponse(session.url, status_code=303)


@app.get("/success", response_class=HTMLResponse)
async def success(request: Request, order_id: str = ""):
    order = pending_orders.get(order_id, {})
    service_name = SERVICES.get(order.get("service_type", ""), {}).get("name", "Your order")
    return templates.TemplateResponse("success.html", {
        "request":      request,
        "order_id":     order_id,
        "service_name": service_name,
        "email":        order.get("email", ""),
    })


@app.get("/cancel", response_class=HTMLResponse)
async def cancel(request: Request):
    return templates.TemplateResponse("cancel.html", {"request": request})


@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    secret     = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if event["type"] == "checkout.session.completed":
        session  = event["data"]["object"]
        order_id = session.get("metadata", {}).get("order_id")
        order    = pending_orders.get(order_id)

        if order and order["status"] == "pending_payment":
            order["status"] = "generating"
            order["amount_paid"] = session.get("amount_total", 0)

            try:
                content = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: generate_content(order)
                )
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: send_delivery_email(order["email"], order, content)
                )
                order["status"] = "delivered"
            except Exception as e:
                order["status"] = f"error: {e}"

            with open(ORDERS_FILE, "a") as f:
                f.write(json.dumps(order) + "\n")

    return JSONResponse({"status": "ok"})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, key: str = ""):
    if key != os.getenv("DASHBOARD_KEY", "changeme"):
        raise HTTPException(status_code=403, detail="Invalid dashboard key")

    orders = []
    if ORDERS_FILE.exists():
        for line in ORDERS_FILE.read_text().splitlines():
            if line.strip():
                orders.append(json.loads(line))

    total_revenue = sum(o.get("amount_paid", 0) for o in orders) / 100
    delivered     = sum(1 for o in orders if o.get("status") == "delivered")

    return templates.TemplateResponse("dashboard.html", {
        "request":       request,
        "orders":        list(reversed(orders)),
        "total_revenue": total_revenue,
        "delivered":     delivered,
        "total_orders":  len(orders),
        "services":      SERVICES,
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", 8080)), reload=False)
