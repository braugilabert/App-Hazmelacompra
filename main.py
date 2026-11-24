"""
Hazmelacompra - MVP
Lista de la compra de varios supermercados/tiendas y UNA sola entrega a domicilio.

Flujo:
  1. El usuario elige productos del catálogo de cada tienda y arma su lista.
  2. Crea un pedido: el sistema agrupa los artículos por tienda.
  3. Un repartidor (shopper) recoge en cada tienda (ruta de recogida) y hace
     una única entrega en casa del cliente.

Arranque:  uvicorn main:app --reload
"""
import hashlib
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "hazmelacompra.db"

# Tarifas del servicio (ajústalas a tu modelo de negocio)
FEE_BASE = 3.50          # tarifa fija de entrega
FEE_POR_TIENDA = 1.50    # extra por cada tienda adicional (a partir de la 2ª)
ENVIO_GRATIS_DESDE = 60.0

# Cuenta de repartidor inicial (cámbiala con variables de entorno)
REPARTIDOR_EMAIL = os.environ.get("HAZMELACOMPRA_REPARTIDOR_EMAIL", "repartidor@hazmelacompra.local")
REPARTIDOR_PASSWORD = os.environ.get("HAZMELACOMPRA_REPARTIDOR_PASSWORD", "cambiame123")
SESION_DIAS = 30


# ------------------------------------------------------------------ Autenticación
def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + "$" + h.hex()


def check_password(password: str, guardado: str) -> bool:
    salt_hex, h_hex = guardado.split("$")
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
    return secrets.compare_digest(h.hex(), h_hex)


def usuario_actual(authorization: str = Header(default="")) -> sqlite3.Row:
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Inicia sesión")
    with db() as conn:
        u = conn.execute(
            """SELECT u.id, u.email, u.nombre, u.rol FROM sesiones s
               JOIN usuarios u ON u.id = s.usuario_id
               WHERE s.token=? AND s.expira > ?""",
            (token, datetime.now().isoformat(timespec="seconds")),
        ).fetchone()
    if not u:
        raise HTTPException(401, "Sesión no válida o caducada")
    return u


def solo_repartidor(u=Depends(usuario_actual)):
    if u["rol"] != "repartidor":
        raise HTTPException(403, "Solo para repartidores")
    return u


