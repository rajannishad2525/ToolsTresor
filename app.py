from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import re, qrcode, io, hashlib, random, string, requests, os, uuid, secrets
from stegano import lsb
from loremipsum import get_sentence
from PIL import Image, ImageDraw

app = Flask(__name__)
CORS(app, supports_credentials=True)

# CONFIG
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SECRET_KEY'] = 'secretkey123'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- MODELS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    first_login = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)
    def ping(self): self.last_seen = datetime.utcnow(); db.session.commit()

class SiteSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    maintenance_mode = db.Column(db.Boolean, default=False)

class BlogPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    content = db.Column(db.Text, nullable=False)
    meta_description = db.Column(db.String(160), nullable=False, default="")
    keywords = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Tool(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    route_name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=False)
    icon = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

# Secret Note Model
class SecretNote(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id): return db.session.get(User, int(user_id))

# --- MAINTENANCE CHECK ---
@app.before_request
def check_maintenance():
    # Ye routes hamesha open rahenge
    allowed_routes = ['static', 'login', 'signup', 'admin_panel', 'toggle_maintenance', 'logout', 'login_status', 'admin_login_page']
    if request.endpoint in allowed_routes: return
    
    # Admin hamesha access kar sakta hai
    if current_user.is_authenticated and current_user.is_admin: return
    
    # Baaki sabke liye check karo
    setting = SiteSetting.query.first()
    if setting and setting.maintenance_mode: return render_template('maintenance.html')

# ==========================================
# --- AUTH & MAIN ROUTES ---
# ==========================================

@app.route('/')
def home():
    tools = Tool.query.filter_by(is_active=True).all()
    return render_template('index.html', user=current_user, tools=tools)

# NORMAL USER LOGIN (Admin Blocked)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('home'))
    error = None
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and user.check_password(request.form.get('password')):
            if user.is_admin:
                error = "Admins cannot login here. Use /adminryzen"
            else:
                login_user(user); user.ping()
                return redirect(url_for('home'))
        else: error = "Invalid email or password"
    return render_template('login.html', error=error)

# SECRET ADMIN LOGIN (Only for Admins)
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login_page():
    if current_user.is_authenticated and current_user.is_admin: return redirect(url_for('admin_panel'))
    error = None
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and user.check_password(request.form.get('password')):
            if user.is_admin:
                login_user(user); user.ping()
                return redirect(url_for('admin_panel'))
            else: error = "Access Denied: You are not an Admin."
        else: error = "Invalid Admin Credentials"
    return render_template('admin_login.html', error=error)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated: return redirect(url_for('home'))
    error = None
    if request.method == 'POST':
        if User.query.filter_by(email=request.form.get('email')).first(): error = "User already exists"
        else:
            u = User(email=request.form.get('email'), is_admin=False); u.set_password(request.form.get('password'))
            db.session.add(u); db.session.commit(); login_user(u); return redirect(url_for('home'))
    return render_template('signup.html', error=error)

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('home'))

# ==========================================
# --- ADMIN PANEL ROUTES ---
# ==========================================

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin: return "Access Denied", 403
    return render_template('admin.html', users=User.query.all(), maintenance=SiteSetting.query.first().maintenance_mode, posts=BlogPost.query.all(), tools=Tool.query.all())

@app.route('/admin/toggle_maintenance')
@login_required
def toggle_maintenance():
    if not current_user.is_admin: return "Access Denied", 403
    s = SiteSetting.query.first(); s.maintenance_mode = not s.maintenance_mode; db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/toggle_tool/<int:id>')
@login_required
def toggle_tool(id):
    if not current_user.is_admin: return "Access Denied", 403
    t = db.session.get(Tool, id); t.is_active = not t.is_active; db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete-user/<int:id>')
@login_required
def delete_user(id):
    if not current_user.is_admin or id == current_user.id: return redirect(url_for('admin_panel'))
    u = db.session.get(User, id); db.session.delete(u); db.session.commit(); return redirect(url_for('admin_panel'))

@app.route('/admin/create-post', methods=['GET', 'POST'])
@login_required
def create_post():
    if not current_user.is_admin: return "Access Denied", 403
    if request.method == 'POST':
        slug = re.sub(r'[^a-z0-9-]', '', request.form.get('slug').lower().strip().replace(' ', '-'))
        if BlogPost.query.filter_by(slug=slug).first(): flash('Slug exists!'); return redirect(url_for('create_post'))
        db.session.add(BlogPost(title=request.form.get('title'), slug=slug, content=request.form.get('content'), meta_description=request.form.get('meta_description'), keywords=request.form.get('keywords')))
        db.session.commit(); return redirect(url_for('admin_panel'))
    return render_template('create_blog.html')

