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

# Función auxiliar para obtener el nombre real del perfil desde Editable.ini
def get_stepmania_profile_name(stepmania_path, profile_id):
    """
    Lee el archivo Editable.ini ubicado en el directorio del perfil y extrae el nombre real
    del perfil usando la clave 'DisplayName' de la sección [Editable].
    """
    profile_dir = os.path.join(stepmania_path, profile_id)
    editable_path = os.path.join(profile_dir, "Editable.ini")
    if os.path.exists(editable_path):
        config = configparser.ConfigParser()
        config.read(editable_path)
        if "Editable" in config and "DisplayName" in config["Editable"]:
            return config["Editable"]["DisplayName"]
    return profile_id  # Retorna el ID si no se encuentra el nombre

# ------------------------------------------------
# Endpoint para obtener la configuración del usuario
# ------------------------------------------------
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

# ------------------------------------------------
# Endpoints de API (para comunicación con el monitor)
# ------------------------------------------------

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

        # Verificar la validez de la API key
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

        # Extraer y convertir los datos
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

        # Evitar duplicados: verificar si ya existe un puntaje igual o mayor
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

        # Insertar el nuevo puntaje
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

# ------------------------------------------------
# Endpoints para la Interfaz Web
# ------------------------------------------------

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        if not username or not password:
            return "Todos los campos son obligatorios", 400

        api_key = secrets.token_hex(16)  # Genera una API key única
        try:
            conn = db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (username, password, api_key) VALUES (?, ?, ?)",
                           (username, password, api_key))
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
    # Obtener configuración del usuario
    cursor.execute("SELECT stepmania_path, stepmania_profile FROM users WHERE username = ?", (session['username'],))
    user_config = cursor.fetchone()
    stepmania_path = user_config["stepmania_path"] if user_config and user_config["stepmania_path"] else ""
    profile_id = user_config["stepmania_profile"] if user_config and user_config["stepmania_profile"] else ""
    # Obtener el nombre real del perfil desde Editable.ini
    stepmania_profile_name = get_stepmania_profile_name(stepmania_path, profile_id) if stepmania_path and profile_id else "No configurado"
    # Obtener los records del usuario filtrados por profile_id
    cursor.execute("SELECT * FROM scores WHERE profile_id = ?", (profile_id,))
    scores = cursor.fetchall()
    # Calcular el total de puntos del usuario
    cursor.execute("SELECT SUM(score) AS total_points FROM scores WHERE profile_id = ?", (profile_id,))
    total_points_row = cursor.fetchone()
    total_points = total_points_row["total_points"] if total_points_row["total_points"] is not None else 0
    conn.close()
    return render_template('profile.html',
                           username=session['username'],
                           stepmania_profile=stepmania_profile_name,
                           total_points=total_points,
                           scores=scores,
                           stepmania_path=stepmania_path)

if __name__ == '__main__':
    app.run(debug=True)
