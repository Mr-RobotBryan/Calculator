from flask import Flask, request, jsonify, session, redirect, url_for, render_template
import sqlite3
import os
import secrets
import configparser

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta'  # Cambia esto por una clave más segura
db_name = "stepmania_stats.db"

# Filtro personalizado: extrae la parte final de una ruta (normalizada)
@app.template_filter('basename')
def basename_filter(path):
    return os.path.basename(os.path.normpath(path))

# ---------------------------
# Funciones de Utilidad
# ---------------------------
def calculate_league(percent_dp):
    """
    Calcula la liga (nombre de piedra preciosa) basándose en el promedio de PercentDP (valor entre 0 y 1).
    """
    if percent_dp < 0.70:
        return "Cuarzo"
    elif percent_dp < 0.75:
        return "Amatista"
    elif percent_dp < 0.80:
        return "Topacio"
    elif percent_dp < 0.85:
        return "Esmeralda"
    elif percent_dp < 0.90:
        return "Rubí"
    elif percent_dp < 0.95:
        return "Zafiro"
    else:
        return "Diamante"

def calculate_level(total_points):
    """
    Calcula el nivel basándose en el total acumulado de puntos.
    Cada 10,000,000 de puntos se sube un nivel.
    """
    return total_points // 10_000_000 + 1

def format_points(points):
    """
    Formatea los puntos para mostrarlos en notación abreviada:
      - En millones (M) si es >= 1,000,000.
      - En miles (K) si es >= 1,000.
      - Sino, se muestra el número completo.
    """
    if points >= 1_000_000:
        return f"{points/1_000_000:.2f}M"
    elif points >= 1_000:
        return f"{points/1_000:.1f}K"
    else:
        return str(points)

def db_connection():
    conn = sqlite3.connect(db_name)
    conn.row_factory = sqlite3.Row  # Permite acceder a las columnas por nombre
    return conn

def setup_database():
    conn = db_connection()
    cursor = conn.cursor()

    # Tabla de usuarios
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        api_key TEXT UNIQUE,
        stepmania_path TEXT,
        stepmania_profile TEXT
    )
    """)

    # Tabla de puntuaciones
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        song_dir TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        steps_type TEXT NOT NULL,
        grade TEXT NOT NULL,
        score INTEGER NOT NULL,
        percent_dp REAL NOT NULL,
        max_combo INTEGER NOT NULL,
        date_time TEXT NOT NULL,
        player_guid TEXT NOT NULL,
        player_name TEXT NOT NULL,
        profile_id TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()

setup_database()

# ---------------------------
# Endpoints de API
# ---------------------------

@app.route('/api/auth', methods=['POST'])
def api_auth():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({"status": "error", "message": "Faltan credenciales"}), 400
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT api_key FROM users WHERE username = ? AND password = ?", (username, password))
    result = cursor.fetchone()
    conn.close()
    if result:
        return jsonify({"status": "success", "api_key": result["api_key"]}), 200
    else:
        return jsonify({"status": "error", "message": "Credenciales incorrectas"}), 401

@app.route('/api/submit_stats', methods=['POST'])
def api_submit_stats():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No se envió un cuerpo JSON válido"}), 400
        api_key = data.get('api_key')
        if not api_key:
            return jsonify({"status": "error", "message": "API Key no proporcionada"}), 400
        conn = db_connection()
        cursor = conn.cursor()
        # Verificar la API key
        cursor.execute("SELECT username, stepmania_profile FROM users WHERE api_key = ?", (api_key,))
        user = cursor.fetchone()
        if not user:
            conn.close()
            return jsonify({"status": "error", "message": "Usuario no autorizado"}), 401
        username, profile_id = user["username"], user["stepmania_profile"]
        # Validar campos requeridos
        required_fields = [
            'song_dir', 'difficulty', 'steps_type', 'grade', 'score',
            'percent_dp', 'max_combo', 'date_time', 'player_guid', 'player_name'
        ]
        missing_fields = [field for field in required_fields if field not in data or not data[field]]
        if missing_fields:
            conn.close()
            return jsonify({
                "status": "error",
                "message": f"Faltan datos para registrar el puntaje: {', '.join(missing_fields)}"
            }), 400
        # Extraer datos
        song_dir = data['song_dir']
        difficulty = data['difficulty']
        steps_type = data['steps_type']
        grade = data['grade']
        score = int(data['score'])
        percent_dp = float(data['percent_dp'])
        max_combo = int(data['max_combo'])
        date_time = data['date_time']
        player_guid = data['player_guid']
        player_name = data['player_name']
        # Evitar duplicados (simplificado)
        cursor.execute("""
        SELECT 1 FROM scores 
        WHERE song_dir = ? AND difficulty = ? AND player_guid = ? AND score >= ?
        """, (song_dir, difficulty, player_guid, score))
        if cursor.fetchone():
            conn.close()
            return jsonify({
                "status": "error",
                "message": "El puntaje ya existe en la base de datos. No se registrará duplicado."
            }), 400
        cursor.execute("""
        INSERT INTO scores (
            song_dir, difficulty, steps_type, grade, score, 
            percent_dp, max_combo, date_time, player_guid, player_name, profile_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (song_dir, difficulty, steps_type, grade, score, percent_dp, max_combo, date_time, player_guid, player_name, profile_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Puntaje registrado exitosamente"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error inesperado: {str(e)}"}), 500