@app.route('/blog/<slug>')
def view_blog(slug): return render_template('view_blog.html', post=BlogPost.query.filter_by(slug=slug).first_or_404())

@app.route('/admin/delete-post/<int:id>')
@login_required
def delete_post(id):
    if not current_user.is_admin: return "Access Denied", 403
    p = db.session.get(BlogPost, id); db.session.delete(p); db.session.commit(); return redirect(url_for('admin_panel'))

@app.route('/admin/add-tool', methods=['GET', 'POST'])
@login_required
def add_tool():
    if not current_user.is_admin: return "Access Denied", 403
    if request.method == 'POST':
        if Tool.query.filter_by(route_name=request.form.get('route')).first(): flash('Exists'); return redirect(url_for('add_tool'))
        db.session.add(Tool(name=request.form.get('name'), route_name=request.form.get('route'), description=request.form.get('description'), icon=request.form.get('icon'), is_active=True))
        db.session.commit(); return redirect(url_for('admin_panel'))
    return render_template('add_tool.html')

# ==========================================
# --- TOOL ROUTES (Pages + API) ---
# ==========================================

# Pages (HTML Render)
@app.route('/word-counter')
def page_word_counter(): return render_template('word-counter.html', user=current_user)
@app.route('/qr-generator')
def page_qr_generator(): return render_template('qr-generator.html', user=current_user)
@app.route('/case-converter')
def page_case_converter(): return render_template('case-converter.html', user=current_user)
@app.route('/md5-generator')
def page_md5_generator(): return render_template('md5-generator.html', user=current_user)
@app.route('/password-generator')
def page_password_generator(): return render_template('password-generator.html', user=current_user)
@app.route('/lorem-ipsum')
def page_lorem_ipsum(): return render_template('lorem-ipsum.html', user=current_user)
@app.route('/my-ip')
def page_my_ip(): return render_template('my-ip.html', user=current_user)
@app.route('/random-quote')
def page_random_quote(): return render_template('random-quote.html', user=current_user)
@app.route('/header-checker')
def page_header_checker(): return render_template('header-checker.html', user=current_user)
@app.route('/image-compressor')
def page_image_compressor(): return render_template('image-compressor.html', user=current_user)
@app.route('/steganography')
def page_steganography(): return render_template('steganography.html', user=current_user)
@app.route('/exif-cleaner')
def page_exif_cleaner(): return render_template('exif-cleaner.html')
@app.route('/url-scanner')
def page_url_scanner(): return render_template('url-scanner.html')
@app.route('/secret-note')
def page_secret_note(): return render_template('secret-note.html', user=current_user)
@app.route('/digital-footprint')
def page_digital_footprint(): return render_template('digital-footprint.html', user=current_user)
@app.route('/file-hasher')
def page_file_hasher(): return render_template('file-hasher.html', user=current_user)
@app.route('/password-strength')
def page_password_strength(): return render_template('password-strength.html', user=current_user)
@app.route('/pdf-cleaner')
def page_pdf_cleaner(): return render_template('pdf-cleaner.html', user=current_user)
@app.route('/watermarker')
def page_watermarker(): return render_template('watermarker.html', user=current_user)
@app.route('/file-locker')
def page_file_locker(): return render_template('file-locker.html', user=current_user)

# Static Pages
@app.route('/about-us')
def about_us(): return render_template('about-us.html')
@app.route('/contact-us')
def contact_us(): return render_template('contact-us.html')
@app.route('/privacy-policy')
def privacy_policy(): return render_template('privacy-policy.html')
@app.route('/terms-of-service')
def terms_of_service(): return render_template('terms_of_service.html')

# API Logic
@app.route('/api/word-counter', methods=['POST'])
def api_word_counter():
    t = request.get_json().get('text', '')
    return jsonify({'words': len(t.split()) if t else 0, 'characters': len(t), 'sentences': len(re.findall(r'[.!?]+', t)) if t else 0, 'paragraphs': len([p for p in t.split('\n') if p.strip()]) if t else 0})

@app.route('/api/qr-generator', methods=['POST'])
def api_qr_generator():
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5); qr.add_data(request.get_json().get('text', '')); qr.make(fit=True)
        b = io.BytesIO(); qr.make_image(fill='black', back_color='white').save(b, 'PNG'); b.seek(0)
        return send_file(b, mimetype='image/png')
    except: return jsonify({'error': 'Error'}), 500

