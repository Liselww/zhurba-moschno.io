from flask import Flask, render_template, url_for, request, redirect, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import hashlib
from functools import wraps
import os
from PIL import Image
import io

# Декоратор для перевірки прав адміна
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Доступ заборонено! Потрібні права адміністратора.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function




basedir = os.path.abspath(os.path.dirname(__file__))


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-it'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'zhurba_data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Налаштування для аватарок
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads', 'avatars')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

# Налаштування для картинок у постах
app.config['POST_IMAGES_FOLDER'] = os.path.join(basedir, 'static', 'uploads', 'post_images')
# Створюємо папку, якщо її немає
os.makedirs(app.config['POST_IMAGES_FOLDER'], exist_ok=True)

# Створюємо папки якщо їх немає
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(basedir, 'static', 'avatars'), exist_ok=True)

db = SQLAlchemy(app)

# Налаштування Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Будь ласка, увійдіть для доступу до цієї сторінки"
login_manager.login_message_category = "info"

# Функція перевірки розширення файлу
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# --- МОДЕЛЬ КОРИСТУВАЧА ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    date_registered = db.Column(db.DateTime, default=datetime.utcnow)
    avatar_path = db.Column(db.String(200), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    
    # Зв'язки
    articles = db.relationship('Article', backref='author', lazy=True, cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='author', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def avatar(self, size=100):
        """Повертає URL аватарки"""
        try:
            if self.avatar_path:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], self.avatar_path)
                if os.path.exists(file_path):
                    return url_for('static', filename=f'uploads/avatars/{self.avatar_path}')
                else:
                    self.avatar_path = None
                    db.session.commit()
            
            if self.email:
                email_hash = hashlib.md5(self.email.lower().encode('utf-8')).hexdigest()
                return f"https://www.gravatar.com/avatar/{email_hash}?s={size}&d=identicon"
            
            return url_for('static', filename='avatars/default.png')
        except Exception as e:
            print(f"Помилка avatar(): {e}")
            return url_for('static', filename='avatars/default.png')

    def __repr__(self):
        return f'<User {self.username}>'

# --- МОДЕЛЬ СТАТТІ ---
class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    intro = db.Column(db.String(300), nullable=False)
    text = db.Column(db.Text, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Зв'язок з коментарями
    comments = db.relationship('Comment', backref='article', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Article {self.title}>'

# --- МОДЕЛЬ КОМЕНТАРЯ ---
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False)

    def __repr__(self):
        return f'<Comment {self.id}>'


class PostImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)  # Унікальне ім'я файлу
    post_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)

    # Зв'язок з постом (один пост може мати багато картинок)
    post = db.relationship('Article', backref='images', lazy=True)

    def __repr__(self):
        return f'<PostImage {self.filename}>'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- МАРШРУТИ ДЛЯ КОМЕНТАРІВ ---
@app.route('/posts/<int:article_id>/comment', methods=['POST'])
@login_required
def add_comment(article_id):
    """Додати коментар до статті"""
    article = Article.query.get_or_404(article_id)
    text = request.form.get('text')
    
    if not text or text.strip() == '':
        flash('Коментар не може бути порожнім', 'danger')
        return redirect(url_for('post_detail', id=article_id))
    
    comment = Comment(
        text=text.strip(),
        user_id=current_user.id,
        article_id=article_id
    )
    
    try:
        db.session.add(comment)
        db.session.commit()
        flash('Коментар додано!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Помилка при додаванні коментаря', 'danger')
        print(f"Помилка: {e}")
    
    return redirect(url_for('post_detail', id=article_id) + '#comments')