@app.route('/api/get_config', methods=['POST'])
def get_config():
    data = request.get_json()
    api_key = data.get("api_key")
    if not api_key:
        return jsonify({"status": "error", "message": "API key requerida"}), 400
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT stepmania_path, stepmania_profile FROM users WHERE api_key = ?", (api_key,))
    config_row = cursor.fetchone()
    conn.close()
    if config_row:
        return jsonify({
            "status": "success",
            "stepmania_path": config_row["stepmania_path"],
            "stepmania_profile": config_row["stepmania_profile"]
        }), 200
    else:
        return jsonify({"status": "error", "message": "Configuración no encontrada"}), 404

@app.route('/api/get_ranking_info', methods=['POST'])
def get_ranking_info():
    data = request.get_json()
    api_key = data.get("api_key")
    if not api_key:
        return jsonify({"status": "error", "message": "API key requerida"}), 400
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT stepmania_profile FROM users WHERE api_key = ?", (api_key,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    profile_id = user["stepmania_profile"]
    cursor.execute("SELECT SUM(score) AS total_points, AVG(percent_dp) AS avg_percent_dp FROM scores WHERE profile_id = ?", (profile_id,))
    row = cursor.fetchone()
    total_points = row["total_points"] if row["total_points"] is not None else 0
    avg_percent_dp = row["avg_percent_dp"] if row["avg_percent_dp"] is not None else 0
    conn.close()
    league = calculate_league(avg_percent_dp)
    level = calculate_level(total_points)
    formatted_points = format_points(total_points)
    return jsonify({
        "status": "success",
        "total_points": total_points,
        "avg_percent_dp": avg_percent_dp,
        "league": league,
        "level": level,
        "formatted_points": formatted_points
    }), 200

# ---------------------------
# Endpoints para la Interfaz Web
# (Simplificados; ajusta según tu implementación)
# ---------------------------
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    # Código de registro (simplificado)
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        if not username or not password:
            return "Todos los campos son obligatorios", 400
        api_key = secrets.token_hex(16)
        try:
            conn = db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (username, password, api_key) VALUES (?, ?, ?)", (username, password, api_key))
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return "El nombre de usuario ya existe. Por favor elige otro.", 400
        except Exception as e:
            return f"Error al registrar el usuario: {e}", 500
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        conn = db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username, api_key FROM users WHERE username = ? AND password = ?", (username, password))
        user = cursor.fetchone()
        conn.close()
        if user:
            session['username'] = user["username"]
            session['api_key'] = user["api_key"]
            return redirect(url_for('ranking'))
        else:
            return "Credenciales incorrectas", 400
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/configure_path', methods=['GET', 'POST'])
def configure_path():
    if 'username' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        stepmania_path = request.form['stepmania_path'].strip()
        if not stepmania_path:
            return "La ruta es obligatoria", 400
        conn = db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET stepmania_path = ? WHERE username = ?", (stepmania_path, session['username']))
        conn.commit()
        conn.close()
        return redirect(url_for('configure_profile'))
    return render_template('configure_path.html')

@app.route('/configure_profile', methods=['GET', 'POST'])
def configure_profile():
    if 'username' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        stepmania_profile = request.form['stepmania_profile'].strip()
        if not stepmania_profile:
            return "El ID del perfil es obligatorio", 400
        conn = db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET stepmania_profile = ? WHERE username = ?", (stepmania_profile, session['username']))
        conn.commit()
        conn.close()
        return redirect(url_for('ranking'))
    return render_template('configure_profile.html')

@app.route('/ranking')
def ranking():
    if 'username' not in session:
        return redirect(url_for('login'))
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT player_name, SUM(score) as total_score
        FROM scores
        GROUP BY player_name
        ORDER BY total_score DESC
    """)
    ranking_data = cursor.fetchall()
    conn.close()
    return render_template('ranking.html', ranking=ranking_data)

@app.route('/profile')
def profile():
    if 'username' not in session:
        return redirect(url_for('login'))
    conn = db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT stepmania_path, stepmania_profile FROM users WHERE username = ?", (session['username'],))
    user_config = cursor.fetchone()
    stepmania_path = user_config["stepmania_path"] if user_config and user_config["stepmania_path"] else ""
    profile_id = user_config["stepmania_profile"] if user_config and user_config["stepmania_profile"] else ""
    # Obtener ranking info para mostrar en el perfil
    cursor.execute("SELECT SUM(score) AS total_points, AVG(percent_dp) AS avg_percent_dp FROM scores WHERE profile_id = ?", (profile_id,))
    row = cursor.fetchone()
    total_points = row["total_points"] if row["total_points"] is not None else 0
    avg_percent_dp = row["avg_percent_dp"] if row["avg_percent_dp"] is not None else 0
    league = calculate_league(avg_percent_dp)
    level = calculate_level(total_points)
    formatted_points = format_points(total_points)
    cursor.execute("SELECT * FROM scores WHERE profile_id = ?", (profile_id,))
    scores = cursor.fetchall()
    conn.close()
    return render_template('profile.html',
                           username=session['username'],
                           stepmania_profile=league,  # Mostrar liga en vez de raw perfil
                           level=level,
                           formatted_points=formatted_points,
                           scores=scores,
                           stepmania_path=stepmania_path)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