@app.route('/api/steganography', methods=['POST'])
def api_steganography():
    try:
        action = request.form.get('action'); f = request.files['image']
        if action == 'encode':
            secret = lsb.hide(f, request.form.get('message')); b = io.BytesIO(); secret.save(b, 'PNG'); b.seek(0)
            return send_file(b, mimetype='image/png', as_attachment=True, download_name='secret.png')
        elif action == 'decode': return jsonify({'result': lsb.reveal(f) or "No message found"})
    except: return jsonify({'error': 'Error or Invalid Image'}), 500

@app.route('/api/case-converter', methods=['POST'])
def api_case_converter():
    d = request.get_json(); t = d.get('text', ''); c = d.get('case_type', '')
    if c == 'uppercase': r = t.upper()
    elif c == 'lowercase': r = t.lower()
    elif c == 'titlecase': r = t.title()
    elif c == 'sentencecase': r = t.capitalize()
    else: r = t
    return jsonify({'result': r})

@app.route('/api/md5-generator', methods=['POST'])
def api_md5_generator(): return jsonify({'result': hashlib.md5(request.get_json().get('text', '').encode()).hexdigest()})

@app.route('/api/password-generator', methods=['POST'])
def api_password_generator():
    d = request.get_json(); l = int(d.get('length', 12))
    c = string.ascii_letters + (string.digits if d.get('numbers') else '') + (string.punctuation if d.get('symbols') else '')
    return jsonify({'result': ''.join(secrets.choice(c) for i in range(l))})

@app.route('/api/lorem-ipsum', methods=['POST'])
def api_lorem_ipsum(): return jsonify({'result': ' '.join([get_sentence()[0] for _ in range(int(request.get_json().get('count', 3)))])})

@app.route('/api/my-ip', methods=['GET'])
def api_my_ip(): return jsonify({'ip': request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr).split(',')[0]})

@app.route('/api/random-quote', methods=['GET'])
def api_random_quote(): return jsonify(random.choice([{"quote": "Stay hungry.", "author": "Steve Jobs"}, {"quote": "Code is poetry.", "author": "Unknown"}]))

@app.route('/api/header-checker', methods=['POST'])
def api_header_checker():
    try:
        url = request.get_json().get('url', '')
        if not url.startswith('http'): url = 'https://' + url
        from urllib.parse import urlparse; h = urlparse(url).hostname or ''
        if any(h.startswith(b) for b in ['localhost','127.','192.168.','10.','172.']): return jsonify({'error': 'Invalid URL'}), 400
        return jsonify({'result': str(requests.head(url, timeout=5).headers)})
    except: return jsonify({'error': 'Error'}), 500

@app.route('/api/image-compressor', methods=['POST'])
def api_image_compressor():
    try:
        f = request.files['image']; i = Image.open(f.stream); b = io.BytesIO(); i.save(b, format=i.format, quality=60); b.seek(0)
        return send_file(b, mimetype=f.mimetype)
    except: return jsonify({'error': 'Error'}), 500

@app.route('/api/exif-cleaner', methods=['POST'])
def api_exif_cleaner():
    try:
        f = request.files['image']; i = Image.open(f.stream); d = list(i.getdata()); n = Image.new(i.mode, i.size); n.putdata(d)
        b = io.BytesIO(); n.save(b, format='PNG'); b.seek(0)
        return send_file(b, mimetype='image/png', as_attachment=True, download_name='clean.png')
    except: return jsonify({'error': 'Error'}), 500

@app.route('/api/url-scanner', methods=['POST'])
def api_url_scanner():
    try:
        url = request.get_json().get('url', '')
        if not url.startswith('http'): url = 'https://' + url
        from urllib.parse import urlparse; h = urlparse(url).hostname or ''
        if any(h.startswith(b) for b in ['localhost','127.','192.168.','10.','172.']): return jsonify({'error': 'Invalid URL'}), 400
        return jsonify({'real_url': requests.head(url, allow_redirects=True, timeout=5).url})
    except: return jsonify({'error': 'Invalid'}), 400

@app.route('/api/create-note', methods=['POST'])
def api_create_note():
    c = request.get_json().get('content', '')
    if not c: return jsonify({'error': 'Empty'}), 400
    nid = str(uuid.uuid4()); db.session.add(SecretNote(id=nid, content=c)); db.session.commit()
    return jsonify({'link': request.host_url + 'note/' + nid})

@app.route('/note/<nid>')
def read_note(nid):
    n = db.session.get(SecretNote, nid)
    if not n: return render_template('read-note.html', content=None, error='This note has already been read or does not exist.')
    c = n.content; db.session.delete(n); db.session.commit()
    return render_template('read-note.html', content=c, error=None)

@app.route('/api/file-hash', methods=['POST'])
def api_file_hash():
    try:
        f = request.files['file'].read()
        return jsonify({'md5': hashlib.md5(f).hexdigest(), 'sha256': hashlib.sha256(f).hexdigest()})
    except: return jsonify({'error': 'Error'}), 500

