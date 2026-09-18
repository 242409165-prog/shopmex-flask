from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3
import hashlib
import requests
import os
import re
import json
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'tienda_secret_key_2024'
DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'tienda.db')

# Filtro para parsear JSON en templates
app.jinja_env.filters['fromjson'] = json.loads

# ── Tipo de cambio USD → MXN ──────────────────────────────────────────────────
USD_TO_MXN = 17.5

def usd_to_mxn(usd):
    return round(usd * USD_TO_MXN, 2)

app.jinja_env.globals['usd_to_mxn'] = usd_to_mxn

# ── Traducciones de descripciones (IDs reales de FakeStore API) ───────────────
# ID 1-6: Electrónica | 7-10: Joyería | 11-14: Ropa Hombre | 15-20: Ropa Mujer
TRADUCCIONES = {
    # Electrónica
    1:  "Mochila de viaje resistente al agua con múltiples compartimentos. Puerto USB integrado para cargar dispositivos. Ideal para trabajo, escuela o viajes.",
    2:  "Suéter con capucha para hombre de algodón premium. Bolsillo frontal tipo canguro. Disponible en varios colores, tallas S a XXL.",
    3:  "Chamarra casual para hombre con forro interior suave. Cierre frontal y bolsillos laterales. Perfecta para clima fresco.",
    4:  "Chamarra de mezclilla para hombre, corte slim fit. Lavado desgastado con acabado vintage. Muy versátil para el día a día.",
    5:  "Suéter tejido a mano para hombre, lana merino 100%. Cuello redondo y manga larga. Abriga sin perder el estilo.",
    6:  "Camisa de franela a cuadros para hombre. Tela suave de algodón. Perfecta para look casual o leñador moderno.",
    # Joyería
    7:  "Collar dorado con colgante de flor delicada. Cadena de 45cm con cierre de langosta. Baño de oro 18K antialérgico.",
    8:  "Pulsera de plata .925 con diseño de infinito. Incluye caja de regalo. Ideal para regalar en cualquier ocasión.",
    9:  "Anillo ajustable de plata con piedra azul. Diseño bohemio elegante. Talla universal, perfecto como regalo.",
    10: "Collar de perlas cultivadas con cierre dorado. Cadena de 40cm. Clásico atemporal para ocasiones formales.",
    # Ropa Hombre
    11: "Camiseta slim fit de algodón peinado para hombre. Sin estampado, cuello redondo. Tela suave y duradera. Tallas XS a XXL.",
    12: "Camiseta casual premium con manga larga y botones. Corte relajado. Perfecta para uso diario o salidas informales.",
    13: "Chamarra de cuero genuino para hombre con cierre y bolsillos laterales. Forro interior cálido. Perfecta para otoño e invierno.",
    14: "Suéter de punto grueso para hombre. Tejido cálido de lana mezclada. Cuello redondo. Ideal para temporadas frías.",
    # Ropa Mujer
    15: "Vestido de verano con estampado floral. Tela chiffon ligera y fluida. Escote en V, falda midi. Perfecto para playa o casual.",
    16: "Vestido de satén con tirantes finos y corte en A. Ideal para cenas, eventos o salidas nocturnas. Elegante y sofisticado.",
    17: "Blusa de algodón con diseño de rayas. Corte recto y manga tres cuartos. Combina con jeans, falda o pantalón de vestir.",
    18: "Chamarra de mezclilla estilo boyfriend para mujer. Lavado vintage con botones dorados. Un básico que nunca pasa de moda.",
    19: "Top corto de punto con escote cuadrado y manga corta. Tela elástica cómoda. Combina con pantalón, falda o jeans.",
    20: "Suéter holgado de punto para mujer, estilo oversize. Cuello de tortuga. Abriga con estilo en días fríos.",
}

def get_descripcion(pid, desc_original):
    # Si no hay traducción para ese ID, usa la descripción original de la API
    return TRADUCCIONES.get(int(pid), desc_original)

app.jinja_env.globals['get_descripcion'] = get_descripcion

