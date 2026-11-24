# Hazmelacompra (MVP)

Lista de la compra de varios supermercados/tiendas y una sola entrega a domicilio.

## Arrancar

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Abre http://127.0.0.1:8000 (web) o http://127.0.0.1:8000/docs (API interactiva).

## Cuentas

- **Clientes**: se registran en la web (email + contraseña de 8+ caracteres) y solo ven sus propios pedidos.
- **Repartidores**: entran en http://127.0.0.1:8000/repartidor. Hay una cuenta inicial
  (`repartidor@hazmelacompra.local` / `cambiame123`). Cámbiala **antes de publicar** arrancando con:

```bash
export HAZMELACOMPRA_REPARTIDOR_EMAIL=tu@email.com
export HAZMELACOMPRA_REPARTIDOR_PASSWORD=una_contraseña_larga
```

  La cuenta se crea la primera vez que arranca con una base de datos sin repartidores. Si ya existe `hazmelacompra.db`, borra la base de datos (o la cuenta) para que use las nuevas variables.
- Las contraseñas se guardan con PBKDF2 y las sesiones duran 30 días (token `Bearer`).

Desde el panel el repartidor ve los pedidos, marca artículos recogidos por parada, abre cada tienda en el mapa y marca la entrega.

## Estructura

- `main.py`: API FastAPI + SQLite (tiendas, productos, pedidos, ruta de recogida).
- `static/index.html`: web del cliente (lista, total, pedido y seguimiento).
- `static/repartidor.html`: panel del repartidor (solo cuentas con rol repartidor).

## Endpoints principales

| Método | Ruta | Para qué |
|---|---|---|
| GET | `/api/catalogo` | Productos agrupados por tienda |
| POST | `/api/pedidos` | Crear pedido multi-tienda (requiere login) |
| POST | `/api/registro`, `/api/login`, `/api/logout` | Cuentas y sesión |
| GET | `/api/mis-pedidos` | Pedidos del cliente |
| GET | `/api/pedidos/{id}` | Seguimiento (dueño o repartidor) |
| GET | `/api/pedidos?estado=pendiente` | Panel del repartidor |
| POST | `/api/pedidos/{id}/items/{item}/recogido` | Marcar artículo recogido |
| PATCH | `/api/pedidos/{id}/estado` | Cambiar estado (entregado, cancelado...) |

## Siguientes pasos

Pagos (Stripe), alta de repartidores desde un panel de administración, recuperar contraseña, catálogos reales por tienda (scraping/APIs/acuerdos),
ruta real con OSRM o Google Routes, PostgreSQL y notificaciones.