@app.route('/api/pdf-cleaner', methods=['POST'])
def api_pdf_cleaner():
    try:
        import pypdf; reader = pypdf.PdfReader(request.files['file'].stream); writer = pypdf.PdfWriter()
        for page in reader.pages: writer.add_page(page)
        writer.add_metadata({}); b = io.BytesIO(); writer.write(b); b.seek(0)
        return send_file(b, mimetype='application/pdf', as_attachment=True, download_name='clean.pdf')
    except: return jsonify({'error': 'Error'}), 500

@app.route('/api/watermark', methods=['POST'])
def api_watermark():
    try:
        img = Image.open(request.files['image'].stream).convert('RGBA')
        overlay = Image.new('RGBA', img.size, (255,255,255,0))
        d = ImageDraw.Draw(overlay); t = request.form.get('text', 'Watermark'); w, h = img.size
        d.text((w//2 - len(t)*6, h//2), t, fill=(255,255,255,120))
        out = Image.alpha_composite(img, overlay).convert('RGB')
        b = io.BytesIO(); out.save(b, 'PNG'); b.seek(0)
        return send_file(b, mimetype='image/png', as_attachment=True, download_name='watermarked.png')
    except: return jsonify({'error': 'Error'}), 500

@app.route('/api/file-action', methods=['POST'])
def api_file_action():
    try:
        from cryptography.fernet import Fernet; import base64
        f = request.files['file']; action = request.form.get('action')
        if action == 'encrypt':
            k = Fernet.generate_key(); enc = Fernet(k).encrypt(f.read())
            return jsonify({'file_content': base64.b64encode(enc).decode(), 'filename': f.filename + '.locked', 'key': k.decode()})
        k = request.form.get('key', '').strip().encode(); dec = Fernet(k).decrypt(f.read())
        return jsonify({'file_content': base64.b64encode(dec).decode(), 'filename': f.filename.replace('.locked', '')})
    except: return jsonify({'error': 'Invalid key or corrupted file'}), 400

@app.route('/api/login_status', methods=['GET'])
def login_status():
    if current_user.is_authenticated: current_user.ping(); return jsonify({'authenticated': True, 'is_admin': current_user.is_admin}), 200
    return jsonify({'authenticated': False}), 200

# --- INIT ---
with app.app_context():
    db.create_all()
    if not User.query.filter_by(email='admin@toolstresor.com').first():
        db.session.add(User(email='admin@toolstresor.com', is_admin=True, password_hash=generate_password_hash('admin123'))); db.session.commit()
        print("Admin: admin@toolstresor.com / admin123")
    
    if not SiteSetting.query.first(): db.session.add(SiteSetting(maintenance_mode=False)); db.session.commit()

    if not Tool.query.first():
        # 12 Tools Default
        tools = [
            ("Word Counter", "page_word_counter", "Count words", "📝"),
            ("QR Generator", "page_qr_generator", "Create QR codes", "📱"),
            ("Case Converter", "page_case_converter", "Text formatter", "Aa"),
            ("MD5 Generator", "page_md5_generator", "Secure hash", "🔑"),
            ("Password Gen", "page_password_generator", "Secure passwords", "🔐"),
            ("Lorem Ipsum", "page_lorem_ipsum", "Dummy text", "📄"),
            ("What is My IP", "page_my_ip", "IP Finder", "🌐"),
            ("Random Quote", "page_random_quote", "Daily inspiration", "💬"),
            ("Header Checker", "page_header_checker", "HTTP Analysis", "🔍"),
            ("Image Compressor", "page_image_compressor", "Optimize images", "🖼️"),
            ("Steganography", "page_steganography", "Hide secrets", "🕵️‍♂️"),
            ("URL Scanner", "page_url_scanner", "Unshorten links", "🔗"),
            ("Secret Note", "page_secret_note", "Self-destructing notes", "🔥"),
            ("Password Strength", "page_password_strength", "Check password strength", "💪"),
            ("File Hasher", "page_file_hasher", "MD5 & SHA256 hash", "#️⃣"),
            ("Digital Footprint", "page_digital_footprint", "Browser & IP info", "👣"),
            ("PDF Cleaner", "page_pdf_cleaner", "Remove PDF metadata", "📋"),
            ("Watermarker", "page_watermarker", "Add text watermark", "🖋️"),
            ("File Locker", "page_file_locker", "Encrypt & decrypt files", "🔒")
        ]
        for n, r, d, i in tools: db.session.add(Tool(name=n, route_name=r, description=d, icon=i, is_active=True))
        db.session.commit()

@app.errorhandler(404)
def not_found(e): return render_template('404.html'), 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)