def crear_sesion(conn, usuario_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expira = (datetime.now() + timedelta(days=SESION_DIAS)).isoformat(timespec="seconds")
    conn.execute("INSERT INTO sesiones(token, usuario_id, expira) VALUES (?,?,?)",
                 (token, usuario_id, expira))
    return token


# ---------------------------------------------------------------- Base de datos
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS tiendas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    direccion TEXT NOT NULL,
    lat REAL, lon REAL
);
CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tienda_id INTEGER NOT NULL REFERENCES tiendas(id),
    nombre TEXT NOT NULL,
    precio REAL NOT NULL,
    unidad TEXT NOT NULL DEFAULT 'ud'
);
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    password TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'cliente'
);
CREATE TABLE IF NOT EXISTS sesiones (
    token TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    expira TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pedidos (
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES usuarios(id),
    cliente TEXT NOT NULL,
    telefono TEXT NOT NULL,
    direccion_entrega TEXT NOT NULL,
    franja TEXT NOT NULL,
    estado TEXT NOT NULL,
    subtotal REAL NOT NULL,
    tarifa REAL NOT NULL,
    total REAL NOT NULL,
    creado TEXT NOT NULL,
    notas TEXT
);
CREATE TABLE IF NOT EXISTS pedido_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id TEXT NOT NULL REFERENCES pedidos(id),
    tienda_id INTEGER NOT NULL REFERENCES tiendas(id),
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    nombre TEXT NOT NULL,
    precio REAL NOT NULL,
    cantidad INTEGER NOT NULL,
    recogido INTEGER NOT NULL DEFAULT 0
);
"""

SEED_TIENDAS = [
    ("Mercadona", "Av. de Alfonso X el Sabio 10, Alicante", 38.3452, -0.4810),
    ("Carrefour", "C. Pintor Gisbert 3, Alicante", 38.3470, -0.4915),
    ("Lidl", "Av. de Denia 45, Alicante", 38.3600, -0.4790),
    ("Frutería El Huerto", "Mercado Central, Alicante", 38.3445, -0.4845),
    ("Farmacia Central", "C. Mayor 12, Alicante", 38.3460, -0.4830),
]
SEED_PRODUCTOS = {
    "Mercadona": [("Leche entera 1L", 0.89, "ud"), ("Pan de molde", 1.35, "ud"),
                  ("Huevos docena", 2.55, "ud"), ("Aceite de oliva 1L", 8.95, "ud")],
    "Carrefour": [("Arroz 1kg", 1.65, "ud"), ("Pasta 500g", 1.05, "ud"),
                  ("Café molido 250g", 3.40, "ud"), ("Detergente", 6.99, "ud")],
    "Lidl": [("Yogur natural x4", 1.19, "ud"), ("Queso rallado", 1.79, "ud"),
             ("Chocolate negro", 1.29, "ud"), ("Agua 6x1.5L", 2.10, "ud")],
    "Frutería El Huerto": [("Tomates", 2.20, "kg"), ("Naranjas", 1.60, "kg"),
                           ("Lechuga", 1.10, "ud"), ("Plátanos", 1.99, "kg")],
    "Farmacia Central": [("Paracetamol 1g", 2.45, "ud"), ("Gel hidroalcohólico", 2.99, "ud"),
                         ("Tiritas", 3.10, "ud")],
}


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(pedidos)")]
        if "user_id" not in cols:  # bases de datos creadas antes del login
            conn.execute("ALTER TABLE pedidos ADD COLUMN user_id INTEGER REFERENCES usuarios(id)")
        if not conn.execute("SELECT 1 FROM usuarios WHERE rol='repartidor' LIMIT 1").fetchone():
            conn.execute(
                "INSERT INTO usuarios(email, nombre, password, rol) VALUES (?,?,?,'repartidor')",
                (REPARTIDOR_EMAIL, "Repartidor", hash_password(REPARTIDOR_PASSWORD)),
            )
        if conn.execute("SELECT COUNT(*) FROM tiendas").fetchone()[0] == 0:
            for nombre, dir_, lat, lon in SEED_TIENDAS:
                conn.execute(
                    "INSERT INTO tiendas(nombre, direccion, lat, lon) VALUES (?,?,?,?)",
                    (nombre, dir_, lat, lon),
                )
            for tienda, prods in SEED_PRODUCTOS.items():
                tid = conn.execute("SELECT id FROM tiendas WHERE nombre=?", (tienda,)).fetchone()[0]
                for n, p, u in prods:
                    conn.execute(
                        "INSERT INTO productos(tienda_id, nombre, precio, unidad) VALUES (?,?,?,?)",
                        (tid, n, p, u),
                    )


# ---------------------------------------------------------------------- Modelos
class Estado(str, Enum):
    PENDIENTE = "pendiente"        # creado, esperando repartidor
    RECOGIENDO = "recogiendo"      # el repartidor está pasando por las tiendas
    EN_CAMINO = "en_camino"        # todo recogido, yendo a casa del cliente
    ENTREGADO = "entregado"
    CANCELADO = "cancelado"


class ItemIn(BaseModel):
    producto_id: int
    cantidad: int = Field(ge=1, le=50)


class PedidoIn(BaseModel):
    cliente: str = Field(min_length=2)
    telefono: str = Field(min_length=6)
    direccion_entrega: str = Field(min_length=5)
    franja: str = Field(description="Ej: 'Hoy 18:00-20:00'")
    notas: Optional[str] = None
    items: list[ItemIn] = Field(min_length=1)


class RegistroIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    nombre: str = Field(min_length=2)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: str
    password: str


class EstadoIn(BaseModel):
    estado: Estado


# ------------------------------------------------------------------------- Lógica
def calcular_tarifa(subtotal: float, n_tiendas: int) -> float:
    if subtotal >= ENVIO_GRATIS_DESDE:
        return 0.0
    return round(FEE_BASE + FEE_POR_TIENDA * max(0, n_tiendas - 1), 2)


def orden_ruta(tiendas: list[sqlite3.Row], origen=(38.3452, -0.4810)) -> list[sqlite3.Row]:
    """Ruta de recogida con heurística del vecino más cercano (suficiente para MVP).
    Para producción: usar Google Routes / OSRM / OR-Tools."""
    pendientes = list(tiendas)
    ruta, actual = [], origen
    while pendientes:
        sig = min(
            pendientes,
            key=lambda t: (t["lat"] - actual[0]) ** 2 + (t["lon"] - actual[1]) ** 2,
        )
        ruta.append(sig)
        pendientes.remove(sig)
        actual = (sig["lat"], sig["lon"])
    return ruta


def cargar_pedido(conn, pedido_id: str) -> dict:
    p = conn.execute("SELECT * FROM pedidos WHERE id=?", (pedido_id,)).fetchone()
    if not p:
        raise HTTPException(404, "Pedido no encontrado")
    items = conn.execute(
        """SELECT i.*, t.nombre AS tienda, t.direccion AS tienda_dir, t.lat, t.lon
           FROM pedido_items i JOIN tiendas t ON t.id = i.tienda_id
           WHERE i.pedido_id=?""",
        (pedido_id,),
    ).fetchall()

    por_tienda: dict[int, dict] = {}
    for it in items:
        g = por_tienda.setdefault(
            it["tienda_id"],
            {"tienda_id": it["tienda_id"], "tienda": it["tienda"], "direccion": it["tienda_dir"],
             "lat": it["lat"], "lon": it["lon"], "items": [], "subtotal": 0.0},
        )
        g["items"].append({"id": it["id"], "nombre": it["nombre"], "precio": it["precio"],
                           "cantidad": it["cantidad"], "recogido": bool(it["recogido"])})
        g["subtotal"] = round(g["subtotal"] + it["precio"] * it["cantidad"], 2)

    # Ordenar paradas según la ruta de recogida
    filas = [{"id": k, "lat": v["lat"], "lon": v["lon"]} for k, v in por_tienda.items()]
    orden = [r["id"] for r in orden_ruta(filas)]
    paradas = [por_tienda[i] for i in orden]
    for n, par in enumerate(paradas, 1):
        par["parada"] = n

    return {**dict(p), "paradas": paradas}


# --------------------------------------------------------------------------- App
app = FastAPI(title="Hazmelacompra", version="0.1.0")


@app.on_event("startup")
def _startup():
    init_db()


@app.post("/api/registro", status_code=201)
def registro(data: RegistroIn):
    email = data.email.lower().strip()
    with db() as conn:
        if conn.execute("SELECT 1 FROM usuarios WHERE email=?", (email,)).fetchone():
            raise HTTPException(409, "Ya existe una cuenta con ese email")
        uid = conn.execute(
            "INSERT INTO usuarios(email, nombre, password, rol) VALUES (?,?,?,'cliente')",
            (email, data.nombre.strip(), hash_password(data.password)),
        ).lastrowid
        token = crear_sesion(conn, uid)
    return {"token": token, "email": email, "nombre": data.nombre.strip(), "rol": "cliente"}


@app.post("/api/login")
def login(data: LoginIn):
    with db() as conn:
        u = conn.execute("SELECT * FROM usuarios WHERE email=?", (data.email.lower().strip(),)).fetchone()
        if not u or not check_password(data.password, u["password"]):
            raise HTTPException(401, "Email o contraseña incorrectos")
        token = crear_sesion(conn, u["id"])
    return {"token": token, "email": u["email"], "nombre": u["nombre"], "rol": u["rol"]}


@app.get("/api/me")
def me(u=Depends(usuario_actual)):
    return dict(u)


@app.post("/api/logout", status_code=204)
def logout(authorization: str = Header(default="")):
    with db() as conn:
        conn.execute("DELETE FROM sesiones WHERE token=?", (authorization.removeprefix("Bearer ").strip(),))


@app.get("/api/tiendas")
def listar_tiendas():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM tiendas ORDER BY nombre")]


@app.get("/api/catalogo")
def catalogo():
    """Catálogo completo agrupado por tienda."""
    with db() as conn:
        tiendas = conn.execute("SELECT * FROM tiendas ORDER BY nombre").fetchall()
        out = []
        for t in tiendas:
            prods = conn.execute(
                "SELECT id, nombre, precio, unidad FROM productos WHERE tienda_id=? ORDER BY nombre",
                (t["id"],),
            ).fetchall()
            out.append({**dict(t), "productos": [dict(p) for p in prods]})
        return out


@app.post("/api/pedidos", status_code=201)
def crear_pedido(data: PedidoIn, u=Depends(usuario_actual)):
    """Crea un pedido multi-tienda con UNA sola entrega."""
    with db() as conn:
        ids = [i.producto_id for i in data.items]
        marcas = ",".join("?" * len(ids))
        prods = {
            r["id"]: r
            for r in conn.execute(f"SELECT * FROM productos WHERE id IN ({marcas})", ids)
        }
        faltan = set(ids) - set(prods)
        if faltan:
            raise HTTPException(400, f"Productos inexistentes: {sorted(faltan)}")

        subtotal = round(sum(prods[i.producto_id]["precio"] * i.cantidad for i in data.items), 2)
        n_tiendas = len({prods[i.producto_id]["tienda_id"] for i in data.items})
        tarifa = calcular_tarifa(subtotal, n_tiendas)
        pedido_id = uuid.uuid4().hex[:8].upper()

        conn.execute(
            """INSERT INTO pedidos(id, user_id, cliente, telefono, direccion_entrega, franja, estado,
                                   subtotal, tarifa, total, creado, notas)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pedido_id, u["id"], data.cliente, data.telefono, data.direccion_entrega, data.franja,
             Estado.PENDIENTE.value, subtotal, tarifa, round(subtotal + tarifa, 2),
             datetime.now().isoformat(timespec="seconds"), data.notas),
        )
        for i in data.items:
            p = prods[i.producto_id]
            conn.execute(
                """INSERT INTO pedido_items(pedido_id, tienda_id, producto_id, nombre, precio, cantidad)
                   VALUES (?,?,?,?,?,?)""",
                (pedido_id, p["tienda_id"], p["id"], p["nombre"], p["precio"], i.cantidad),
            )
        return cargar_pedido(conn, pedido_id)


