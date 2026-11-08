"""StyleKart — demo store, Server 2 of the VerifyCOD Gnani demo.

A simple storefront: 4 products, cart, COD checkout. On checkout the page
POSTs the order to the VerifyCOD API (port 8000) and the customer-phone
widget in the side panel rings — that phone is the buyer's phone.

The store itself holds no order data; VerifyCOD owns orders/verifications.
This server only serves the page. Run it on port 8001.

Run:  uvicorn app:app --reload --port 8001   (from the store/ folder)
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent

app = FastAPI(title="StyleKart — Demo Store")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def home():
    return FileResponse(BASE / "static" / "index.html")