# ── Categorías en español ─────────────────────────────────────────────────────
CATEGORIAS_ES = {
    "electronics":    "Electrónica",
    "jewelery":       "Joyería",
    "men's clothing": "Ropa Hombre",
    "women's clothing":"Ropa Mujer",
}
app.jinja_env.globals['CATEGORIAS_ES'] = CATEGORIAS_ES

# ── Stock simulado por producto ───────────────────────────────────────────────
STOCK = {
    1:15, 2:8, 3:3, 4:20, 5:12, 6:0, 7:5, 8:9, 9:14, 10:6,
    11:18, 12:22, 13:4, 14:11, 15:7, 16:2, 17:16, 18:10, 19:0, 20:13,
}

def get_stock(pid):
    return STOCK.get(int(pid), 10)

app.jinja_env.globals['get_stock'] = get_stock

# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    cur = conn.cursor()
    cur.executescript('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre     TEXT NOT NULL,
            apellido   TEXT NOT NULL,
            email      TEXT UNIQUE NOT NULL,
            password   TEXT NOT NULL,
            telefono   TEXT,
            fecha_reg  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS contactos (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre    TEXT NOT NULL,
            email     TEXT NOT NULL,
            asunto    TEXT NOT NULL,
            mensaje   TEXT NOT NULL,
            fecha     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pedidos (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER NOT NULL,
            productos TEXT NOT NULL,
            total     REAL NOT NULL,
            estado    TEXT DEFAULT 'Completado',
            fecha     TEXT NOT NULL
        );
    ''')
    conn.commit()
    conn.close()

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ── Helpers ───────────────────────────────────────────────────────────────────

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesión para acceder a esta página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

# ── Register ──────────────────────────────────────────────────────────────────

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        nombre   = request.form.get('nombre', '').strip()
        apellido = request.form.get('apellido', '').strip()
        email    = request.form.get('email', '').strip().lower()
        telefono = request.form.get('telefono', '').strip()
        pw       = request.form.get('password', '').strip()
        pw2      = request.form.get('password2', '').strip()

        errors = []
        if not nombre:   errors.append('El nombre es obligatorio.')
        if not apellido: errors.append('El apellido es obligatorio.')
        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w{2,}$', email):
            errors.append('Correo electrónico inválido.')
        if len(pw) < 6:  errors.append('La contraseña debe tener al menos 6 caracteres.')
        if pw != pw2:    errors.append('Las contraseñas no coinciden.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('registro.html', form=request.form)

        try:
            conn = get_db()
            conn.execute(
                'INSERT INTO usuarios (nombre,apellido,email,password,telefono,fecha_reg) VALUES (?,?,?,?,?,?)',
                (nombre, apellido, email, hash_password(pw), telefono, datetime.now().strftime('%Y-%m-%d %H:%M'))
            )
            conn.commit()
            conn.close()
            flash('¡Registro exitoso! Ahora puedes iniciar sesión.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Ese correo ya está registrado.', 'danger')

    return render_template('registro.html', form={})

# ── Login / Logout ────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        pw    = request.form.get('password', '')

        conn = get_db()
        user = conn.execute(
            'SELECT * FROM usuarios WHERE email=? AND password=?',
            (email, hash_password(pw))
        ).fetchone()
        conn.close()

        if user:
            session['user_id']   = user['id']
            session['user_name'] = user['nombre']
            flash(f'¡Bienvenido, {user["nombre"]}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Correo o contraseña incorrectos.', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('index'))

# ── Catálogo de productos propio ──────────────────────────────────────────────

CATALOGO = [
    # ── Electrónica ──
    {"id":1,"title":"iPhone 14 Pro Max 256GB","category":"electronica",
     "price":999.99,"stock":12,"rating":{"rate":4.8,"count":1240},
     "image":"https://images.unsplash.com/photo-1678685888221-cda773a3dcdb?w=400&q=80",
     "description":"Smartphone Apple con chip A16 Bionic, cámara de 48MP, pantalla Super Retina XDR 6.7 pulgadas y Dynamic Island. Batería de larga duración hasta 29 horas."},
    {"id":2,"title":"Samsung Galaxy S23 Ultra","category":"electronica",
     "price":849.99,"stock":8,"rating":{"rate":4.7,"count":980},
     "image":"https://images.unsplash.com/photo-1610945415295-d9bbf067e59c?w=400&q=80",
     "description":"Teléfono Android con pantalla AMOLED 6.8 pulgadas, cámara cuádruple de 200MP, S Pen integrado y batería de 5000mAh. El smartphone más potente de Samsung."},
    {"id":3,"title":"MacBook Air M2 15 pulgadas","category":"electronica",
     "price":1299.99,"stock":5,"rating":{"rate":4.9,"count":760},
     "image":"https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=400&q=80",
     "description":"Laptop ultradelgada con chip Apple M2, pantalla Liquid Retina 15.3 pulgadas, 8GB RAM y SSD 256GB. Hasta 18 horas de batería sin cargador."},
    {"id":4,"title":"Sony WH-1000XM5 Audifonos","category":"electronica",
     "price":349.99,"stock":20,"rating":{"rate":4.8,"count":2100},
     "image":"https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=400&q=80",
     "description":"Audífonos inalámbricos con la mejor cancelación de ruido del mercado. 30 horas de batería, carga rápida y micrófono con IA para llamadas cristalinas."},
    {"id":5,"title":"iPad Pro 11 pulgadas M2","category":"electronica",
     "price":799.99,"stock":9,"rating":{"rate":4.7,"count":540},
     "image":"https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?w=400&q=80",
     "description":"Tablet con chip M2, pantalla Liquid Retina con ProMotion 120Hz, compatible con Apple Pencil 2 y Magic Keyboard. Perfecta para creativos y profesionales."},
    {"id":6,"title":"Apple Watch Series 9 GPS","category":"electronica",
     "price":399.99,"stock":15,"rating":{"rate":4.6,"count":890},
     "image":"https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=400&q=80",
     "description":"Smartwatch con pantalla Always-On Retina, sensor de frecuencia cardiaca, oxígeno en sangre y detector de caídas. Compatible con iPhone."},

    # ── Ropa y Moda ──
    {"id":7,"title":"Tenis Nike Air Max 270","category":"ropa",
     "price":149.99,"stock":30,"rating":{"rate":4.5,"count":3200},
     "image":"https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=400&q=80",
     "description":"Tenis deportivos con cámara de aire Max de 270° para máxima amortiguación. Diseño moderno y ligero. Disponibles en tallas del 24 al 31cm. Perfectos para correr o uso casual."},
    {"id":8,"title":"Chamarra de Cuero Negro","category":"ropa",
     "price":189.99,"stock":14,"rating":{"rate":4.4,"count":670},
     "image":"https://images.unsplash.com/photo-1551028719-00167b16eac5?w=400&q=80",
     "description":"Chamarra de cuero genuino con cierre frontal, bolsillos laterales y forro interior suave. Corte slim fit. Perfecta para otoño e invierno. Tallas S a XXL."},
    {"id":9,"title":"Jeans Slim Fit Azul Clásico","category":"ropa",
     "price":79.99,"stock":45,"rating":{"rate":4.3,"count":1500},
     "image":"https://images.unsplash.com/photo-1542272604-787c3835535d?w=400&q=80",
     "description":"Jeans de mezclilla 100% algodón, corte slim fit. Lavado clásico azul medio. Cinturilla ajustable y cinco bolsillos. Tallas 28 a 38. Combinan con todo."},
    {"id":10,"title":"Vestido Floral de Verano","category":"ropa",
     "price":59.99,"stock":22,"rating":{"rate":4.6,"count":890},
     "image":"https://images.unsplash.com/photo-1496747611176-843222e1e57c?w=400&q=80",
     "description":"Vestido midi con estampado floral en tela chiffon ligera. Escote en V, manga corta y falda fluida. Perfecto para playa, brunch o salidas casuales. Tallas XS a XL."},
    {"id":11,"title":"Bolsa Tote de Cuero Vegano","category":"ropa",
     "price":89.99,"stock":18,"rating":{"rate":4.5,"count":430},
     "image":"https://images.unsplash.com/photo-1548036328-c9fa89d128fa?w=400&q=80",
     "description":"Bolsa tote espaciosa de cuero vegano con asas dobles y cierre magnético. Interior forrado con bolsillo para celular. Perfecta para el trabajo o las compras."},

    # ── Hogar ──
    {"id":12,"title":"Cafetera Nespresso Vertuo","category":"hogar",
     "price":199.99,"stock":11,"rating":{"rate":4.7,"count":2300},
     "image":"https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=400&q=80",
     "description":"Cafetera automática con tecnología Centrifusion. Prepara café espresso, lungo, doble espresso y café grande. Incluye 12 cápsulas de bienvenida. Calienta en 30 segundos."},
    {"id":13,"title":"Silla Gamer Ergonómica","category":"hogar",
     "price":299.99,"stock":7,"rating":{"rate":4.5,"count":1100},
     "image":"https://images.unsplash.com/photo-1598550476439-6847785fcea6?w=400&q=80",
     "description":"Silla gaming con soporte lumbar ajustable, reposabrazos 4D, reclinable hasta 180°. Tapizado de cuero PU resistente. Soporta hasta 150kg. Ideal para largas jornadas."},
    {"id":14,"title":"Lámpara de Escritorio LED","category":"hogar",
     "price":49.99,"stock":35,"rating":{"rate":4.4,"count":780},
     "image":"https://images.unsplash.com/photo-1507473885765-e6ed057f782c?w=400&q=80",
     "description":"Lámpara LED con 5 niveles de brillo y 3 temperaturas de color. Base con cargador inalámbrico Qi integrado. Cuello flexible 360°. Ahorra 80% de energía."},
    {"id":15,"title":"Planta Monstera Deliciosa","category":"hogar",
     "price":34.99,"stock":25,"rating":{"rate":4.8,"count":560},
     "image":"https://images.unsplash.com/photo-1614594975525-e45190c55d0b?w=400&q=80",
     "description":"Planta de interior Monstera Deliciosa en maceta de 20cm. Fácil de cuidar, purifica el aire y decora cualquier espacio. Viene con sustrato especial para interiores."},

    # ── Deportes ──
    {"id":16,"title":"Bicicleta de Montaña 29\"","category":"deportes",
     "price":599.99,"stock":4,"rating":{"rate":4.6,"count":320},
     "image":"https://images.unsplash.com/photo-1485965120184-e220f721d03e?w=400&q=80",
     "description":"Bicicleta MTB con marco de aluminio, suspensión delantera, 21 velocidades Shimano y frenos de disco hidráulicos. Ruedas de 29 pulgadas. Ideal para montaña y ciudad."},
    {"id":17,"title":"Mancuernas Ajustables 20kg","category":"deportes",
     "price":129.99,"stock":16,"rating":{"rate":4.5,"count":940},
     "image":"https://images.unsplash.com/photo-1534438327276-14e5300c3a48?w=400&q=80",
     "description":"Set de mancuernas ajustables de 2 a 20kg con selector rápido de peso. Reemplazan 10 pares de mancuernas. Base incluida. Perfectas para ejercicio en casa."},
    {"id":18,"title":"Yoga Mat Antideslizante","category":"deportes",
     "price":39.99,"stock":50,"rating":{"rate":4.7,"count":1800},
     "image":"https://images.unsplash.com/photo-1601925228008-35e3e8d5f28c?w=400&q=80",
     "description":"Tapete de yoga 6mm de grosor, material TPE ecológico antideslizante. 183 x 61cm. Incluye correa para transporte. Ideal para yoga, pilates y meditación."},

    # ── Belleza ──
    {"id":19,"title":"Set Skincare Hidratante","category":"belleza",
     "price":89.99,"stock":28,"rating":{"rate":4.6,"count":1200},
     "image":"https://images.unsplash.com/photo-1556228720-195a672e8a03?w=400&q=80",
     "description":"Kit de cuidado facial con limpiador, tónico, sérum de vitamina C y crema hidratante SPF 30. Fórmula dermatológicamente probada para todo tipo de piel."},
    {"id":20,"title":"Perfume Acqua di Giò 100ml","category":"belleza",
     "price":119.99,"stock":19,"rating":{"rate":4.8,"count":3400},
     "image":"https://images.unsplash.com/photo-1541643600914-78b084683702?w=400&q=80",
     "description":"Eau de Toilette con notas acuáticas, bergamota y jazmín. Fragancia fresca e intensa para hombre. Duración de 8 a 12 horas. Presentación de 100ml con caja de regalo."},

    # ── Juguetes ──
    {"id":21,"title":"LEGO Technic Ferrari F40","category":"juguetes",
     "price":179.99,"stock":6,"rating":{"rate":4.9,"count":450},
     "image":"https://images.unsplash.com/photo-1587654780291-39c9404d746b?w=400&q=80",
     "description":"Set LEGO Technic con 1458 piezas. Incluye motor funcional, suspensión y puertas de mariposa. Para mayores de 10 años. Mide 35cm al terminar."},
    {"id":22,"title":"Consola Nintendo Switch OLED","category":"juguetes",
     "price":349.99,"stock":0,"rating":{"rate":4.8,"count":2100},
     "image":"https://images.unsplash.com/photo-1585620385456-4759f9b5c7d9?w=400&q=80",
     "description":"Consola híbrida con pantalla OLED de 7 pulgadas, base con puerto LAN, 64GB de almacenamiento y Joy-Con blancos. Juega en casa o a donde vayas."},

    # ── Alimentación ──
    {"id":23,"title":"Proteína Whey Gold 5lb","category":"alimentacion",
     "price":79.99,"stock":33,"rating":{"rate":4.7,"count":5600},
     "image":"https://images.unsplash.com/photo-1593095948071-474c5cc2989d?w=400&q=80",
     "description":"Proteína de suero de leche 100% pura, 24g de proteína por porción. Sabor chocolate. 74 servicios por bote. Sin azúcar añadida. Ideal post-entreno."},
    {"id":24,"title":"Café de Especialidad 500g","category":"alimentacion",
     "price":24.99,"stock":60,"rating":{"rate":4.8,"count":890},
     "image":"https://images.unsplash.com/photo-1447933601403-0c6688de566e?w=400&q=80",
     "description":"Café de especialidad de origen único, tostado medio. Notas a chocolate, caramelo y frutos rojos. Molido para cafetera de émbolo o filtro. Cosecha 2024."},
    # ── Accesorios ──
    {"id":25,"title":"Cartera de Piel Café","category":"accesorios",
     "price":10.49,"stock":40,"rating":{"rate":4.5,"count":620},
     "image":"https://images.unsplash.com/photo-1627123424574-724758594e93?w=400&q=80",
     "description":"Cartera delgada de piel genuina con 6 ranuras para tarjetas, compartimento para billetes y bolsillo trasero. Diseño slim que no abult en el bolsillo. Color café oscuro."},
    {"id":26,"title":"Lentes de Sol Aviador Dorado","category":"accesorios",
     "price":8.99,"stock":35,"rating":{"rate":4.4,"count":890},
     "image":"https://images.unsplash.com/photo-1572635196237-14b3f281503f?w=400&q=80",
     "description":"Lentes estilo aviador con armazón dorado y lentes espejados. Protección UV400. Incluye estuche rígido y paño de limpieza. Unisex, perfectos para playa o ciudad."},
    {"id":27,"title":"Cinturón de Cuero Negro","category":"accesorios",
     "price":9.99,"stock":28,"rating":{"rate":4.3,"count":450},
     "image":"https://images.unsplash.com/photo-1624623278313-a930126a11c3?w=400&q=80",
     "description":"Cinturón de cuero genuino con hebilla metálica plateada. Ancho 3.5cm. Tallas 90 a 120cm. Ideal para uso formal o casual. Costuras reforzadas y durables."},
    {"id":28,"title":"Gorra Nike Dri-FIT","category":"accesorios",
     "price":5.49,"stock":55,"rating":{"rate":4.6,"count":1300},
     "image":"https://images.unsplash.com/photo-1588850561407-ed78c282e89b?w=400&q=80",
     "description":"Gorra deportiva con tecnología Dri-FIT que absorbe la humedad. Visera curva, cierre ajustable trasero. Talla única. Perfecta para deporte o uso diario."},
    {"id":29,"title":"Bufanda de Lana Gris","category":"accesorios",
     "price":7.99,"stock":22,"rating":{"rate":4.5,"count":310},
     "image":"https://images.unsplash.com/photo-1520903920243-00d872a2d1c9?w=400&q=80",
     "description":"Bufanda tejida 100% lana merino. 180 x 30cm. Suave al tacto y muy abrigadora. Color gris clásico que combina con cualquier outfit de temporada fría."},
    {"id":30,"title":"Mochila Escolar 25L","category":"accesorios",
     "price":10.99,"stock":18,"rating":{"rate":4.7,"count":2100},
     "image":"https://images.unsplash.com/photo-1553062407-98eeb64c6a62?w=400&q=80",
     "description":"Mochila de 25 litros con compartimento principal, bolsillo frontal organizador y bolsillos laterales. Puerto USB externo. Correas acolchadas. Resistente al agua."},
    {"id":31,"title":"Pulsera Tejida Multicolor","category":"accesorios",
     "price":2.99,"stock":80,"rating":{"rate":4.3,"count":560},
     "image":"https://images.unsplash.com/photo-1573408301185-9519f94816b5?w=400&q=80",
     "description":"Set de 5 pulseras tejidas a mano con colores vibrantes. Cierre ajustable. Ideales para regalar o usar en el día a día. Estilo boho chic."},
    {"id":32,"title":"Reloj Análogo Clásico","category":"accesorios",
     "price":10.99,"stock":14,"rating":{"rate":4.6,"count":730},
     "image":"https://images.unsplash.com/photo-1524592094714-0f0654e20314?w=400&q=80",
     "description":"Reloj de pulsera con mecanismo japonés de cuarzo, caja de acero inoxidable y correa de piel marrón. Resistente al agua 30m. Garantía de 2 años."},
]

CATEGORIAS_TIENDA = {
    "electronica":   "Electrónica",
    "ropa":          "Ropa y Moda",
    "hogar":         "Hogar y Deco",
    "deportes":      "Deportes",
    "belleza":       "Belleza",
    "juguetes":      "Juguetes",
    "alimentacion":  "Alimentación",
    "accesorios":    "Accesorios",
}

def get_product(pid):
    return next((p for p in CATALOGO if p['id'] == int(pid)), None)

# ── Rutas de productos ────────────────────────────────────────────────────────

@app.route('/productos')
def productos():
    categoria = request.args.get('categoria', '')
    if categoria:
        products = [p for p in CATALOGO if p['category'] == categoria]
    else:
        products = CATALOGO
    cats = list(CATEGORIAS_TIENDA.keys())
    return render_template('productos.html', products=products, categories=cats,
                           categoria=categoria, CATEGORIAS_TIENDA=CATEGORIAS_TIENDA)

@app.route('/productos/<int:pid>')
def producto_detalle(pid):
    p = get_product(pid)
    return render_template('producto_detalle.html', product=p,
                           CATEGORIAS_TIENDA=CATEGORIAS_TIENDA)

# ── Cart (session-based) ──────────────────────────────────────────────────────

@app.route('/carrito')
@login_required
def carrito():
    cart = session.get('cart', [])
    total = sum(item['price'] * item['qty'] for item in cart)
    return render_template('carrito.html', cart=cart, total=round(total, 2))

@app.route('/carrito/agregar', methods=['POST'])
@login_required
def agregar_carrito():
    data = request.get_json()
    cart = session.get('cart', [])
    pid  = data.get('id')
    for item in cart:
        if item['id'] == pid:
            item['qty'] += 1
            session['cart'] = cart
            return jsonify({'ok': True, 'count': sum(i['qty'] for i in cart)})
    cart.append({'id': pid, 'title': data['title'], 'price': data['price'],
                 'image': data['image'], 'qty': 1})
    session['cart'] = cart
    return jsonify({'ok': True, 'count': sum(i['qty'] for i in cart)})

@app.route('/carrito/eliminar/<int:pid>')
@login_required
def eliminar_carrito(pid):
    cart = [i for i in session.get('cart', []) if i['id'] != pid]
    session['cart'] = cart
    flash('Producto eliminado del carrito.', 'info')
    return redirect(url_for('carrito'))

@app.route('/carrito/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart = session.get('cart', [])
    if not cart:
        flash('Tu carrito está vacío.', 'warning')
        return redirect(url_for('carrito'))

    total_usd = round(sum(i['price'] * i['qty'] for i in cart), 2)
    total_mxn = usd_to_mxn(total_usd)

    if request.method == 'POST':
        # Datos de envío
        nombre_env  = request.form.get('nombre_envio', '').strip()
        direccion   = request.form.get('direccion', '').strip()
        ciudad      = request.form.get('ciudad', '').strip()
        estado_env  = request.form.get('estado', '').strip()
        cp          = request.form.get('cp', '').strip()
        telefono    = request.form.get('telefono', '').strip()
        # Datos de pago
        titular     = request.form.get('titular', '').strip()
        num_tarjeta = request.form.get('num_tarjeta', '').replace(' ', '')
        expiry      = request.form.get('expiry', '').strip()
        cvv         = request.form.get('cvv', '').strip()

        errors = []
        if not nombre_env: errors.append('El nombre de envío es obligatorio.')
        if not direccion:  errors.append('La dirección es obligatoria.')
        if not ciudad:     errors.append('La ciudad es obligatoria.')
        if not cp:         errors.append('El código postal es obligatorio.')
        if not titular:    errors.append('El nombre del titular es obligatorio.')
        if len(num_tarjeta) not in [15, 16]: errors.append('Número de tarjeta inválido.')
        if not re.match(r'^\d{2}/\d{2}$', expiry): errors.append('Fecha de expiración inválida (MM/AA).')
        if len(cvv) not in [3, 4]: errors.append('CVV inválido.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            conn = get_db()
            user = conn.execute('SELECT * FROM usuarios WHERE id=?', (session['user_id'],)).fetchone()
            conn.close()
            return render_template('checkout.html', cart=cart, total_mxn=total_mxn, user=user)

        # Guardar pedido
        conn = get_db()
        conn.execute(
            'INSERT INTO pedidos (user_id, productos, total, estado, fecha) VALUES (?,?,?,?,?)',
            (session['user_id'], json.dumps(cart), total_mxn, 'Completado',
             datetime.now().strftime('%Y-%m-%d %H:%M'))
        )
        conn.commit()
        conn.close()
        session['cart'] = []
        flash('¡Compra realizada con éxito! Tu pedido está en camino. 🎉', 'success')
        return redirect(url_for('index'))

    # GET — mostrar formulario
    conn = get_db()
    user = conn.execute('SELECT * FROM usuarios WHERE id=?', (session['user_id'],)).fetchone()
    conn.close()
    return render_template('checkout.html', cart=cart, total_mxn=total_mxn, user=user)

# ── Contact ───────────────────────────────────────────────────────────────────

@app.route('/contacto', methods=['GET', 'POST'])
def contacto():
    if request.method == 'POST':
        nombre  = request.form.get('nombre', '').strip()
        email   = request.form.get('email', '').strip()
        asunto  = request.form.get('asunto', '').strip()
        mensaje = request.form.get('mensaje', '').strip()

        if not nombre or not email or not asunto or not mensaje:
            flash('Todos los campos son obligatorios.', 'danger')
        else:
            conn = get_db()
            conn.execute(
                'INSERT INTO contactos (nombre,email,asunto,mensaje,fecha) VALUES (?,?,?,?,?)',
                (nombre, email, asunto, mensaje, datetime.now().strftime('%Y-%m-%d %H:%M'))
            )
            conn.commit()
            conn.close()
            flash('¡Mensaje enviado! Te contactaremos pronto.', 'success')
            return redirect(url_for('contacto'))

    return render_template('contacto.html')

# ── Cuenta de usuario ─────────────────────────────────────────────────────────

@app.route('/cuenta')
@login_required
def cuenta():
    conn = get_db()
    user = conn.execute('SELECT * FROM usuarios WHERE id=?', (session['user_id'],)).fetchone()
    pedidos = conn.execute('SELECT * FROM pedidos WHERE user_id=? ORDER BY fecha DESC',
                           (session['user_id'],)).fetchall()
    conn.close()
    return render_template('cuenta.html', user=user, pedidos=pedidos)

@app.route('/cuenta/editar', methods=['POST'])
@login_required
def editar_cuenta():
    nombre   = request.form.get('nombre', '').strip()
    apellido = request.form.get('apellido', '').strip()
    telefono = request.form.get('telefono', '').strip()
    email    = request.form.get('email', '').strip().lower()

    if not nombre or not apellido or not email:
        flash('Nombre, apellido y correo son obligatorios.', 'danger')
        return redirect(url_for('cuenta'))

    try:
        conn = get_db()
        conn.execute(
            'UPDATE usuarios SET nombre=?, apellido=?, telefono=?, email=? WHERE id=?',
            (nombre, apellido, telefono, email, session['user_id'])
        )
        conn.commit()
        conn.close()
        session['user_name'] = nombre
        flash('Perfil actualizado correctamente.', 'success')
    except sqlite3.IntegrityError:
        flash('Ese correo ya está en uso por otra cuenta.', 'danger')

    return redirect(url_for('cuenta'))

@app.route('/cuenta/contrasena', methods=['POST'])
@login_required
def cambiar_contrasena():
    actual  = request.form.get('actual', '').strip()
    nueva   = request.form.get('nueva', '').strip()
    nueva2  = request.form.get('nueva2', '').strip()

    conn = get_db()
    user = conn.execute('SELECT * FROM usuarios WHERE id=?', (session['user_id'],)).fetchone()

    if user['password'] != hash_password(actual):
        flash('La contraseña actual es incorrecta.', 'danger')
        conn.close()
        return redirect(url_for('cuenta'))

    if len(nueva) < 6:
        flash('La nueva contraseña debe tener al menos 6 caracteres.', 'danger')
        conn.close()
        return redirect(url_for('cuenta'))

    if nueva != nueva2:
        flash('Las contraseñas nuevas no coinciden.', 'danger')
        conn.close()
        return redirect(url_for('cuenta'))

    conn.execute('UPDATE usuarios SET password=? WHERE id=?',
                 (hash_password(nueva), session['user_id']))
    conn.commit()
    conn.close()
    flash('Contraseña actualizada correctamente.', 'success')
    return redirect(url_for('cuenta'))

@app.route('/cuenta/eliminar', methods=['POST'])
@login_required
def eliminar_cuenta():
    pw = request.form.get('password', '').strip()
    conn = get_db()
    user = conn.execute('SELECT * FROM usuarios WHERE id=?', (session['user_id'],)).fetchone()

    if user['password'] != hash_password(pw):
        flash('Contraseña incorrecta. No se eliminó la cuenta.', 'danger')
        conn.close()
        return redirect(url_for('cuenta'))

    conn.execute('DELETE FROM usuarios WHERE id=?', (session['user_id'],))
    conn.commit()
    conn.close()
    session.clear()
    flash('Tu cuenta ha sido eliminada permanentemente.', 'info')
    return redirect(url_for('index'))

# ── Static pages ──────────────────────────────────────────────────────────────

@app.route('/acerca')
def acerca():
    return render_template('acerca.html')

@app.route('/terminos')
def terminos():
    return render_template('terminos.html')

# ── Cart count context ────────────────────────────────────────────────────────

@app.context_processor
def cart_count():
    cart = session.get('cart', [])
    return {'cart_count': sum(i['qty'] for i in cart)}

# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