@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    """Видалити коментар"""
    comment = Comment.query.get_or_404(comment_id)
    
    # Перевірка прав
    if (current_user.id == comment.user_id or 
        current_user.id == comment.article.user_id or 
        current_user.is_admin):
        
        article_id = comment.article_id
        try:
            db.session.delete(comment)
            db.session.commit()
            flash('Коментар видалено', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Помилка при видаленні коментаря', 'danger')
            print(f"Помилка: {e}")
    else:
        flash('У вас немає прав на видалення цього коментаря', 'danger')
        article_id = comment.article_id
    
    return redirect(url_for('post_detail', id=article_id) + '#comments')


@app.route('/comment/<int:comment_id>/edit', methods=['POST'])
@login_required
def edit_comment(comment_id):
    """Редагувати коментар"""
    comment = Comment.query.get_or_404(comment_id)
    
    if current_user.id != comment.user_id:
        flash('Ви не можете редагувати цей коментар', 'danger')
        return redirect(url_for('post_detail', id=comment.article_id))
    
    text = request.form.get('text')
    if not text or text.strip() == '':
        flash('Коментар не може бути порожнім', 'danger')
    else:
        try:
            comment.text = text.strip()
            db.session.commit()
            flash('Коментар оновлено', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Помилка при редагуванні коментаря', 'danger')
            print(f"Помилка: {e}")
    
    return redirect(url_for('post_detail', id=comment.article_id) + '#comments')


# --- МАРШРУТ ДЛЯ ЗМІНИ АВАТАРКИ ---
@app.route('/change-avatar', methods=['POST'])
@login_required
def change_avatar():
    try:
        if 'avatar' not in request.files:
            flash('Файл не вибрано', 'danger')
            return redirect(url_for('profile'))
        
        file = request.files['avatar']
        
        if file.filename == '':
            flash('Файл не вибрано', 'danger')
            return redirect(url_for('profile'))
        
        if file and allowed_file(file.filename):
            img_data = file.read()
            
            try:
                img = Image.open(io.BytesIO(img_data))
                
                # Конвертуємо в RGB
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    if img.mode == 'RGBA':
                        background.paste(img, mask=img.split()[-1])
                    else:
                        background.paste(img)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                img.thumbnail((200, 200))
                
                new_filename = f"user_{current_user.id}_{int(datetime.now().timestamp())}.jpg"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                
                img.save(filepath, 'JPEG', quality=90, optimize=True)
                
                if current_user.avatar_path:
                    old_avatar = os.path.join(app.config['UPLOAD_FOLDER'], current_user.avatar_path)
                    if os.path.exists(old_avatar):
                        os.remove(old_avatar)
                
                current_user.avatar_path = new_filename
                db.session.commit()
                
                flash('Аватарку успішно змінено!', 'success')
                
            except Exception as e:
                flash(f'Файл пошкоджений: {str(e)}', 'danger')
                print(f"Помилка: {e}")
        else:
            flash('Дозволені тільки: PNG, JPG, JPEG, GIF', 'danger')
    
    except Exception as e:
        flash(f'Помилка: {str(e)}', 'danger')
        print(f"Помилка: {e}")
    
    return redirect(url_for('profile'))


@app.route('/use-gravatar', methods=['POST'])
@login_required
def use_gravatar():
    try:
        if current_user.avatar_path:
            old_avatar = os.path.join(app.config['UPLOAD_FOLDER'], current_user.avatar_path)
            if os.path.exists(old_avatar):
                os.remove(old_avatar)
        
        current_user.avatar_path = None
        db.session.commit()
        flash('Тепер використовується Gravatar!', 'success')
    except Exception as e:
        flash(f'Помилка: {str(e)}', 'danger')
        print(f"Помилка: {e}")
    
    return redirect(url_for('profile'))


# --- МАРШРУТИ АВТОРИЗАЦІЇ ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Паролі не співпадають!', 'danger')
            return render_template('register.html')

        if User.query.filter_by(username=username).first():
            flash('Користувач з таким іменем вже існує!', 'danger')
            return render_template('register.html')

        if User.query.filter_by(email=email).first():
            flash('Користувач з таким email вже існує!', 'danger')
            return render_template('register.html')

        new_user = User(username=username, email=email)
        new_user.set_password(password)

        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Реєстрація успішна!', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Сталася помилка при реєстрації', 'danger')
            print(e)

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        remember = True if request.form.get('remember') else False

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user, remember=remember)
            flash(f'Ласкаво просимо, {user.username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Неправильне ім\'я користувача або пароль', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Ви вийшли з системи', 'info')
    return redirect(url_for('index'))


@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)


# --- ОСНОВНІ МАРШРУТИ ---
@app.route('/')
@app.route('/home')
def index():
    return render_template("index.html")


@app.route('/about')
def about():
    return render_template("about.html")


@app.route('/posts')
def posts():
    articles = Article.query.order_by(Article.date.desc()).all()
    return render_template("posts.html", articles=articles)


@app.route('/posts/<int:id>')
def post_detail(id):
    article = Article.query.get_or_404(id)
    return render_template("post_detail.html", article=article)