@app.get("/api/pedidos/{pedido_id}")
def ver_pedido(pedido_id: str, u=Depends(usuario_actual)):
    with db() as conn:
        p = cargar_pedido(conn, pedido_id.upper())
        if u["rol"] != "repartidor" and p["user_id"] != u["id"]:
            raise HTTPException(404, "Pedido no encontrado")
        return p


@app.get("/api/mis-pedidos")
def mis_pedidos(u=Depends(usuario_actual)):
    with db() as conn:
        rows = conn.execute("SELECT id FROM pedidos WHERE user_id=? ORDER BY creado DESC", (u["id"],)).fetchall()
        return [cargar_pedido(conn, r["id"]) for r in rows]


@app.get("/api/pedidos", dependencies=[Depends(solo_repartidor)])
def listar_pedidos(estado: Optional[Estado] = None):
    """Para el panel del repartidor / administración."""
    with db() as conn:
        if estado:
            rows = conn.execute(
                "SELECT id FROM pedidos WHERE estado=? ORDER BY creado DESC", (estado.value,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT id FROM pedidos ORDER BY creado DESC").fetchall()
        return [cargar_pedido(conn, r["id"]) for r in rows]


@app.patch("/api/pedidos/{pedido_id}/estado", dependencies=[Depends(solo_repartidor)])
def cambiar_estado(pedido_id: str, body: EstadoIn):
    with db() as conn:
        cargar_pedido(conn, pedido_id.upper())
        conn.execute("UPDATE pedidos SET estado=? WHERE id=?", (body.estado.value, pedido_id.upper()))
        return cargar_pedido(conn, pedido_id.upper())


@app.post("/api/pedidos/{pedido_id}/items/{item_id}/recogido", dependencies=[Depends(solo_repartidor)])
def marcar_recogido(pedido_id: str, item_id: int):
    """El repartidor marca cada artículo recogido; al completar todos pasa a EN_CAMINO."""
    pid = pedido_id.upper()
    with db() as conn:
        cargar_pedido(conn, pid)
        conn.execute(
            "UPDATE pedido_items SET recogido=1 WHERE id=? AND pedido_id=?", (item_id, pid)
        )
        pendientes = conn.execute(
            "SELECT COUNT(*) FROM pedido_items WHERE pedido_id=? AND recogido=0", (pid,)
        ).fetchone()[0]
        nuevo = Estado.EN_CAMINO if pendientes == 0 else Estado.RECOGIENDO
        conn.execute("UPDATE pedidos SET estado=? WHERE id=?", (nuevo.value, pid))
        return cargar_pedido(conn, pid)


# Frontend estático
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/repartidor")
def panel_repartidor():
    return FileResponse(BASE_DIR / "static" / "repartidor.html")
