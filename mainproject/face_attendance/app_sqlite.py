import cv2
import os
import datetime
import sqlite3
import numpy as np
import time
import hashlib
import functools
try:
    import face_recognition  # For more accurate face recognition
except ImportError:
    print("face_recognition library not found. Using fallback methods.")
    face_recognition = None
from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, jsonify

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'smart_drishti_secret_key'

# SQLite Database path
DB_PATH = 'face_attendance.db'

# Ensure directory for storing student face images exists
UPLOAD_FOLDER = 'static/faces'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize face detector
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

# Database helper functions
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # This enables column access by name like dict
    return conn

def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if the database already has tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='students'")
    table_exists = cursor.fetchone() is not None
    
    if not table_exists:
        print("Initializing database with default schema and data...")
        
        # Create tables with new structure
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department TEXT NOT NULL
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS main_subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            class_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS elective_subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            class_id INTEGER NOT NULL,
            FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            roll_number TEXT NOT NULL UNIQUE,
            class_id INTEGER NOT NULL,
            elective_subject_id INTEGER,
            image_path TEXT,
            FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE,
            FOREIGN KEY (elective_subject_id) REFERENCES elective_subjects(id) ON DELETE SET NULL
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            subject_type TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        ''')
        
        # Add table for storing group photos
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            subject_type TEXT NOT NULL,
            date TEXT NOT NULL,
            photo_path TEXT NOT NULL,
            annotated_path TEXT,
            faces_detected INTEGER DEFAULT 0,
            students_recognized INTEGER DEFAULT 0,
            FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
        )
        ''')
        
        # Add MCA and MBA departments
        cursor.execute("INSERT INTO classes (name, department) VALUES (?, ?)", ("MCA", "MCA"))
        cursor.execute("INSERT INTO classes (name, department) VALUES (?, ?)", ("MBA", "MBA"))
        
        # Get MCA class ID
        cursor.execute("SELECT id FROM classes WHERE name = 'MCA'")
        mca_id = cursor.fetchone()[0]
        
        # Add main subjects for MCA
        main_subjects = ["Java", "Optimizing Techniques", "Research Methodology", "Software Testing"]
        for subject in main_subjects:
            cursor.execute("INSERT INTO main_subjects (name, class_id) VALUES (?, ?)", (subject, mca_id))
        
        # Add elective subjects for MCA
        elective_subjects = ["Full Stack", "Cloud Computing", "Cyber Security", "Data Science"]
        for subject in elective_subjects:
            cursor.execute("INSERT INTO elective_subjects (name, class_id) VALUES (?, ?)", (subject, mca_id))
        
        # Add users table for authentication
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        ''')
        
        # Add default admin user (username: admin, password: admin123)
        password_hash = hashlib.sha256('admin123'.encode()).hexdigest()
        cursor.execute(
            "INSERT INTO users (username, password_hash, name, role, created_at) VALUES (?, ?, ?, ?, ?)",
            ('admin', password_hash, 'Administrator', 'admin', datetime.datetime.now().isoformat())
        )
        
        conn.commit()
        print("Database initialized successfully.")
    else:
        # Check if we need to add the attendance_photos table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attendance_photos'")
        photos_table_exists = cursor.fetchone() is not None
        
        if not photos_table_exists:
            print("Adding attendance_photos table...")
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                subject_type TEXT NOT NULL,
                date TEXT NOT NULL,
                photo_path TEXT NOT NULL,
                annotated_path TEXT,
                faces_detected INTEGER DEFAULT 0,
                students_recognized INTEGER DEFAULT 0,
                FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
            )
            ''')
            conn.commit()
            print("Added attendance_photos table.")
        else:
            # Check if we need to add the users table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            users_table_exists = cursor.fetchone() is not None
            
            if not users_table_exists:
                print("Adding users table...")
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                ''')
                
                # Add default admin user
                password_hash = hashlib.sha256('admin123'.encode()).hexdigest()
                cursor.execute(
                    "INSERT INTO users (username, password_hash, name, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    ('admin', password_hash, 'Administrator', 'admin', datetime.datetime.now().isoformat())
                )
                conn.commit()
                print("Added users table with default admin user.")
            else:
                print("Database already exists, skipping initialization.")
    
    cursor.close()
    conn.close()

# Initialize the database when the app starts
init_database()

# Login required decorator
def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page', 'warning')
            return redirect(url_for('login', next=request.url))
        return view(**kwargs)
    return wrapped_view

# Admin required decorator
def admin_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page', 'warning')
            return redirect(url_for('login', next=request.url))
        
        if session.get('user_role') != 'admin':
            flash('You do not have permission to access this page', 'danger')
            return redirect(url_for('index'))
            
        return view(**kwargs)
    return wrapped_view

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if user and user['password_hash'] == hashlib.sha256(password.encode()).hexdigest():
            # Store user info in session
            session.clear()
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_role'] = user['role']
            
            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('index')
                
            flash(f'Welcome back, {user["name"]}!', 'success')
            return redirect(next_page)
        
        flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

# Logout route
@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))

# User management routes
@app.route('/users')
@admin_required
def users():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, username, name, role, created_at FROM users ORDER BY id')
    users = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('users.html', users=users)

@app.route('/add_user', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        name = request.form['name']
        role = request.form['role']
        
        # Basic validation
        if not username or not password or not name or not role:
            flash('All fields are required', 'danger')
            return redirect(url_for('add_user'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Check if username already exists
            cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                flash('Username already exists', 'danger')
                return redirect(url_for('add_user'))
            
            # Hash password and create user
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            cursor.execute(
                "INSERT INTO users (username, password_hash, name, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (username, password_hash, name, role, datetime.datetime.now().isoformat())
            )
            conn.commit()
            flash('User added successfully', 'success')
            return redirect(url_for('users'))
        except Exception as e:
            flash(f'Error adding user: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()
    
    return render_template('add_user.html')

# Protected routes with login_required decorator
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/students')
@login_required
def students():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all students with their class name and elective subject
    cursor.execute('''
    SELECT s.*, c.name as class_name, e.name as elective_subject 
    FROM students s 
    JOIN classes c ON s.class_id = c.id
    LEFT JOIN elective_subjects e ON s.elective_subject_id = e.id
    ''')
    
    students = cursor.fetchall()
    
    # Get all classes for the add student form
    cursor.execute("SELECT * FROM classes")
    classes = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('students.html', students=students, classes=classes)

@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if request.method == 'POST':
        name = request.form['name']
        roll_number = request.form['roll_number']
        class_id = request.form['class_id']
        elective_subject_id = request.form.get('elective_subject_id')
        
        # Check if a face image was uploaded
        if 'face_image' not in request.files:
            flash('No face image provided', 'danger')
            return redirect(request.url)
        
        file = request.files['face_image']
        
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        
        if file:
            # Save the image
            filename = f"{roll_number}.jpg"
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
            
            # Detect if there is a face in the image
            img = cv2.imread(file_path)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            
            if len(faces) == 0:
                # No face detected
                os.remove(file_path)
                flash('No face detected in the image. Please upload a clear face image.', 'danger')
                return redirect(request.url)
            
            # If a face is detected, save to database
            conn = get_db_connection()
            cursor = conn.cursor()
            
            try:
                cursor.execute(
                    "INSERT INTO students (name, roll_number, class_id, elective_subject_id, image_path) VALUES (?, ?, ?, ?, ?)",
                    (name, roll_number, class_id, elective_subject_id, file_path)
                )
                conn.commit()
                flash('Student added successfully!', 'success')
            except sqlite3.IntegrityError:
                flash('Roll number already exists!', 'danger')
            finally:
                cursor.close()
                conn.close()
                
            return redirect(url_for('students'))
    
    # If GET request or form submission failed
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all classes
    cursor.execute("SELECT * FROM classes")
    classes = cursor.fetchall()
    
    # Get all elective subjects
    cursor.execute("SELECT * FROM elective_subjects")
    elective_subjects = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('add_student.html', classes=classes, elective_subjects=elective_subjects)

@app.route('/take_attendance')
def take_attendance():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all classes
    cursor.execute("SELECT * FROM classes")
    classes = cursor.fetchall()
    
    # Get all main subjects
    cursor.execute("SELECT * FROM main_subjects")
    main_subjects = cursor.fetchall()
    
    # Get all elective subjects
    cursor.execute("SELECT * FROM elective_subjects")
    elective_subjects = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('take_attendance.html', 
                          classes=classes, 
                          main_subjects=main_subjects,
                          elective_subjects=elective_subjects)

def detect_faces_in_frame(frame, class_id, subject_id=None, subject_type=None):
    # Check if frame is empty or None
    if frame is None or frame.size == 0:
        # Return an error frame
        error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(error_frame, "Invalid camera frame", (50, 240), 
                  cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        return error_frame
    
    # Create a copy of the frame to avoid modifying the original
    display_frame = frame.copy()
    
    # Convert to grayscale
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # Apply some preprocessing to improve face detection
    # Equalize histogram for better contrast
    gray = cv2.equalizeHist(gray)
    
    # Use multiple face detection approaches for better reliability
    # 1. Standard Haar Cascade
    faces_haar = face_cascade.detectMultiScale(
        gray, 
        scaleFactor=1.1, 
        minNeighbors=5, 
        minSize=(30, 30),
        flags=cv2.CASCADE_SCALE_IMAGE
    )
    
    # If no faces detected with Haar, try with different parameters
    if len(faces_haar) == 0:
        faces_haar = face_cascade.detectMultiScale(
            gray, 
            scaleFactor=1.05, 
            minNeighbors=3, 
            minSize=(20, 20)
        )
    
    # Choose the detection result with more faces
    faces = faces_haar
    
    # Check if subject information is provided
    if subject_id is None or subject_type is None:
        cv2.putText(display_frame, "Subject not selected correctly", 
                  (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        return display_frame
    
    # Get students from the selected class with correct subject enrollment
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if subject_type == 'main':
        # For main subjects, get all students in the class (all take main subjects)
        cursor.execute("SELECT * FROM students WHERE class_id = ?", (class_id,))
        students = cursor.fetchall()
        student_count = len(students)
    else:
        # For elective subjects, only get students who have chosen this elective
        cursor.execute("SELECT * FROM students WHERE class_id = ? AND elective_subject_id = ?", 
                     (class_id, subject_id))
        students = cursor.fetchall()
        student_count = len(students)
        
        # Also get total student count for context
        cursor.execute("SELECT COUNT(*) as count FROM students WHERE class_id = ?", (class_id,))
        total_class_students = cursor.fetchone()['count']
    
    # Load student face images for comparison
    student_faces = []
    for student in students:
        if student['image_path'] and os.path.exists(student['image_path']):
            try:
                student_img = cv2.imread(student['image_path'])
                if student_img is not None:
                    student_faces.append({
                        'id': student['id'],
                        'name': student['name'],
                        'roll_number': student['roll_number'],
                        'image': student_img
                    })
            except Exception as e:
                print(f"Error loading student image: {str(e)}")
    
    # Set flag for unregistered faces
    unregistered_face_detected = False
    recognized_students = []
    
    # Mark attendance for detected faces
    if len(faces) > 0 and len(student_faces) > 0:
        today = datetime.date.today().isoformat()
        now = datetime.datetime.now().time().isoformat()
        
        # Process each detected face
        for (x, y, w, h) in faces:
            # Extract the face ROI (Region of Interest)
            face_roi = gray[y:y+h, x:x+w]
            
            # Resize the face for better comparison
            face_roi = cv2.resize(face_roi, (100, 100))
            
            # Best match variables
            best_match_score = float('inf')
            best_match_student = None
            
            # Compare with each student's face
            for student in student_faces:
                try:
                    # Process student image
                    student_gray = cv2.cvtColor(student['image'], cv2.COLOR_BGR2GRAY)
                    student_gray = cv2.equalizeHist(student_gray)
                    
                    # Detect faces in student image
                    student_faces_detected = face_cascade.detectMultiScale(
                        student_gray, 
                        scaleFactor=1.1, 
                        minNeighbors=5, 
                        minSize=(30, 30)
                    )
                    
                    if len(student_faces_detected) > 0:
                        # Get the first face
                        sx, sy, sw, sh = student_faces_detected[0]
                        student_face_roi = student_gray[sy:sy+sh, sx:sx+sw]
                        student_face_roi = cv2.resize(student_face_roi, (100, 100))
                        
                        # Compare the faces using Mean Squared Error (MSE)
                        err = np.sum((face_roi.astype("float") - student_face_roi.astype("float")) ** 2)
                        err /= float(face_roi.shape[0] * face_roi.shape[1])
                        
                        # Update best match if this is better
                        if err < best_match_score:
                            best_match_score = err
                            best_match_student = student
                except Exception as e:
                    print(f"Error comparing face: {str(e)}")
            
            # If we found a good match (lower MSE is better)
            match_threshold = 2000  # Adjust this threshold based on testing
            if best_match_student and best_match_score < match_threshold:
                # Draw green rectangle and label with student name
                cv2.rectangle(display_frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                label = f"{best_match_student['name']} ({best_match_student['roll_number']})"
                cv2.putText(display_frame, label, (x, y-10), 
                          cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                
                # Add to recognized students if not already there
                if best_match_student['id'] not in recognized_students:
                    recognized_students.append(best_match_student['id'])
            else:
                # Unregistered or unrecognized face
                cv2.rectangle(display_frame, (x, y), (x+w, y+h), (0, 0, 255), 2)
                cv2.putText(display_frame, "Unknown", (x, y-10), 
                          cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                unregistered_face_detected = True
        
        # Mark attendance only for recognized students
        if len(recognized_students) > 0:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            for student_id in recognized_students:
                cursor.execute(
                    "SELECT * FROM attendance WHERE student_id = ? AND date = ? AND subject_id = ? AND subject_type = ?",
                    (student_id, today, subject_id, subject_type)
                )
                
                if cursor.fetchone() is None:
                    cursor.execute(
                        "INSERT INTO attendance (student_id, subject_id, subject_type, date, time, status) VALUES (?, ?, ?, ?, ?, ?)",
                        (student_id, subject_id, subject_type, today, now, 'present')
                    )
            
            conn.commit()
            cursor.close()
            conn.close()
    
    cursor.close()
    conn.close()
    
    # Draw rectangle around faces and show unregistered message if needed
    if len(faces) > 0:
        # Show message for unregistered faces
        if unregistered_face_detected:
            cv2.putText(display_frame, "Unregistered face detected! Please register first.", 
                      (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        # Show success message when faces are recognized
        if len(recognized_students) > 0:
            msg = f"Recognized {len(recognized_students)} students!"
            cv2.putText(display_frame, msg, 
                      (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            if subject_type == 'elective':
                cv2.putText(display_frame, f"Enrolled students: {student_count}/{total_class_students}", 
                          (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    else:
        # No faces detected message
        cv2.putText(display_frame, "No faces detected. Please ensure your face is visible.", 
                  (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    
    return display_frame

@app.route('/video_feed/<int:class_id>')
def video_feed(class_id):
    # Get subject info from session at request time
    subject_id = session.get('subject_id')
    subject_type = session.get('subject_type')
    
    def generate_frames():
        print("Starting camera initialization...")
        
        # Store the subject info from the request context
        current_subject_id = subject_id
        current_subject_type = subject_type
        
        # On Windows, try DirectShow as the first option
        if os.name == 'nt':  # Windows
            print("Detected Windows OS, trying DirectShow first...")
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        else:
            # For other platforms, start with default
            cap = cv2.VideoCapture(0)
        
        # Check if camera opened successfully
        if cap is None or not cap.isOpened():
            print("Initial camera access failed, trying alternative methods...")
            
            # Try multiple camera indices
            for idx in [0, 1, -1]:
                for api in [cv2.CAP_ANY, cv2.CAP_DSHOW, cv2.CAP_V4L2, cv2.CAP_MSMF]:
                    try:
                        print(f"Trying camera index {idx} with API {api}...")
                        cap = cv2.VideoCapture(idx, api)
                        if cap is not None and cap.isOpened():
                            print(f"Success with camera index {idx} and API {api}")
                            break
                    except Exception as e:
                        print(f"Error with camera index {idx} and API {api}: {str(e)}")
                        continue
                
                if cap is not None and cap.isOpened():
                    break
        
        # If camera access failed, use fallback
        if cap is None or not cap.isOpened():
            print("All camera access methods failed. Using fallback mode.")
            # Redirect to fallback feed
            for _ in range(3):  # Send a few frames to redirect
                error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(error_frame, "Camera initialization failed", (50, 200), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                cv2.putText(error_frame, "Switching to fallback mode...", (50, 250), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                
                ret, buffer = cv2.imencode('.jpg', error_frame)
                error_frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + error_frame_bytes + b'\r\n')
            
            # Return early to trigger fallback on client side
            return
        
        # If we reached here, camera is working
        print("Camera initialized successfully!")
        
        # Set camera properties for better quality
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        
        try:
            # Read and discard a few initial frames to let camera adjust
            for _ in range(5):
                cap.read()
            
            # Main video loop
            frame_count = 0
            while True:
                success, frame = cap.read()
                if not success:
                    print(f"Failed to read frame after {frame_count} frames")
                    # Try to reinitialize camera
                    cap.release()
                    cap = cv2.VideoCapture(0)
                    if not cap.isOpened():
                        break
                    continue
                
                frame_count += 1
                if frame_count % 30 == 0:  # Log every 30 frames
                    print(f"Successfully read {frame_count} frames")
                
                # Process the frame to detect faces and mark attendance
                try:
                    processed_frame = detect_faces_in_frame(frame, class_id, subject_id, subject_type)
                except Exception as e:
                    print(f"Error in face detection: {str(e)}")
                    # Use original frame on error
                    processed_frame = frame
                
                # Convert to jpeg format
                try:
                    ret, buffer = cv2.imencode('.jpg', processed_frame)
                    if not ret:
                        print("Failed to encode frame to JPEG")
                        continue
                        
                    processed_frame = buffer.tobytes()
                    
                    yield (b'--frame\r\n'
                          b'Content-Type: image/jpeg\r\n\r\n' + processed_frame + b'\r\n')
                except Exception as e:
                    print(f"Error encoding frame: {str(e)}")
                    continue
                
        except Exception as e:
            print(f"Error in video stream: {str(e)}")
        finally:
            # Always release the camera when done
            if cap is not None:
                print("Releasing camera...")
                cap.release()
                print("Camera released")
    
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/process_attendance', methods=['POST'])
def process_attendance():
    # Check if class_id is in the form data
    if 'class_id' not in request.form or not request.form['class_id']:
        flash('Error: Class ID is required for attendance', 'danger')
        return redirect(url_for('take_attendance'))
    
    class_id = request.form['class_id']
    subject_id = request.form.get('subject_id')
    subject_type = session.get('subject_type')
    
    if not subject_id or not subject_type:
        flash('Error: Subject information is missing', 'danger')
        return redirect(url_for('take_attendance'))
    
    # Get class name
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM classes WHERE id = ?", (class_id,))
    class_result = cursor.fetchone()
    
    if not class_result:
        flash('Error: Invalid class selected', 'danger')
        return redirect(url_for('take_attendance'))
    
    class_name = class_result['name']
    
    # Get subject name
    if subject_type == 'main':
        cursor.execute("SELECT name FROM main_subjects WHERE id = ?", (subject_id,))
    else:
        cursor.execute("SELECT name FROM elective_subjects WHERE id = ?", (subject_id,))
    
    subject_result = cursor.fetchone()
    if not subject_result:
        flash('Error: Invalid subject selected', 'danger')
        return redirect(url_for('take_attendance'))
    
    subject_name = subject_result['name']
    
    # Get today's attendance for this class and subject
    today = datetime.date.today().isoformat()
    cursor.execute('''
    SELECT s.id, s.name, s.roll_number, a.status
    FROM students s
    LEFT JOIN attendance a ON s.id = a.student_id AND a.date = ? AND a.subject_id = ? AND a.subject_type = ?
    WHERE s.class_id = ?
    ''', (today, subject_id, subject_type, class_id))
    
    attendance_results = cursor.fetchall()
    
    # Count present students
    present_count = 0
    for student in attendance_results:
        if student['status'] == 'present':
            present_count += 1
    
    cursor.close()
    conn.close()
    
    return render_template('attendance_result.html', 
                          class_name=class_name,
                          subject_name=subject_name,
                          subject_type=subject_type,
                          date=datetime.datetime.today().strftime("%B %d, %Y"),
                          attendance_results=attendance_results,
                          present_count=present_count,
                          total_count=len(attendance_results))

@app.route('/view_attendance')
def view_attendance():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all classes
    cursor.execute("SELECT * FROM classes")
    classes = cursor.fetchall()
    
    # Get all main subjects
    cursor.execute("SELECT * FROM main_subjects")
    main_subjects = cursor.fetchall()
    
    # Get all elective subjects
    cursor.execute("SELECT * FROM elective_subjects")
    elective_subjects = cursor.fetchall()
    
    # Get distinct dates with attendance records
    cursor.execute("SELECT DISTINCT date FROM attendance ORDER BY date DESC")
    dates_raw = cursor.fetchall()
    
    # Convert to datetime objects for the template
    dates = []
    for date_raw in dates_raw:
        date_obj = datetime.datetime.strptime(date_raw['date'], '%Y-%m-%d')
        dates.append({'date': date_obj})
    
    cursor.close()
    conn.close()
    
    return render_template('view_attendance.html', 
                          classes=classes, 
                          main_subjects=main_subjects,
                          elective_subjects=elective_subjects,
                          dates=dates)

@app.route('/attendance_report', methods=['POST'])
def attendance_report():
    class_id = request.form['class_id']
    date = request.form['date']
    subject_id = request.form.get('subject_id')
    subject_type = request.form.get('subject_type')
    
    if not subject_id or not subject_type:
        flash('Error: Subject information is required', 'danger')
        return redirect(url_for('view_attendance'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get class name
    cursor.execute("SELECT name FROM classes WHERE id = ?", (class_id,))
    class_name = cursor.fetchone()['name']
    
    # Get subject name
    if subject_type == 'main':
        cursor.execute("SELECT name FROM main_subjects WHERE id = ?", (subject_id,))
    else:
        cursor.execute("SELECT name FROM elective_subjects WHERE id = ?", (subject_id,))
    
    subject_result = cursor.fetchone()
    if not subject_result:
        flash('Error: Invalid subject selected', 'danger')
        return redirect(url_for('view_attendance'))
    
    subject_name = subject_result['name']
    
    # Get enrollment statistics
    total_class_students = 0
    enrolled_students = 0
    
    # Count total students in class
    cursor.execute("SELECT COUNT(*) as count FROM students WHERE class_id = ?", (class_id,))
    total_class_students = cursor.fetchone()['count']
    
    # Count enrolled students based on subject type
    if subject_type == 'main':
        # All students in the class are enrolled in main subjects
        enrolled_students = total_class_students
    else:
        # Only students who selected this elective are enrolled
        cursor.execute("SELECT COUNT(*) as count FROM students WHERE class_id = ? AND elective_subject_id = ?", 
                     (class_id, subject_id))
        enrolled_students = cursor.fetchone()['count']
    
    # Get attendance for the selected date, class, and subject
    if subject_type == 'main':
        # For main subjects, check attendance for all students in class
        cursor.execute('''
        SELECT s.id, s.name, s.roll_number, a.status
        FROM students s
        LEFT JOIN attendance a ON s.id = a.student_id AND a.date = ? AND a.subject_id = ? AND a.subject_type = ?
        WHERE s.class_id = ?
        ''', (date, subject_id, subject_type, class_id))
    else:
        # For elective subjects, only show students enrolled in this elective
        cursor.execute('''
        SELECT s.id, s.name, s.roll_number, a.status
        FROM students s
        LEFT JOIN attendance a ON s.id = a.student_id AND a.date = ? AND a.subject_id = ? AND a.subject_type = ?
        WHERE s.class_id = ? AND s.elective_subject_id = ?
        ''', (date, subject_id, subject_type, class_id, subject_id))
    
    attendance_results = cursor.fetchall()
    
    # Count present students
    present_count = 0
    for student in attendance_results:
        if student['status'] == 'present':
            present_count += 1
    
    cursor.close()
    conn.close()
    
    formatted_date = datetime.datetime.strptime(date, '%Y-%m-%d').strftime("%B %d, %Y")
    
    return render_template('attendance_report.html', 
                          class_name=class_name,
                          subject_name=subject_name,
                          subject_type=subject_type,
                          class_id=class_id,
                          date=formatted_date,
                          attendance_results=attendance_results,
                          present_count=present_count,
                          total_count=len(attendance_results),
                          total_class_students=total_class_students,
                          enrolled_students=enrolled_students)

@app.route('/delete_student/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get student image path before deletion
    cursor.execute("SELECT image_path FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()
    
    if student and student['image_path']:
        try:
            # Delete the image file if it exists
            if os.path.exists(student['image_path']):
                os.remove(student['image_path'])
        except Exception as e:
            flash(f'Error deleting image: {str(e)}', 'warning')
    
    # Delete student from database
    cursor.execute("DELETE FROM students WHERE id = ?", (student_id,))
    conn.commit()
    
    # Delete associated attendance records
    cursor.execute("DELETE FROM attendance WHERE student_id = ?", (student_id,))
    conn.commit()
    
    cursor.close()
    conn.close()
    
    flash('Student deleted successfully!', 'success')
    return redirect(url_for('students'))

@app.route('/edit_student/<int:student_id>', methods=['GET'])
def edit_student(student_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get the student details
    cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()
    
    if not student:
        cursor.close()
        conn.close()
        flash('Student not found', 'danger')
        return redirect(url_for('students'))
    
    # Get all classes
    cursor.execute("SELECT * FROM classes")
    classes = cursor.fetchall()
    
    # Get all elective subjects
    cursor.execute("SELECT * FROM elective_subjects")
    elective_subjects = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('edit_student.html', student=student, classes=classes, elective_subjects=elective_subjects)

@app.route('/update_student/<int:student_id>', methods=['POST'])
def update_student(student_id):
    name = request.form['name']
    roll_number = request.form['roll_number']
    class_id = request.form['class_id']
    elective_subject_id = request.form.get('elective_subject_id')
    
    # Validate the data
    if not name or not roll_number or not class_id:
        flash('Name, roll number, and class are required fields', 'danger')
        return redirect(url_for('edit_student', student_id=student_id))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if the roll number already exists for another student
    cursor.execute("SELECT id FROM students WHERE roll_number = ? AND id != ?", (roll_number, student_id))
    existing_student = cursor.fetchone()
    
    if existing_student:
        cursor.close()
        conn.close()
        flash('A student with this roll number already exists', 'danger')
        return redirect(url_for('edit_student', student_id=student_id))
    
    # Get current student data before update
    cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    current_student = cursor.fetchone()
    
    # Check if a new face image was uploaded
    if 'face_image' in request.files and request.files['face_image'].filename != '':
        file = request.files['face_image']
        
        # Save the image with the roll number as the filename
        filename = f"{roll_number}.jpg"
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        
        # If roll number changed, delete the old image
        if current_student['roll_number'] != roll_number and os.path.exists(os.path.join(UPLOAD_FOLDER, f"{current_student['roll_number']}.jpg")):
            try:
                os.remove(os.path.join(UPLOAD_FOLDER, f"{current_student['roll_number']}.jpg"))
            except Exception as e:
                flash(f'Error removing old image: {str(e)}', 'warning')
        
        # Save the new image
        file.save(file_path)
        
        # Detect if there is a face in the image
        img = cv2.imread(file_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        
        if len(faces) == 0:
            # No face detected
            os.remove(file_path)
            flash('No face detected in the image. Please upload a clear face image.', 'danger')
            return redirect(url_for('edit_student', student_id=student_id))
        
        # Update with new image path
        cursor.execute(
            "UPDATE students SET name = ?, roll_number = ?, class_id = ?, elective_subject_id = ?, image_path = ? WHERE id = ?",
            (name, roll_number, class_id, elective_subject_id, file_path, student_id)
        )
    else:
        # If roll number changed, rename the existing image file
        if current_student['roll_number'] != roll_number and current_student['image_path']:
            old_path = os.path.join(UPLOAD_FOLDER, f"{current_student['roll_number']}.jpg")
            new_path = os.path.join(UPLOAD_FOLDER, f"{roll_number}.jpg")
            
            if os.path.exists(old_path):
                try:
                    os.rename(old_path, new_path)
                    # Update with new image path
                    cursor.execute(
                        "UPDATE students SET name = ?, roll_number = ?, class_id = ?, elective_subject_id = ?, image_path = ? WHERE id = ?",
                        (name, roll_number, class_id, elective_subject_id, new_path, student_id)
                    )
                except Exception as e:
                    flash(f'Error renaming image file: {str(e)}', 'warning')
                    # Update without changing the image path
                    cursor.execute(
                        "UPDATE students SET name = ?, roll_number = ?, class_id = ?, elective_subject_id = ? WHERE id = ?",
                        (name, roll_number, class_id, elective_subject_id, student_id)
                    )
            else:
                # Update without changing the image path
                cursor.execute(
                    "UPDATE students SET name = ?, roll_number = ?, class_id = ?, elective_subject_id = ? WHERE id = ?",
                    (name, roll_number, class_id, elective_subject_id, student_id)
                )
        else:
            # Update without changing the image path
            cursor.execute(
                "UPDATE students SET name = ?, roll_number = ?, class_id = ?, elective_subject_id = ? WHERE id = ?",
                (name, roll_number, class_id, elective_subject_id, student_id)
            )
    
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Student updated successfully!', 'success')
    return redirect(url_for('students'))

@app.route('/subjects')
def subjects():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all classes
    cursor.execute("SELECT * FROM classes")
    classes = cursor.fetchall()
    
    # Get main subjects with class name
    cursor.execute('''
    SELECT m.*, c.name as class_name
    FROM main_subjects m
    JOIN classes c ON m.class_id = c.id
    ''')
    main_subjects = cursor.fetchall()
    
    # Get elective subjects with class name
    cursor.execute('''
    SELECT e.*, c.name as class_name
    FROM elective_subjects e
    JOIN classes c ON e.class_id = c.id
    ''')
    elective_subjects = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('subjects.html', 
                          classes=classes, 
                          main_subjects=main_subjects,
                          elective_subjects=elective_subjects)

@app.route('/set_subject/<int:class_id>/<int:subject_id>/<subject_type>')
def set_subject(class_id, subject_id, subject_type):
    # Store the selected subject info in the session
    session['class_id'] = class_id
    session['subject_id'] = subject_id
    session['subject_type'] = subject_type
    
    return 'Subject set successfully'

@app.route('/check_class_students/<int:class_id>')
def check_class_students(class_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Count students in the class
    cursor.execute("SELECT COUNT(*) as count FROM students WHERE class_id = ?", (class_id,))
    result = cursor.fetchone()
    student_count = result['count']
    
    cursor.close()
    conn.close()
    
    return jsonify({'has_students': student_count > 0, 'count': student_count})

@app.route('/fallback_feed/<int:class_id>')
def fallback_feed(class_id):
    """Fallback function to generate frames from a static image when webcam is not available"""
    # Get subject info from session at request time
    subject_id = session.get('subject_id')
    subject_type = session.get('subject_type')
    
    def generate_frames():
        # Store the subject info from the request context
        current_subject_id = subject_id
        current_subject_type = subject_type
        
        # Create a fallback image with a message
        fallback_frame = np.ones((480, 640, 3), dtype=np.uint8) * 255  # White background
        
        # Add some text
        cv2.putText(fallback_frame, "Camera not available", (120, 200), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        cv2.putText(fallback_frame, "Using simulation mode", (120, 240), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        cv2.putText(fallback_frame, "Only students with face images will be marked", (70, 280), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        
        # Draw a face-like shape
        cv2.circle(fallback_frame, (320, 120), 60, (0, 0, 255), 2)
        cv2.circle(fallback_frame, (300, 100), 10, (0, 0, 0), -1)  # Left eye
        cv2.circle(fallback_frame, (340, 100), 10, (0, 0, 0), -1)  # Right eye
        cv2.ellipse(fallback_frame, (320, 130), (30, 20), 0, 0, 180, (0, 0, 0), 2)  # Smile
        
        # Mark attendance based on subject selection
        if current_subject_id and current_subject_type:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Get students based on subject type
            if current_subject_type == 'main':
                # For main subjects, get all students in the class
                cursor.execute("SELECT * FROM students WHERE class_id = ? AND image_path IS NOT NULL", (class_id,))
                student_message = "Marking students with face images for main subject"
            else:
                # For elective subjects, only get students who have chosen this elective and have face images
                cursor.execute("SELECT * FROM students WHERE class_id = ? AND elective_subject_id = ? AND image_path IS NOT NULL", 
                             (class_id, current_subject_id))
                
                # Get counts for display
                cursor.execute("SELECT COUNT(*) as count FROM students WHERE class_id = ?", (class_id,))
                total_class_students = cursor.fetchone()['count']
                
                cursor.execute("SELECT COUNT(*) as count FROM students WHERE class_id = ? AND elective_subject_id = ? AND image_path IS NOT NULL", 
                             (class_id, current_subject_id))
                enrolled_with_images = cursor.fetchone()['count']
                
                student_message = f"Marking students with face images: {enrolled_with_images} of {total_class_students}"
            
            students = cursor.fetchall()
            recognized_count = 0
            
            # Add info text
            cv2.putText(fallback_frame, student_message, (50, 320),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            
            # Add student image thumbnails with recognized status
            thumbnail_size = 40
            max_thumbnails = 5
            thumbnail_y = 350
            
            for i, student in enumerate(students[:max_thumbnails]):
                if student['image_path'] and os.path.exists(student['image_path']):
                    try:
                        # Load and resize student image
                        student_img = cv2.imread(student['image_path'])
                        if student_img is not None:
                            student_img = cv2.resize(student_img, (thumbnail_size, thumbnail_size))
                            
                            # Place thumbnail in frame
                            x_offset = 50 + i * (thumbnail_size + 10)
                            fallback_frame[thumbnail_y:thumbnail_y+thumbnail_size, 
                                          x_offset:x_offset+thumbnail_size] = student_img
                            
                            # Add student name under thumbnail
                            name_text = student['name'][:8] + '..' if len(student['name']) > 10 else student['name']
                            cv2.putText(fallback_frame, name_text, 
                                       (x_offset, thumbnail_y + thumbnail_size + 15),
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
                            
                            # Draw green rectangle around thumbnail to indicate recognition
                            cv2.rectangle(fallback_frame, 
                                         (x_offset, thumbnail_y), 
                                         (x_offset+thumbnail_size, thumbnail_y+thumbnail_size), 
                                         (0, 255, 0), 2)
                            recognized_count += 1
                    except Exception as e:
                        print(f"Error processing student thumbnail: {str(e)}")
            
            # Add more info about recognized students
            if recognized_count > 0:
                cv2.putText(fallback_frame, f"Recognized {recognized_count} students with images", 
                           (50, thumbnail_y + thumbnail_size + 40),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                # Mark attendance for students with face images
                today = datetime.date.today().isoformat()
                now = datetime.datetime.now().time().isoformat()
                
                for student in students:
                    if student['image_path'] and os.path.exists(student['image_path']):
                        cursor.execute(
                            "SELECT * FROM attendance WHERE student_id = ? AND date = ? AND subject_id = ? AND subject_type = ?",
                            (student['id'], today, current_subject_id, current_subject_type)
                        )
                        
                        if cursor.fetchone() is None:
                            cursor.execute(
                                "INSERT INTO attendance (student_id, subject_id, subject_type, date, time, status) VALUES (?, ?, ?, ?, ?, ?)",
                                (student['id'], current_subject_id, current_subject_type, today, now, 'present')
                            )
                
                conn.commit()
            else:
                cv2.putText(fallback_frame, "No students with face images found", 
                           (50, thumbnail_y + thumbnail_size + 40),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            
            cursor.close()
            conn.close()
        else:
            # No subject selected warning
            cv2.putText(fallback_frame, "No subject selected - attendance not marked", (50, 320),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        while True:
            # Convert to jpeg format
            ret, buffer = cv2.imencode('.jpg', fallback_frame)
            frame_bytes = buffer.tobytes()
            
            yield (b'--frame\r\n'
                  b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
            # Add a slight delay to reduce CPU usage
            time.sleep(0.1)
    
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/backup_database')
def backup_database():
    """Create a backup of the database file"""
    try:
        import shutil
        from datetime import datetime
        
        # Ensure backup directory exists
        backup_dir = 'backups'
        os.makedirs(backup_dir, exist_ok=True)
        
        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(backup_dir, f'face_attendance_backup_{timestamp}.db')
        
        # Copy the database file
        shutil.copy2(DB_PATH, backup_file)
        
        return jsonify({
            'success': True,
            'message': f'Database backed up successfully to {backup_file}',
            'backup_file': backup_file
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error backing up database: {str(e)}'
        }), 500

@app.route('/restore_database/<path:backup_file>')
def restore_database(backup_file):
    """Restore the database from a backup file"""
    try:
        import shutil
        
        # First create a backup of the current database
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        current_backup = os.path.join('backups', f'pre_restore_backup_{timestamp}.db')
        os.makedirs('backups', exist_ok=True)
        
        # Backup current database
        shutil.copy2(DB_PATH, current_backup)
        
        # Restore from backup file
        shutil.copy2(backup_file, DB_PATH)
        
        return jsonify({
            'success': True,
            'message': f'Database restored successfully from {backup_file}',
            'current_backup': current_backup
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error restoring database: {str(e)}'
        }), 500

@app.route('/database_management')
def database_management():
    """Page for managing database backups and restoration"""
    
    # Get list of available backups
    backup_dir = 'backups'
    os.makedirs(backup_dir, exist_ok=True)
    
    backups = []
    for file in os.listdir(backup_dir):
        if file.endswith('.db'):
            file_path = os.path.join(backup_dir, file)
            file_stats = os.stat(file_path)
            
            # Get file creation time
            created_time = datetime.datetime.fromtimestamp(file_stats.st_ctime)
            
            backups.append({
                'filename': file,
                'path': file_path,
                'size': file_stats.st_size,
                'created': created_time.strftime('%Y-%m-%d %H:%M:%S')
            })
    
    # Sort backups by creation time (newest first)
    backups.sort(key=lambda x: x['created'], reverse=True)
    
    # Get database stats
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Count records in each table
    cursor.execute("SELECT COUNT(*) FROM students")
    student_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM classes")
    class_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM main_subjects")
    main_subject_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM elective_subjects")
    elective_subject_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM attendance")
    attendance_count = cursor.fetchone()[0]
    
    cursor.close()
    conn.close()
    
    stats = {
        'students': student_count,
        'classes': class_count,
        'main_subjects': main_subject_count,
        'elective_subjects': elective_subject_count,
        'attendance': attendance_count,
        'db_file': os.path.abspath(DB_PATH),
        'db_size': os.path.getsize(DB_PATH),
    }
    
    return render_template('database_management.html', 
                          backups=backups, 
                          stats=stats)

@app.route('/process_group_attendance', methods=['POST'])
def process_group_attendance():
    """Process uploaded group photo for attendance marking"""
    try:
        # Check required parameters
        if 'class_id' not in request.form or not request.form['class_id']:
            flash('Error: Class ID is required for attendance', 'danger')
            return redirect(url_for('take_attendance'))
        
        if 'group_photo' not in request.files or request.files['group_photo'].filename == '':
            flash('Error: Group photo is required', 'danger')
            return redirect(url_for('take_attendance'))
        
        class_id = request.form['class_id']
        subject_id = request.form.get('subject_id')
        subject_type = request.form.get('subject_type')
        
        if not subject_id or not subject_type:
            flash('Error: Subject information is missing', 'danger')
            return redirect(url_for('take_attendance'))
        
        # Get class and subject information
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get class name
        cursor.execute("SELECT name FROM classes WHERE id = ?", (class_id,))
        class_result = cursor.fetchone()
        
        if not class_result:
            flash('Error: Invalid class selected', 'danger')
            return redirect(url_for('take_attendance'))
        
        class_name = class_result['name']
        
        # Get subject name
        if subject_type == 'main':
            cursor.execute("SELECT name FROM main_subjects WHERE id = ?", (subject_id,))
        else:
            cursor.execute("SELECT name FROM elective_subjects WHERE id = ?", (subject_id,))
        
        subject_result = cursor.fetchone()
        if not subject_result:
            flash('Error: Invalid subject selected', 'danger')
            return redirect(url_for('take_attendance'))
        
        subject_name = subject_result['name']
        
        # Get students from this class with appropriate subject enrollment
        if subject_type == 'main':
            # For main subjects, get all students in the class
            cursor.execute("""
                SELECT s.id, s.name, s.roll_number, s.image_path 
                FROM students s 
                WHERE s.class_id = ?
            """, (class_id,))
        else:
            # For elective subjects, only get students who have chosen this elective
            cursor.execute("""
                SELECT s.id, s.name, s.roll_number, s.image_path 
                FROM students s 
                WHERE s.class_id = ? AND s.elective_subject_id = ?
            """, (class_id, subject_id))
        
        students = cursor.fetchall()
        
        if not students:
            flash(f'No students found for this {subject_type} subject', 'warning')
            return redirect(url_for('take_attendance'))
        
        # Save and process the uploaded group photo
        group_photo = request.files['group_photo']
        photo_filename = f"group_photo_{class_id}_{subject_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        temp_path = os.path.join(UPLOAD_FOLDER, photo_filename)
        group_photo.save(temp_path)
        
        # Process the group photo for face recognition
        recognized_student_ids, annotated_path = recognize_faces(temp_path, students)
        
        today = datetime.date.today().isoformat()
        now = datetime.datetime.now().time().isoformat()
        
        # Save photo information to database
        cursor.execute("""
            INSERT INTO attendance_photos 
            (class_id, subject_id, subject_type, date, photo_path, annotated_path, 
            faces_detected, students_recognized)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            class_id, 
            subject_id, 
            subject_type, 
            today, 
            '/'.join(temp_path.split(os.sep)[-2:]),  # Relative path for storage
            '/'.join(annotated_path.split(os.sep)[-2:]), 
            len(recognized_student_ids), 
            len(recognized_student_ids)
        ))
        conn.commit()
        
        # Mark attendance for recognized students
        if recognized_student_ids:
            for student_id in recognized_student_ids:
                cursor.execute(
                    "SELECT * FROM attendance WHERE student_id = ? AND date = ? AND subject_id = ? AND subject_type = ?",
                    (student_id, today, subject_id, subject_type)
                )
                
                if cursor.fetchone() is None:
                    cursor.execute(
                        "INSERT INTO attendance (student_id, subject_id, subject_type, date, time, status) VALUES (?, ?, ?, ?, ?, ?)",
                        (student_id, subject_id, subject_type, today, now, 'present')
                    )
                    # Get student name for logging
                    cursor.execute("SELECT name FROM students WHERE id = ?", (student_id,))
                    student = cursor.fetchone()
                    print(f"Marked {student['name']} (ID: {student_id}) as present")
            
            conn.commit()
            session['manual_mode'] = False
            flash(f'Successfully marked {len(recognized_student_ids)} students as present', 'success')
        else:
            flash('No students were recognized in the group photo. No attendance has been marked.', 'warning')
            session['manual_mode'] = True
        
        # Get attendance results after marking
        cursor.execute('''
        SELECT s.id, s.name, s.roll_number, a.status
        FROM students s
        LEFT JOIN attendance a ON s.id = a.student_id AND a.date = ? AND a.subject_id = ? AND a.subject_type = ?
        WHERE s.class_id = ?
        ''', (today, subject_id, subject_type, class_id))
        
        attendance_results = cursor.fetchall()
        
        # Count present students
        present_count = 0
        for student in attendance_results:
            if student['status'] == 'present':
                present_count += 1
        
        cursor.close()
        conn.close()
        
        # Don't remove the original photo - keep it for reference
        
        return render_template('attendance_result.html', 
                            class_name=class_name,
                            subject_name=subject_name,
                            subject_type=subject_type,
                            date=datetime.datetime.today().strftime("%B %d, %Y"),
                            attendance_results=attendance_results,
                            present_count=present_count,
                            total_count=len(attendance_results),
                            group_photo=session.get('annotated_group_photo'),
                            faces_detected=session.get('faces_detected'),
                            students_recognized=session.get('students_recognized'),
                            stats={
                                'total_students': len(students),
                                'faces_detected': session.get('faces_detected', 0),
                                'students_recognized': len(recognized_student_ids),
                                'present_count': present_count,
                                'manual_mode': session.get('manual_mode', False)
                            })
                            
    except Exception as e:
        # Handle any exceptions
        flash(f'Error processing group photo: {str(e)}', 'danger')
        print(f"Exception in process_group_attendance: {str(e)}")
        return redirect(url_for('take_attendance'))

# Add advanced face recognition function
def recognize_faces(group_photo_path, student_photos):
    """
    Recognize faces using the face_recognition library if available,
    otherwise fall back to OpenCV methods.
    
    Args:
        group_photo_path: Path to the group photo
        student_photos: List of dicts with student data including photo paths
        
    Returns:
        List of recognized student IDs
    """
    recognized_students = []
    
    # Load the group photo
    group_img = cv2.imread(group_photo_path)
    if group_img is None:
        print(f"Error: Could not load group photo at {group_photo_path}")
        return []
    
    # Try to use face_recognition library for better accuracy
    if face_recognition is not None:
        print("Using face_recognition library for advanced recognition")
        try:
            # Convert from BGR (OpenCV) to RGB (face_recognition)
            rgb_group_img = cv2.cvtColor(group_img, cv2.COLOR_BGR2RGB)
            
            # Detect face locations in group photo
            group_face_locations = face_recognition.face_locations(rgb_group_img)
            group_face_encodings = face_recognition.face_encodings(rgb_group_img, group_face_locations)
            
            print(f"Detected {len(group_face_locations)} faces in the group photo")
            
            # Process each student photo
            for student in student_photos:
                if student.get('image_path') and os.path.exists(student['image_path']):
                    # Load student image
                    student_img = cv2.imread(student['image_path'])
                    if student_img is not None:
                        # Convert to RGB
                        rgb_student_img = cv2.cvtColor(student_img, cv2.COLOR_BGR2RGB)
                        
                        # Get student face locations
                        student_face_locations = face_recognition.face_locations(rgb_student_img)
                        
                        if student_face_locations:
                            # Get encoding of the first face found
                            student_encoding = face_recognition.face_encodings(rgb_student_img, [student_face_locations[0]])[0]
                            
                            # Check each face in the group photo
                            for i, group_encoding in enumerate(group_face_encodings):
                                # Compare face encodings
                                match = face_recognition.compare_faces([student_encoding], group_encoding, tolerance=0.6)
                                
                                if match[0]:
                                    print(f"Match found for student {student['name']} (ID: {student['id']})")
                                    # Add to recognized students if not already present
                                    if student['id'] not in recognized_students:
                                        recognized_students.append(student['id'])
                                    
                                    # Mark this face as matched (draw green rectangle)
                                    top, right, bottom, left = group_face_locations[i]
                                    cv2.rectangle(group_img, (left, top), (right, bottom), (0, 255, 0), 2)
                                    
                                    # Add name label
                                    cv2.putText(group_img, student['name'], (left, top - 10),
                                              cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                                    
                                    # We found a match for this student, no need to check other faces
                                    break
            
            # Mark unmatched faces with red rectangles
            for i, face_loc in enumerate(group_face_locations):
                top, right, bottom, left = face_loc
                # Check if this face has been marked green already
                if not any(student['id'] in recognized_students for student in student_photos):
                    cv2.rectangle(group_img, (left, top), (right, bottom), (0, 0, 255), 2)
                    cv2.putText(group_img, "Unknown", (left, top - 10),
                              cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            
        except Exception as e:
            print(f"Error with face_recognition: {str(e)}. Falling back to OpenCV methods.")
            # Fall back to OpenCV methods
            return fallback_face_recognition(group_photo_path, student_photos, group_img)
    else:
        # Use OpenCV methods as fallback
        print("face_recognition library not available. Using OpenCV methods.")
        return fallback_face_recognition(group_photo_path, student_photos, group_img)
    
    # Save the annotated image
    annotated_path = os.path.join(os.path.dirname(group_photo_path), 'annotated_group_photo.jpg')
    cv2.imwrite(annotated_path, group_img)
    
    return recognized_students, annotated_path

def fallback_face_recognition(group_photo_path, student_photos, group_img=None):
    """Fallback method using OpenCV and SSIM for face recognition"""
    recognized_student_ids = []
    
    if group_img is None:
        group_img = cv2.imread(group_photo_path)
        if group_img is None:
            print(f"Error: Could not load group photo at {group_photo_path}")
            return []
    
    display_img = group_img.copy()
    gray = cv2.cvtColor(group_img, cv2.COLOR_BGR2GRAY)
    
    # Extract faces
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    
    if len(faces) == 0:
        print("No faces detected with default parameters, trying with different parameters")
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=3, minSize=(20, 20))
    
    print(f"Detected {len(faces)} faces in the group photo")
    
    # Process each face
    for i, (x, y, w, h) in enumerate(faces):
        # Extract face region
        face_roi = gray[y:y+h, x:x+w]
        face_roi = cv2.resize(face_roi, (100, 100))
        face_roi = cv2.equalizeHist(face_roi)
        
        best_match = None
        best_similarity = 0
        best_score = float('inf')
        
        # Compare with each student
        for student in student_photos:
            if student.get('image_path') and os.path.exists(student['image_path']):
                student_img = cv2.imread(student['image_path'])
                if student_img is not None:
                    # Process student image
                    student_gray = cv2.cvtColor(student_img, cv2.COLOR_BGR2GRAY)
                    student_faces = face_cascade.detectMultiScale(student_gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
                    
                    if student_faces:
                        # Extract the face region
                        x_s, y_s, w_s, h_s = student_faces[0]
                        student_face = student_gray[y_s:y_s+h_s, x_s:x_s+w_s]
                        student_face = cv2.resize(student_face, (100, 100))
                        student_face = cv2.equalizeHist(student_face)
                        
                        # Compare using multiple metrics
                        # 1. Template matching (NCC)
                        result = cv2.matchTemplate(face_roi, student_face, cv2.TM_CCORR_NORMED)
                        similarity_score = result[0][0]
                        
                        # 2. MSE
                        diff = cv2.absdiff(face_roi, student_face)
                        mse = np.sum(diff * diff) / float(100 * 100)
                        
                        # 3. SSIM if available
                        try:
                            from skimage.metrics import structural_similarity as ssim
                            ssim_score = ssim(face_roi, student_face)
                        except ImportError:
                            ssim_score = 0.5  # Default if not available
                        
                        # Combined weighted score
                        weighted_score = 0.3 * similarity_score + 0.7 * ssim_score
                        
                        print(f"Face #{i+1} comparison with {student['name']} (ID: {student['id']}): NCC: {similarity_score:.4f}, SSIM: {ssim_score:.4f}, Weighted: {weighted_score:.4f}")
                        
                        if weighted_score > best_similarity:
                            best_similarity = weighted_score
                            best_match = student
                            best_score = mse
        
        # Check if match exceeds threshold
        match_threshold = 0.85  # Set to an appropriate value based on testing
        
        if best_match and best_similarity > match_threshold:
            if best_match['id'] not in recognized_student_ids:
                recognized_student_ids.append(best_match['id'])
            
            # Draw green box for recognized student
            cv2.rectangle(display_img, (x, y), (x+w, y+h), (0, 255, 0), 2)
            text = f"{best_match['name']}"
            y_pos = y - 10 if y - 10 > 10 else y + h + 20
            cv2.putText(display_img, text, (x, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            print(f"Face #{i+1} recognized as {best_match['name']} (ID: {best_match['id']}) with similarity {best_similarity:.4f}")
        else:
            # Draw red box for unrecognized face
            cv2.rectangle(display_img, (x, y), (x+w, y+h), (0, 0, 255), 2)
            cv2.putText(display_img, "Unknown", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            
            if best_match:
                print(f"Face #{i+1} best match was {best_match['name']} but similarity {best_similarity:.4f} below threshold {match_threshold}")
    
    # Save the annotated image
    annotated_path = os.path.join(os.path.dirname(group_photo_path), 'annotated_group_photo.jpg')
    cv2.imwrite(annotated_path, display_img)
    
    return recognized_student_ids, annotated_path

@app.route('/verify_attendance/<string:date>/<int:class_id>/<int:subject_id>/<subject_type>', methods=['GET', 'POST'])
def verify_attendance(date, class_id, subject_id, subject_type):
    """
    Allow manual verification and correction of attendance
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get class and subject info
    cursor.execute("SELECT name FROM classes WHERE id = ?", (class_id,))
    class_name = cursor.fetchone()['name']
    
    if subject_type == 'main':
        cursor.execute("SELECT name FROM main_subjects WHERE id = ?", (subject_id,))
    else:
        cursor.execute("SELECT name FROM elective_subjects WHERE id = ?", (subject_id,))
    subject_name = cursor.fetchone()['name']
    
    if request.method == 'POST':
        try:
            # Process form data for attendance updates
            for key, value in request.form.items():
                if key.startswith('student_'):
                    student_id = int(key.split('_')[1])
                    status = value
                    
                    # Check if attendance record exists
                    cursor.execute("""
                        SELECT id FROM attendance 
                        WHERE student_id = ? AND date = ? AND subject_id = ? AND subject_type = ?
                    """, (student_id, date, subject_id, subject_type))
                    
                    record = cursor.fetchone()
                    
                    if record:
                        # Update existing record
                        cursor.execute("""
                            UPDATE attendance 
                            SET status = ? 
                            WHERE student_id = ? AND date = ? AND subject_id = ? AND subject_type = ?
                        """, (status, student_id, date, subject_id, subject_type))
                    else:
                        # Create new record
                        now = datetime.datetime.now().time().isoformat()
                        cursor.execute("""
                            INSERT INTO attendance (student_id, date, time, status, subject_id, subject_type)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (student_id, date, now, status, subject_id, subject_type))
            
            conn.commit()
            flash('Attendance has been verified and updated successfully', 'success')
        except Exception as e:
            flash(f'Error updating attendance: {str(e)}', 'danger')
    
    # Get student list with current attendance status
    if subject_type == 'main':
        cursor.execute("""
            SELECT s.id, s.name, s.roll_number, a.status
            FROM students s
            LEFT JOIN attendance a ON s.id = a.student_id 
                AND a.date = ? AND a.subject_id = ? AND a.subject_type = ?
            WHERE s.class_id = ?
            ORDER BY s.roll_number
        """, (date, subject_id, subject_type, class_id))
    else:
        cursor.execute("""
            SELECT s.id, s.name, s.roll_number, a.status
            FROM students s
            LEFT JOIN attendance a ON s.id = a.student_id 
                AND a.date = ? AND a.subject_id = ? AND a.subject_type = ?
            WHERE s.class_id = ? AND s.elective_subject_id = ?
            ORDER BY s.roll_number
        """, (date, subject_id, subject_type, class_id, subject_id))
    
    students = cursor.fetchall()
    
    # Get attendance summary
    present_count = sum(1 for student in students if student['status'] == 'present')
    
    # Get group photo if available
    cursor.execute("""
        SELECT photo_path FROM attendance_photos
        WHERE date = ? AND class_id = ? AND subject_id = ? AND subject_type = ?
        LIMIT 1
    """, (date, class_id, subject_id, subject_type))
    photo_record = cursor.fetchone()
    group_photo = photo_record['photo_path'] if photo_record else None
    
    cursor.close()
    conn.close()
    
    return render_template('verify_attendance.html',
                          date=date,
                          formatted_date=datetime.datetime.strptime(date, '%Y-%m-%d').strftime("%B %d, %Y"),
                          class_id=class_id,
                          class_name=class_name,
                          subject_id=subject_id,
                          subject_name=subject_name,
                          subject_type=subject_type,
                          students=students,
                          present_count=present_count,
                          total_count=len(students),
                          group_photo=group_photo)

# Add a route to toggle individual student attendance status via AJAX
@app.route('/toggle_attendance', methods=['POST'])
def toggle_attendance():
    """Toggle a student's attendance status via AJAX"""
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        date = data.get('date')
        subject_id = data.get('subject_id')
        subject_type = data.get('subject_type')
        current_status = data.get('current_status')
        
        # Toggle the status
        new_status = 'absent' if current_status == 'present' else 'present'
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if record exists
        cursor.execute("""
            SELECT id FROM attendance 
            WHERE student_id = ? AND date = ? AND subject_id = ? AND subject_type = ?
        """, (student_id, date, subject_id, subject_type))
        
        record = cursor.fetchone()
        
        if record:
            # Update existing record
            cursor.execute("""
                UPDATE attendance 
                SET status = ? 
                WHERE student_id = ? AND date = ? AND subject_id = ? AND subject_type = ?
            """, (new_status, student_id, date, subject_id, subject_type))
        else:
            # Create new record
            now = datetime.datetime.now().time().isoformat()
            cursor.execute("""
                INSERT INTO attendance (student_id, date, time, status, subject_id, subject_type)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (student_id, date, now, new_status, subject_id, subject_type))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'new_status': new_status,
            'message': f"Attendance status changed to {new_status}"
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f"Error: {str(e)}"
        }), 500

@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now()}

if __name__ == '__main__':
    app.run(debug=True) 