@app.route('/create-article', methods=['POST', 'GET'])
@login_required
def create_article():
    if request.method == "POST":
        title = request.form['title']
        intro = request.form['intro']
        text = request.form['text']

        # 1. Спочатку створюємо і зберігаємо пост, щоб отримати його ID
        article = Article(
            title=title,
            intro=intro,
            text=text,
            user_id=current_user.id
        )
        db.session.add(article)
        db.session.flush()  # Отримуємо ID для article, щоб використати його далі

        # 2. Обробка завантажених картинок
        uploaded_files = request.files.getlist('images')  # Отримуємо список файлів
        saved_images = []

        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                # Генеруємо унікальне ім'я файлу
                ext = file.filename.rsplit('.', 1)[1].lower()
                # Формат: post_{post_id}_{timestamp}.jpg
                filename = f"post_{article.id}_{int(datetime.now().timestamp())}_{len(saved_images)}.{ext}"
                filepath = os.path.join(app.config['POST_IMAGES_FOLDER'], filename)

                # Зберігаємо файл
                file.save(filepath)

                # (Опціонально) Оптимізація зображення за допомогою Pillow
                try:
                    img = Image.open(filepath)
                    # Змінюємо розмір, якщо картинка завелика, наприклад, максимум 1200px по ширині
                    if img.width > 1200:
                        ratio = 1200.0 / img.width
                        new_height = int(img.height * ratio)
                        img = img.resize((1200, new_height), Image.LANCZOS)
                        img.save(filepath, optimize=True, quality=85)
                except Exception as e:
                    print(f"Помилка оптимізації зображення {filename}: {e}")

                # Створюємо запис у базі даних для цієї картинки
                post_image = PostImage(filename=filename, post_id=article.id)
                db.session.add(post_image)
                saved_images.append(filename)

        try:
            # Зберігаємо всі зміни (пост + картинки)
            db.session.commit()
            flash(f'Статтю та {len(saved_images)} зображень успішно створено!', 'success')
            return redirect('/posts')
        except Exception as e:
            db.session.rollback()
            # Якщо помилка, видаляємо завантажені файли, щоб не засмічувати сервер
            for filename in saved_images:
                filepath = os.path.join(app.config['POST_IMAGES_FOLDER'], filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
            flash('Помилка при збереженні статті', 'danger')
            print(e)

    return render_template("create_article.html")


@app.route('/posts/<int:id>/delete', methods=['POST'])
@login_required
def post_delete(id):
    article = Article.query.get_or_404(id)
    
    if article.user_id != current_user.id and not current_user.is_admin:
        flash('Ви не можете видалити чужу статтю!', 'danger')
        return redirect(url_for('posts'))
    
    try:
        db.session.delete(article)
        db.session.commit()
        flash('Статтю видалено!', 'success')
    except Exception as e:
        flash('Помилка при видаленні', 'danger')
        print(e)
    
    return redirect('/posts')


@app.route('/posts/<int:id>/update', methods=['POST', 'GET'])
@login_required
def post_update(id):
    article = Article.query.get_or_404(id)
    
    if article.user_id != current_user.id and not current_user.is_admin:
        flash('Ви не можете редагувати чужу статтю!', 'danger')
        return redirect(url_for('posts'))
    
    if request.method == "POST":
        article.title = request.form['title']
        article.intro = request.form['intro']
        article.text = request.form['text']
        
        try:
            db.session.commit()
            flash('Статтю оновлено!', 'success')
            return redirect(url_for('post_detail', id=article.id))
        except Exception as e:
            flash('Помилка при оновленні', 'danger')
            print(e)
    
    return render_template("post_update.html", article=article)


@app.route('/news')
def news():
    return render_template("news.html")


@app.route('/user/<int:user_id>')
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('user_profile.html', user=user)


@app.route('/search-users')
def search_users():
    query = request.args.get('q', '')
    
    if query:
        users = User.query.filter(
            (User.username.contains(query)) | 
            (User.email.contains(query))
        ).order_by(User.username).all()
    else:
        users = []
    
    return render_template('search_users.html', users=users, query=query)


@app.route('/users')
def all_users():
    page = request.args.get('page', 1, type=int)
    users = User.query.order_by(User.username).paginate(page=page, per_page=12)
    return render_template('all_users.html', users=users)





# --- АДМІН-ПАНЕЛЬ ---
@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    users_count = User.query.count()
    articles_count = Article.query.count()
    new_users_today = User.query.filter(
        User.date_registered >= datetime.now().replace(hour=0, minute=0, second=0)
    ).count()
    
    return render_template('admin/index.html',
                         users_count=users_count,
                         articles_count=articles_count,
                         new_users_today=new_users_today)


@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    try:
        users = User.query.order_by(User.date_registered.desc()).all()
        return render_template('admin/users.html', users=users)
    except Exception as e:
        print(f"Помилка: {e}")
        flash(f'Помилка завантаження користувачів', 'danger')
        return redirect(url_for('admin_panel'))


@app.route('/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def admin_toggle_admin(user_id):
    if user_id == current_user.id:
        flash('Ви не можете змінити власні права адміна!', 'warning')
        return redirect(url_for('admin_users'))
    
    user = User.query.get_or_404(user_id)
    user.is_admin = not user.is_admin
    db.session.commit()
    
    status = "призначено адміном" if user.is_admin else "знято з адмінів"
    flash(f'Користувача {user.username} {status}', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    if user_id == current_user.id:
        flash('Ви не можете видалити самого себе!', 'warning')
        return redirect(url_for('admin_users'))
    
    user = User.query.get_or_404(user_id)
    username = user.username
    
    try:
        if user.avatar_path and user.avatar_path != 'default.png':
            avatar_path = os.path.join(app.config['UPLOAD_FOLDER'], user.avatar_path)
            if os.path.exists(avatar_path):
                os.remove(avatar_path)
        
        db.session.delete(user)
        db.session.commit()
        flash(f'Користувача {username} видалено', 'success')
    except Exception as e:
        flash('Помилка при видаленні', 'danger')
        print(e)
    
    return redirect(url_for('admin_users'))


@app.route('/admin/articles')
@login_required
@admin_required
def admin_articles():
    articles = Article.query.order_by(Article.date.desc()).all()
    return render_template('admin/articles.html', articles=articles)


@app.route('/admin/articles/<int:article_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_article(article_id):
    article = Article.query.get_or_404(article_id)
    title = article.title
    
    db.session.delete(article)
    db.session.commit()
    
    flash(f'Статтю "{title}" видалено', 'success')
    return redirect(url_for('admin_articles'))


# --- ДІАГНОСТИКА ---
@app.route('/debug-paths')
def debug_paths():
    result = "<h1>Діагностика шляхів</h1>"
    result += f"<p><b>basedir:</b> {basedir}</p>"
    result += f"<p><b>UPLOAD_FOLDER:</b> {app.config['UPLOAD_FOLDER']}</p>"
    result += f"<p><b>UPLOAD_FOLDER exists:</b> {os.path.exists(app.config['UPLOAD_FOLDER'])}</p>"
    return result


# --- ФУНКЦІЇ ДЛЯ СТВОРЕННЯ ПОЧАТКОВИХ ДАНИХ ---
def create_default_avatar():
    default_avatar_path = os.path.join(basedir, 'static', 'avatars', 'default.png')
    
    if not os.path.exists(default_avatar_path):
        try:
            img = Image.new('RGB', (200, 200), color=(100, 100, 100))
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.ellipse([50, 50, 150, 150], fill=(150, 150, 150))
            img.save(default_avatar_path)
            print("✅ Стандартну аватарку створено")
        except Exception as e:
            print(f"❌ Помилка створення аватарки: {e}")


def create_first_admin():
    try:
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@zhurba.com',
                is_admin=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✅ Адміна створено: admin / admin123")
        else:
            print("✅ Адмін вже існує")
    except Exception as e:
        print(f"⚠️ Помилка при створенні адміна: {e}")


@app.route('/zhurba-songs')
def zhurba_songs():
    return render_template("zhurba-songs.html")


@app.route('/download/<int:song_id>')
def download_song(song_id):
    songs = {
        1: 'zhurba_song.mp3',
        2: 'zhurba_song2.mp3',
        3: 'zhurba_song3.mp3'
    }
    
    if song_id in songs:
        return send_from_directory('static', f'music/{songs[song_id]}', 
                                  as_attachment=True, 
                                  download_name=songs[song_id])
    else:
        flash('Пісня не знайдена', 'danger')
        return redirect(url_for('zhurba_songs'))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        print("✅ Таблиці створено")
        create_default_avatar()
        create_first_admin()
        
    app.run(debug=True)